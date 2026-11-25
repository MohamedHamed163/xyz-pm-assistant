"""Project teams (design review 2026-11-25, Q6).

| Action                                   | CEO | PM                     |
|------------------------------------------|-----|------------------------|
| Create a project                         | ✓   | ✗                      |
| Add / remove members on any project      | ✓   | ✗                      |
| Add / remove members on own projects     | ✓   | ✓ (not PMs, not self)  |
| Assign a PM to a project                 | ✓   | ✗                      |
| Change someone's role                    | ✓   | ✗                      |

Invariants: a project that has a PM never loses its last one; the CEO is never a project member
(they see every project). Every change is recorded in membership_changes. Changes apply to the
next question immediately — permissions are loaded from the database on every request.
"""

from __future__ import annotations

from .topics import ROLE_LABEL
from .uploads import Actor, UploadError


def _audit(conn, project_id, user_id, action, detail, actor):
    conn.execute(
        "INSERT INTO membership_changes (project_id, user_id, action, detail, changed_by) VALUES (%s, %s, %s, %s, %s)",
        (project_id, user_id, action, detail, actor.id),
    )


def _my_projects(conn, actor: Actor) -> set[str]:
    return {r[0] for r in conn.execute("SELECT project_id FROM project_members WHERE user_id = %s", (actor.id,))}


def _can_manage(conn, actor: Actor, project_id: str) -> bool:
    return actor.role == "ceo" or (actor.role == "pm" and project_id in _my_projects(conn, actor))


def _user(conn, actor: Actor, user_id: str):
    row = conn.execute("SELECT id, name, role FROM users WHERE id = %s AND company_id = %s AND is_active",
                       (user_id, actor.company_id)).fetchone()
    if row is None:
        raise UploadError(404, "User not found")
    return row


def _project(conn, actor: Actor, project_id: str, *, lock: bool = False):
    row = conn.execute(f"SELECT id, name FROM projects WHERE id = %s AND company_id = %s {'FOR UPDATE' if lock else ''}",
                       (project_id, actor.company_id)).fetchone()
    if row is None:
        raise UploadError(404, "Project not found")
    return row


def team_overview(conn, actor: Actor) -> dict:
    if actor.role not in ("ceo", "pm"):
        raise UploadError(403, "Only the CEO and project managers can manage teams.")
    mine = _my_projects(conn, actor)
    projects = []
    for pid, name, client in conn.execute(
            "SELECT id, name, client_name FROM projects WHERE company_id = %s ORDER BY id", (actor.company_id,)):
        if actor.role != "ceo" and pid not in mine:
            continue
        members = [{"id": u, "name": n, "role": r, "role_label": ROLE_LABEL.get(r, r)} for u, n, r in conn.execute(
            """SELECT u.id, u.name, u.role FROM project_members m JOIN users u ON u.id = m.user_id
               WHERE m.project_id = %s AND u.is_active ORDER BY u.name""", (pid,))]
        projects.append({"id": pid, "name": name, "client": client, "members": members})
    users = [{"id": u, "name": n, "role": r, "role_label": ROLE_LABEL.get(r, r)} for u, n, r in conn.execute(
        "SELECT id, name, role FROM users WHERE company_id = %s AND is_active AND role <> 'ceo' ORDER BY name",
        (actor.company_id,))]
    roles = [{"name": r, "label": ROLE_LABEL.get(r, r)} for (r,) in conn.execute(
        "SELECT name FROM roles WHERE name <> 'ceo' ORDER BY name")]
    return {"projects": projects, "users": users, "roles": roles,
            "can_create_projects": actor.role == "ceo", "can_change_roles": actor.role == "ceo",
            "can_assign_pms": actor.role == "ceo"}


def create_project(conn, actor: Actor, name: str, client: str | None) -> dict:
    if actor.role != "ceo":
        raise UploadError(403, "Only the CEO can create projects.")
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise UploadError(422, "A project needs a name of at most 120 characters.")
    with conn.transaction():
        conn.execute("LOCK TABLE projects IN SHARE ROW EXCLUSIVE MODE")
        n = conn.execute("SELECT coalesce(max(substring(id from 2)::int), 0) + 1 FROM projects WHERE id ~ '^P[0-9]+$'"
                         ).fetchone()[0]
        pid = f"P{n:03d}"
        conn.execute("INSERT INTO projects (id, company_id, name, client_name, aliases) VALUES (%s, %s, %s, %s, %s)",
                     (pid, actor.company_id, name, (client or "").strip() or None, [name]))
        _audit(conn, pid, actor.id, "project_created", name, actor)
    return {"id": pid, "name": name}


def add_member(conn, actor: Actor, project_id: str, user_id: str) -> dict:
    with conn.transaction():
        _project(conn, actor, project_id, lock=True)
        if not _can_manage(conn, actor, project_id):
            raise UploadError(404, "Project not found")
        uid, name, role = _user(conn, actor, user_id)
        if role == "ceo":
            raise UploadError(422, "The CEO already sees every project.")
        if role == "pm" and actor.role != "ceo":
            raise UploadError(403, "Only the CEO can assign a project manager.")
        inserted = conn.execute("INSERT INTO project_members (user_id, project_id) VALUES (%s, %s) "
                                "ON CONFLICT DO NOTHING RETURNING 1", (uid, project_id)).fetchone()
        if inserted:
            _audit(conn, project_id, uid, "add", None, actor)
    return {"project_id": project_id, "user_id": uid, "name": name}


def remove_member(conn, actor: Actor, project_id: str, user_id: str) -> dict:
    with conn.transaction():
        _project(conn, actor, project_id, lock=True)            # serializes concurrent removals
        if not _can_manage(conn, actor, project_id):
            raise UploadError(404, "Project not found")
        uid, name, role = _user(conn, actor, user_id)
        if role == "pm" and actor.role != "ceo":
            raise UploadError(403, "Only the CEO can remove a project manager.")
        if role == "pm":
            pms = conn.execute(
                """SELECT count(*) FROM project_members m JOIN users u ON u.id = m.user_id
                   WHERE m.project_id = %s AND u.role = 'pm' AND u.is_active""", (project_id,)).fetchone()[0]
            if pms <= 1:
                raise UploadError(409, "Every project needs a project manager — assign another PM first.")
        deleted = conn.execute("DELETE FROM project_members WHERE user_id = %s AND project_id = %s RETURNING 1",
                               (uid, project_id)).fetchone()
        if deleted:
            _audit(conn, project_id, uid, "remove", None, actor)
    return {"project_id": project_id, "user_id": uid, "name": name}


def change_role(conn, actor: Actor, user_id: str, role: str) -> dict:
    if actor.role != "ceo":
        raise UploadError(403, "Only the CEO can change roles.")
    with conn.transaction():
        uid, name, old = _user(conn, actor, user_id)
        if uid == actor.id or old == "ceo":
            raise UploadError(422, "The CEO's role can't be changed here.")
        if role == "ceo" or conn.execute("SELECT 1 FROM roles WHERE name = %s", (role,)).fetchone() is None:
            raise UploadError(422, "Choose a valid role.")
        if old == "pm" and role != "pm":
            last = conn.execute(
                """SELECT p.name FROM project_members m JOIN projects p ON p.id = m.project_id
                   WHERE m.user_id = %s AND NOT EXISTS (
                     SELECT 1 FROM project_members m2 JOIN users u2 ON u2.id = m2.user_id
                     WHERE m2.project_id = m.project_id AND u2.role = 'pm' AND u2.id <> %s AND u2.is_active)""",
                (uid, uid)).fetchone()
            if last:
                raise UploadError(409, f"{name} is the only project manager of {last[0]} — assign another PM first.")
        conn.execute("UPDATE users SET role = %s WHERE id = %s", (role, uid))
        _audit(conn, None, uid, "role_change", f"{old} → {role}", actor)
    return {"user_id": uid, "name": name, "role": role, "previous": old}
