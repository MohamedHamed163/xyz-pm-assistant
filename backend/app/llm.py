"""LLM providers for answer generation.

All providers take the two prompt strings built by ``answer.build_prompt`` and return the raw JSON
text ``{"type": "answer"|"chat"|"not_found", "answer": str, "citations": [int]}``. Parsing and validation happen in
``answer.py`` — never trust the provider to format correctly.

- ``OpenAIChatLLM``: OpenAI Chat Completions with a strict JSON schema. Model from OPENAI_MODEL.
- ``ExtractiveLLM``: offline, deterministic. Picks the passage with the most keyword overlap and
  quotes its most relevant lines. Lets the demo and tests run without an API key.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Protocol

from .embeddings import _STOPWORDS


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class LLMError(RuntimeError):
    pass


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["answer", "chat", "not_found"]},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["type", "answer", "citations"],
    "additionalProperties": False,
}


class OpenAIChatLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 60):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        self.name = f"openai/{self.model}"
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "grounded_answer", "strict": True, "schema": ANSWER_SCHEMA},
            },
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.load(resp)
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMError(f"OpenAI chat call failed: {exc}") from exc


_PASSAGE = re.compile(
    r'<passage id="(\d+)" document="([^"]*)" section="([^"]*)" project="([^"]*)"[^>]*>\n(.*?)\n</passage>',
    re.DOTALL,
)
_PROJECT_ID = re.compile(r"\bP\d{3}\b", re.IGNORECASE)


class ExtractiveLLM:
    """Offline stand-in for an LLM. Not smart — only quotes passages — but follows the same contract."""

    name = "offline-extractive"

    def __init__(self, min_overlap: int = 2, max_lines: int = 10):
        self.min_overlap = min_overlap
        self.max_lines = max_lines

    def complete(self, system: str, user: str) -> str:
        question = user.split("\n", 1)[0].removeprefix("Question: ")
        chat = _offline_chat(question, _profile(user))
        if chat:
            return json.dumps({"type": "chat", "answer": chat, "citations": []})
        keywords = _keywords(_PROJECT_ID.sub(" ", question))
        wanted_projects = {p.upper() for p in _PROJECT_ID.findall(question)}
        needed = 1 if len(keywords) <= 2 else self.min_overlap
        best, best_score = None, 0
        for pid, doc, section, project, body in _PASSAGE.findall(user):
            if wanted_projects and project not in wanted_projects and project != "company-wide":
                continue
            heading_hits = len(keywords & _keywords(f"{doc} {section}"))
            score = len(keywords & _keywords(body)) + 2 * heading_hits
            if score > best_score:
                best, best_score = (int(pid), doc, section, body, heading_hits), score
        if best is None or best_score < needed:
            return json.dumps({"type": "not_found", "answer": "", "citations": []})
        pid, doc, section, body, heading_hits = best
        lines = [l.strip() for l in body.splitlines() if l.strip() and not l.startswith(doc)]
        # Heading matched: the whole section is the answer (keeps tables intact). Else pick matching lines.
        relevant = lines if heading_hits else ([l for l in lines if keywords & _keywords(l)] or lines)
        quote = _join_markdown_lines(relevant[: self.max_lines])
        return json.dumps({
            "type": "answer",
            "answer": f"From {doc} — {section} [{pid}]:\n{quote}",
            "citations": [pid],
        })


_GREETING = re.compile(r"^\s*(hi|hello|hey|hiya|salam|salaam|good (morning|afternoon|evening)|yo)\b", re.I)
_THANKS = re.compile(r"\b(thanks|thank you|thx|cheers)\b", re.I)
_IDENTITY = re.compile(r"\b(my name|who am i|my role|what am i)\b", re.I)
_ACCESS = re.compile(r"\b(which|what) projects\b.*\b(i|me)\b|\bwhat can i (see|access|ask)\b", re.I)
_HELP = re.compile(r"^\s*(help|what can you do|how can you help|who are you)\b", re.I)


def _profile(user_prompt: str) -> dict[str, str]:
    block = re.search(r"<user_profile>\n(.*?)\n</user_profile>", user_prompt, re.DOTALL)
    if not block:
        return {}
    return dict(line.split(": ", 1) for line in block.group(1).splitlines() if ": " in line)


def _offline_chat(question: str, profile: dict[str, str]) -> str | None:
    """Canned conversational replies so the offline demo can greet and answer profile questions."""
    name = profile.get("name", "there")
    role = profile.get("role", "user")
    projects = profile.get("projects they can ask about", "your projects")
    if _IDENTITY.search(question):
        return f"You're {name}, signed in as {role}. You can ask me about {projects}."
    if _ACCESS.search(question):
        return f"You can ask me about {projects}."
    if _HELP.search(question):
        return (f"I answer questions about {projects} — requirements, architecture, bugs, milestones and more — "
                "using only documents you're allowed to read, with sources.")
    if _GREETING.search(question) and len(_keywords(question)) <= 2:
        return f"Hi {name}! What would you like to know about {projects}?"
    if _THANKS.search(question) and len(_keywords(question)) <= 3:
        return "You're welcome! Anything else?"
    return None


def _join_markdown_lines(lines: list[str]) -> str:
    """Join lines, keeping a blank line wherever a table starts or ends so Markdown doesn't merge them."""
    out: list[str] = []
    for line in lines:
        if out and out[-1].startswith("|") != line.startswith("|"):
            out.append("")
        out.append(line)
    return "\n".join(out)


def _keywords(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"\w+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _stem(word: str) -> str:
    """Crude plural folding: milestones→milestone, issues→issue, projects→project."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def default_llm() -> LLM:
    return OpenAIChatLLM() if os.environ.get("OPENAI_API_KEY") else ExtractiveLLM()
