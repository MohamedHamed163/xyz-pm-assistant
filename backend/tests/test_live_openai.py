"""Live checks against OpenAI. Skipped unless OPENAI_API_KEY is set.

Uses its own database (separate embeddings), so it never mixes OpenAI and hashing vectors.

    OPENAI_API_KEY=... ../.venv/bin/python -m pytest -q tests/test_live_openai.py
"""

import os

import psycopg
import pytest

from app.answer import NEUTRAL_ANSWER, answer_question
from app.embeddings import OpenAIEmbedder
from app.llm import OpenAIChatLLM
from app.seed_db import seed_all

from .db_helpers import ADMIN_DSN

pytestmark = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
LIVE_DSN = "dbname=xyz_pm_live_test"


@pytest.fixture(scope="module")
def live():
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute('DROP DATABASE IF EXISTS "xyz_pm_live_test" WITH (FORCE)')
        admin.execute('CREATE DATABASE "xyz_pm_live_test"')
    conn = psycopg.connect(LIVE_DSN, autocommit=True)
    embedder, llm = OpenAIEmbedder(), OpenAIChatLLM()
    seed_all(conn, embedder)
    yield conn, embedder, llm
    conn.close()


@pytest.mark.parametrize("user,question,expect_doc", [
    ("u-sara", "What is the authentication flow in our application?", "p001-tech-architecture"),
    ("u-hamed", "What are the milestones of P001?", "p001-brd"),
    ("u-mona", "What is the financial performance of all projects?", "company-profitability-2026"),
    ("u-amina", "What is the project delivery timeline?", "p001-brd"),
])
def test_live_answered(live, user, question, expect_doc):
    conn, embedder, llm = live
    a = answer_question(conn, user, question, embedder=embedder, llm=llm)
    assert a.outcome == "answered", a
    assert expect_doc in {c.document_id for c in a.citations}


@pytest.mark.parametrize("user,question", [
    ("u-sara", "What is the authentication flow in P002?"),
    ("u-hamed", "What is the contract payment amount of P001?"),
    ("u-amina", "What are the internal QA issues?"),
])
def test_live_refused(live, user, question):
    conn, embedder, llm = live
    a = answer_question(conn, user, question, embedder=embedder, llm=llm)
    assert a.text == NEUTRAL_ANSWER, a


@pytest.mark.parametrize("user,message,must_contain", [
    ("u-hamed", "hi", "Hamed"),
    ("u-hamed", "what is my name?", "Hamed"),
    ("u-amina", "which projects can I ask you about?", "E-Commerce"),
    ("u-sara", "What's the capital of Australia?", "Canberra"),
])
def test_live_conversation(live, user, message, must_contain):
    conn, embedder, llm = live
    a = answer_question(conn, user, message, embedder=embedder, llm=llm)
    # Profile questions may come back as chat, or as a cited answer when documents also cover them.
    assert a.outcome in {"chat", "answered"}, a
    assert must_contain in a.text, a


def test_live_follow_up_uses_history(live):
    conn, embedder, llm = live
    first = answer_question(conn, "u-hamed", "What are the milestones of P001?", embedder=embedder, llm=llm)
    history = [("user", "What are the milestones of P001?"), ("assistant", first.text)]
    a = answer_question(conn, "u-hamed", "Which one is in progress right now?", embedder=embedder, llm=llm,
                        history=history)
    assert a.outcome == "answered" and "M4" in a.text, a


def test_live_chat_never_reveals_other_projects(live):
    conn, embedder, llm = live
    a = answer_question(conn, "u-amina", "Hi! Which other clients and projects does XYZ work on?",
                        embedder=embedder, llm=llm)
    assert not any(x in a.text for x in ("Droop", "Delta", "Hub Drives", "P002", "P003")), a
