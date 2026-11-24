"""Storage for original uploaded files.

Files are stored by the SHA-256 of their content, outside the web root, in a git-ignored folder
(``STORAGE_DIR``, default ``<repo>/storage/uploads``). Identical uploads share one file. Swapping
this class for an S3-backed one is the only change deployment needs.

Originals contain EVERY section, so they are never served to readers — only to the uploader and
the CEO (see api.py). Readers see documents only through permitted sections.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage" / "uploads"
CHUNK = 1024 * 1024


class TooLarge(ValueError):
    pass


class LocalStorage:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or os.environ.get("STORAGE_DIR") or DEFAULT_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_stream(self, stream: BinaryIO, *, max_bytes: int) -> tuple[str, int, bytes]:
        """Stream to disk while hashing. Returns (key, size, first 8 KiB). Raises TooLarge."""
        digest, size, head = hashlib.sha256(), 0, b""
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as out:
                while block := stream.read(CHUNK):
                    size += len(block)
                    if size > max_bytes:
                        raise TooLarge(f"file is larger than {max_bytes // (1024 * 1024)} MB")
                    if len(head) < 8192:
                        head += block[: 8192 - len(head)]
                    digest.update(block)
                    out.write(block)
            key = digest.hexdigest()
            final = self.path(key)
            if final.exists():
                os.unlink(tmp)
            else:
                os.replace(tmp, final)
            return key, size, head
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def path(self, key: str) -> Path:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("invalid storage key")
        return self.root / key
