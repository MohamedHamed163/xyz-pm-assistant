import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type Me, type Team as TeamData } from "./api";

// Project teams. CEO: create projects, add/remove anyone, assign PMs, change roles.
// PM: add/remove non-PM members on their own projects. Changes apply to the next question.

export default function Team({ me }: { me: Me }) {
  const [team, setTeam] = useState<TeamData | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [adding, setAdding] = useState<Record<string, string>>({});
  const [newProject, setNewProject] = useState({ name: "", client: "" });

  const load = useCallback(() => api.team().then(setTeam), []);
  useEffect(() => {
    load();
  }, [load]);

  async function run(action: () => Promise<unknown>, success: string) {
    setMessage(null);
    try {
      await action();
      setMessage(success);
      await load();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "That didn't work");
    }
  }

  async function createProject(e: FormEvent) {
    e.preventDefault();
    await run(() => api.createProject(newProject.name, newProject.client), `Created project “${newProject.name}”.`);
    setNewProject({ name: "", client: "" });
  }

  if (!team) return <p className="muted pad">Loading…</p>;

  return (
    <div className="team">
      {message && <p className="notice-bar" role="status">{message}</p>}

      {team.projects.map((p) => {
        const memberIds = new Set(p.members.map((m) => m.id));
        const candidates = team.users.filter((u) => !memberIds.has(u.id) && (team.can_assign_pms || u.role !== "pm"));
        return (
          <section key={p.id} className="team-project">
            <header>
              <strong>
                {p.id} · {p.name}
              </strong>
              {p.client && <span className="muted small"> · client: {p.client}</span>}
            </header>
            <ul className="member-list">
              {p.members.map((m) => (
                <li key={m.id}>
                  <span className={`avatar small role-${m.role}`} aria-hidden>
                    {m.name[0]}
                  </span>
                  <span className="member-name">{m.name}</span>
                  {team.can_change_roles && m.id !== me.id ? (
                    <select
                      className="role-select"
                      value={m.role}
                      aria-label={`Role of ${m.name}`}
                      onChange={(e) => run(() => api.changeRole(m.id, e.target.value), `${m.name} is now ${e.target.selectedOptions[0].text}.`)}
                    >
                      {team.roles.map((r) => (
                        <option key={r.name} value={r.name}>
                          {r.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className={`role-badge role-${m.role}`}>{m.role_label}</span>
                  )}
                  {(team.can_assign_pms || m.role !== "pm") && (
                    <button
                      className="link-btn danger"
                      onClick={() => run(() => api.removeMember(p.id, m.id), `Removed ${m.name} from ${p.name}.`)}
                    >
                      Remove
                    </button>
                  )}
                </li>
              ))}
              {p.members.length === 0 && <li className="muted small">No members yet.</li>}
            </ul>
            {candidates.length > 0 && (
              <div className="add-member">
                <select
                  value={adding[p.id] ?? ""}
                  onChange={(e) => setAdding({ ...adding, [p.id]: e.target.value })}
                  aria-label={`Add a member to ${p.name}`}
                >
                  <option value="">Add a member…</option>
                  {candidates.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} — {u.role_label}
                    </option>
                  ))}
                </select>
                <button
                  className="btn-secondary"
                  disabled={!adding[p.id]}
                  onClick={() =>
                    run(() => api.addMember(p.id, adding[p.id]), `Added ${team.users.find((u) => u.id === adding[p.id])?.name} to ${p.name}.`).then(
                      () => setAdding({ ...adding, [p.id]: "" }),
                    )
                  }
                >
                  Add
                </button>
              </div>
            )}
          </section>
        );
      })}

      {team.can_create_projects && (
        <form className="team-project new-project" onSubmit={createProject}>
          <strong>New project</strong>
          <div className="form-row">
            <input placeholder="Project name" value={newProject.name} maxLength={120} required
              onChange={(e) => setNewProject({ ...newProject, name: e.target.value })} />
            <input placeholder="Client (optional)" value={newProject.client} maxLength={120}
              onChange={(e) => setNewProject({ ...newProject, client: e.target.value })} />
            <button className="btn-primary" type="submit">
              Create
            </button>
          </div>
        </form>
      )}
      <p className="muted small">Changes take effect on each person's next question. Every change is recorded.</p>
    </div>
  );
}
