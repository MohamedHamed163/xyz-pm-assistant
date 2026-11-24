"""Background worker: parsing and embedding as separate loops (upload-feature design Q7).

A slow 300-page PDF in the parse loop never delays another document going live in the embed loop.
Drafts older than 7 days are discarded by the parse loop every 10 minutes.

    cd backend && ../.venv/bin/python -m app.worker        # standalone (production)

In development the API starts both loops in-process (WORKER_IN_PROCESS=true, the default).
"""

from __future__ import annotations

import logging
import os
import threading
import time

from .db import connect
from .embeddings import Embedder, default_embedder
from .ingestion import process_next
from .storage import LocalStorage
from .uploads import expire_drafts, parse_next

log = logging.getLogger("xyz.worker")
EXPIRE_EVERY = 600


def parse_loop(stop: threading.Event, storage: LocalStorage, *, dsn: str | None = None, poll: float = 1.0) -> None:
    last_expire = 0.0
    while not stop.is_set():
        try:
            with connect(dsn) as conn:
                while not stop.is_set():
                    if time.monotonic() - last_expire > EXPIRE_EVERY:
                        if n := expire_drafts(conn, storage):
                            log.info("expired %d draft(s)", n)
                        last_expire = time.monotonic()
                    if parse_next(conn, storage) is None:
                        stop.wait(poll)
        except Exception:
            log.exception("parse loop crashed; restarting in 5s")
            stop.wait(5)


def embed_loop(stop: threading.Event, embedder: Embedder, *, dsn: str | None = None, poll: float = 1.0) -> None:
    while not stop.is_set():
        try:
            with connect(dsn) as conn:
                while not stop.is_set():
                    if process_next(conn, embedder) is None:
                        stop.wait(poll)
        except Exception:
            log.exception("embed loop crashed; restarting in 5s")
            stop.wait(5)


def start_in_background(embedder: Embedder, storage: LocalStorage, *, dsn: str | None = None) -> threading.Event:
    stop = threading.Event()
    for target, args in ((parse_loop, (stop, storage)), (embed_loop, (stop, embedder))):
        threading.Thread(target=target, args=args, kwargs={"dsn": dsn}, daemon=True, name=target.__name__).start()
    return stop


def worker_in_process() -> bool:
    return os.environ.get("WORKER_IN_PROCESS", "true").lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    stop = start_in_background(default_embedder(), LocalStorage())
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop.set()
