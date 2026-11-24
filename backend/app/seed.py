"""Load the demo company (users, role policy, grants) from data/seed/company.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from .policy import Grant, RolePolicy, User

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = REPO_ROOT / "data" / "seed" / "company.yaml"
DOCUMENTS_DIR = REPO_ROOT / "data" / "documents"


@dataclass(frozen=True)
class Company:
    id: str
    name: str
    project_ids: frozenset[str]
    doc_types: dict[str, dict]
    role_policies: dict[str, RolePolicy]
    users: dict[str, User]
    grants: tuple[Grant, ...]

    def user_by_name(self, name: str) -> User:
        for u in self.users.values():
            if u.name.lower() == name.lower():
                return u
        raise KeyError(name)


def load_company(path: Path = SEED_FILE) -> Company:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    company_id = raw["company"]["id"]
    project_ids = frozenset(p["id"] for p in raw["projects"])
    doc_types = raw["doc_types"]

    role_policies = {}
    for role, spec in raw["role_policy"].items():
        unknown = set(spec["doc_types"]) - set(doc_types)
        if unknown:
            raise ValueError(f"role '{role}' references unknown doc types {unknown}")
        role_policies[role] = RolePolicy(
            scope=spec["scope"],
            doc_types=frozenset(spec["doc_types"]),
            shared_only=bool(spec.get("shared_only", False)),
        )

    users = {}
    for u in raw["users"]:
        unknown = set(u["projects"]) - project_ids
        if unknown:
            raise ValueError(f"user '{u['id']}' assigned to unknown projects {unknown}")
        users[u["id"]] = User(u["id"], u["name"], u["role"], company_id, frozenset(u["projects"]))

    grants = tuple(
        Grant(
            user_id=g["user"],
            document_id=g["document"],
            expires_at=datetime.fromisoformat(g["expires_at"]) if g.get("expires_at") else None,
        )
        for g in raw.get("grants", [])
    )
    return Company(company_id, raw["company"]["name"], project_ids, doc_types, role_policies, users, grants)
