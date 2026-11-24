"""XYZ PM Assistant backend.

On import, loads ``.env`` from the repository root (if present) into the environment. Variables that
are already set win, so a shell ``export`` always overrides the file. ``.env`` is git-ignored.
"""

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv(Path(__file__).resolve().parents[2] / ".env")
