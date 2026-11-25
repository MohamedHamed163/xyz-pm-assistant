"""Live checks against OpenAI. Skipped unless OPENAI_API_KEY is set.

Uses its own database (separate embeddings), so it never mixes OpenAI and hashing vectors.

    ../.venv/bin/python -m pytest -q tests/test_live_openai.py
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
    seed_all(conn, embedder, with_documents=True)
    yield conn, embedder, llm
    conn.close()


def ask(live, user, question, **kw):
    conn, embedder, llm = live
    return answer_question(conn, user, question, embedder=embedder, llm=llm, **kw)


@pytest.mark.parametrize("user,question,expect_doc", [
    ("u-omar", "What are the business rules of Droob AI?", "droob-brd"),
    ("u-omar", "When is the Droob project considered complete?", "droob-proposal"),
    ("u-sara", "How long will the project take?", "droob-proposal"),
    ("u-khaled", "What are the payment terms?", "droob-proposal"),
    ("u-amina", "What are the business goals?", "droob-brd"),
    ("u-youssef", "How do renters verify their identity?", "hub-brd"),
])
def test_live_answered(live, user, question, expect_doc):
    a = ask(live, user, question)
    assert a.outcome == "answered", a
    assert expect_doc in {c.document_id for c in a.citations}


def test_live_qa_asking_for_prices_gets_the_rule_not_the_price(live):
    a = ask(live, "u-omar", "How much does Plan 2 cost?")
    assert "$" not in a.text and "1,000" not in a.text, a
    assert a.outcome in {"chat", "not_in_context"}, a
    if a.outcome == "chat":
        assert "commercial" in a.text.lower(), a          # the rule is explained


def test_live_developer_asking_for_business_rules_gets_the_rule(live):
    a = ask(live, "u-sara", "What are the business rules?")
    assert "authenticated users" not in a.text.lower() and a.citations == [], a


def test_live_other_project_is_neutral(live):
    assert ask(live, "u-youssef", "What are Droob AI's business goals?").text == NEUTRAL_ANSWER


@pytest.mark.parametrize("user,message,must_contain", [
    ("u-hamed", "hi", "Hamed"),
    ("u-hamed", "what is my name?", "Hamed"),
    ("u-sara", "What's the capital of Australia?", "Canberra"),
])
def test_live_conversation(live, user, message, must_contain):
    a = ask(live, user, message)
    assert a.outcome in {"chat", "answered"} and must_contain in a.text, a


def test_live_follow_up_uses_history(live):
    first = ask(live, "u-omar", "What are the business rules?")
    a = ask(live, "u-omar", "Which of those is about document processing?",
            history=[("user", "What are the business rules?"), ("assistant", first.text)])
    assert a.outcome == "answered" and "process" in a.text.lower(), a


@pytest.mark.parametrize("question", ["What's the weather in Paris tomorrow?", "Give me a recipe for pancakes"])
def test_live_off_topic_is_chat_without_sources(live, question):
    a = ask(live, "u-sara", question)
    assert a.citations == [] and a.outcome in {"chat", "not_in_context"}, a


@pytest.mark.parametrize("user,question,topic_word", [
    ("u-youssef", "What are the business rules for renters?", "rules"),
    ("u-khaled", "What are the functional requirements?", "requirement"),
])
def test_live_restricted_topic_is_explained_not_substituted(live, user, question, topic_word):
    a = ask(live, user, question)
    assert a.outcome == "chat" and a.citations == [] and topic_word in a.text.lower(), a
