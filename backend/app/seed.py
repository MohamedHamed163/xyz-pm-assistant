"""Load the demo company (users, projects, topic rules) from data/seed/company.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .policy import RolePolicy, User
from .topics import TopicRules, rules_from_dict

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = REPO_ROOT / "data" / "seed" / "company.yaml"
DOCUMENTS_DIR = REPO_ROOT / "data" / "documents"


@dataclass(frozen=True)
class Company:
    id: str
    name: str
    project_ids: frozenset[str]
    rules: TopicRules
    role_policies: dict[str, RolePolicy]
    users: dict[str, User]

    def user_by_name(self, name: str) -> User:
        for u in self.users.values():
            if u.name.lower() == name.lower():
                return u
        raise KeyError(name)


def load_company(path: Path = SEED_FILE) -> Company:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    company_id = raw["company"]["id"]
    project_ids = frozenset(p["id"] for p in raw["projects"])
    rules = rules_from_dict(raw)
    role_policies = {role: RolePolicy(rules.role_scope[role], rules.access_keys(role)) for role in rules.role_access}

    users = {}
    for u in raw["users"]:
        if u["role"] not in role_policies:
            raise ValueError(f"user '{u['id']}' has unknown role {u['role']!r}")
        unknown = set(u["projects"]) - project_ids
        if unknown:
            raise ValueError(f"user '{u['id']}' assigned to unknown projects {unknown}")
        users[u["id"]] = User(u["id"], u["name"], u["role"], company_id, frozenset(u["projects"]))
    return Company(company_id, raw["company"]["name"], project_ids, rules, role_policies, users)
