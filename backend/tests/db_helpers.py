"""Shared helpers for tests that need a real Postgres + pgvector database."""

import os
import threading
import time

import psycopg
import pytest

from app.db import connect
from app.embeddings import HashingEmbedder

TEST_DSN = os.environ.get("XYZ_TEST_DSN", "dbname=xyz_pm_test")
ADMIN_DSN = os.environ.get("XYZ_ADMIN_DSN", "dbname=postgres")


def recreate_test_database() -> None:
    dbname = psycopg.conninfo.conninfo_to_dict(TEST_DSN)["dbname"]
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
            admin.execute(f'CREATE DATABASE "{dbname}"')
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not available: {exc}")


def new_conn() -> psycopg.Connection:
    return connect(TEST_DSN)


def make_doc(doc_id: str, *, body: str, version: str = "1", project: str = "P001",
             doc_type: str = "prd", heading: str = "Body") -> str:
    """A one-section Markdown document. The default heading "Body" matches no topic → unclassified."""
    project_line = f"project: {project}" if project else "project: null"
    return (
        f"---\nid: {doc_id}\ntitle: Test {doc_id}\n{project_line}\ndoc_type: {doc_type}\nversion: \"{version}\"\n---\n"
        f"# Test {doc_id}\n\n## {heading}\n\n{body}\n"
    )


class FailingEmbedder:
    name = "failing"

    def __init__(self, fail_times: int = 10**9):
        self.remaining = fail_times
        self.inner = HashingEmbedder()

    def embed(self, texts):
        if self.remaining > 0:
            self.remaining -= 1
            raise RuntimeError("simulated OpenAI 503")
        return self.inner.embed(texts)


class SlowEmbedder:
    name = "slow"

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.inner = HashingEmbedder()

    def embed(self, texts):
        time.sleep(self.seconds)
        return self.inner.embed(texts)


def run_in_threads(*fns):
    results, errors = [None] * len(fns), []

    def wrap(i, fn):
        try:
            results[i] = fn()
        except Exception as exc:  # surfaced to the test
            errors.append(exc)

    threads = [threading.Thread(target=wrap, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    if errors:
        raise errors[0]
    return results
