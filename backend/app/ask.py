"""Ask a question as a demo user from the command line.

    cd backend && ../.venv/bin/python -m app.ask sara "What is the authentication flow in P001?"
"""

from __future__ import annotations

import sys

from .answer import answer_question
from .db import connect
from .embeddings import default_embedder
from .llm import default_llm


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    who, question = argv
    embedder, llm = default_embedder(), default_llm()
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, role FROM users WHERE id = %s OR lower(name) = lower(%s)", (who, who)
        ).fetchone()
        if row is None:
            print(f"unknown user: {who}")
            return 2
        user_id, name, role = row
        answer = answer_question(conn, user_id, question, embedder=embedder, llm=llm)
    print(f"{name} ({role}) asks: {question}\n")
    print(answer.text)
    if answer.citations:
        print("\nSources:")
        for c in answer.citations:
            print(f"  [{c.number}] {c.document_title} — {c.heading}")
    print(f"\n(outcome: {answer.outcome} · embedder: {embedder.name} · llm: {llm.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
