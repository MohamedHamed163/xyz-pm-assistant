// Thin typed client for the FastAPI backend. All requests go through the Vite proxy at /api.

export type Outcome = "answered" | "no_answer" | "error";

export interface Citation {
  number: number;
  chunk_id: number;
  document_id: string;
  document_title: string;
  heading: string;
  snippet: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  outcome: Outcome | null;
  citations: Citation[];
  created_at: string;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Me {
  id: string;
  name: string;
  email: string;
  role: string;
  role_label: string;
  organization: string | null;
  projects: { id: string; name: string }[];
  company_wide: boolean;
  access: Record<string, string[]>;
  can_upload: boolean;
}

export interface TopicInfo {
  key: string;
  label: string;
  roles: string[];
}

export interface UploadOptions {
  can_upload: boolean;
  projects: { id: string; name: string }[];
  doc_types: { name: string; label: string }[];
  topics: Record<string, TopicInfo[]>;
}

export interface UploadItem {
  id: number;
  title: string;
  project_id: string | null;
  doc_type: string;
  status: "parsing" | "draft" | "processing" | "ready" | "failed" | "superseded";
  error: string | null;
  file_name: string;
  created_at: string;
  is_new_version: boolean;
  unclassified: number;
}

export interface ReviewRequest {
  id: number;
  title: string;
  project_id: string;
  doc_type: string;
  file_name: string;
  created_at: string;
  uploaded_by: string;
  unclassified: number;
}

export interface DraftSection {
  ordinal?: number;
  heading: string;
  content: string;
  topic: string;
  topic_label?: string;
  changed?: boolean;
  previous_topic?: string | null;
}

export interface Draft {
  id: number;
  document_id: string;
  status: UploadItem["status"];
  error: string | null;
  file_name: string;
  file_size: number;
  page_count: number | null;
  kind: "pdf" | "docx";
  title: string;
  project_id: string | null;
  project_name: string | null;
  doc_type: string;
  is_new_version: boolean;
  published: boolean;
  draft_expires_at: string | null;
  lock_version: number;
  last_edited_by: string | null;
  can_download: boolean;
  sections: DraftSection[];
  summary: Record<string, number>;
  unclassified: number;
}

export interface ManagedDocument {
  id: string;
  title: string;
  project_id: string | null;
  project_name: string | null;
  doc_type: string;
  updated_at: string;
  can_restore: boolean;
  sections: { ordinal: number; heading: string; topic: string; topic_label: string }[];
}

export interface TeamMember {
  id: string;
  name: string;
  role: string;
  role_label: string;
}

export interface Team {
  projects: { id: string; name: string; client: string | null; members: TeamMember[] }[];
  users: TeamMember[];
  roles: { name: string; label: string }[];
  can_create_projects: boolean;
  can_change_roles: boolean;
  can_assign_pms: boolean;
}

export interface DemoUser {
  id: string;
  name: string;
  email: string;
  role: string;
  organization: string | null;
  projects: string[];
}

export interface Source {
  chunk_id: number;
  document_id: string;
  document_title: string;
  project_id: string | null;
  heading: string;
  content: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "xyz-pm-token";
let token: string | null = readStoredToken();
let onUnauthorized: () => void = () => {};

function readStoredToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(value: string | null) {
  token = value;
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token lives in memory only */
  }
}

export const hasToken = () => token !== null;
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (typeof init.body === "string") headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the API running?");
  }
  if (res.status === 401 && token) {
    setToken(null);
    onUnauthorized();
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null) as [string, string][];
  return entries.length ? `?${new URLSearchParams(entries)}` : "";
};

export const api = {
  demoUsers: () => request<{ password: string; users: DemoUser[] }>("/auth/demo-users"),
  login: async (email: string, password: string) => {
    const r = await request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setToken(r.access_token);
  },
  me: () => request<Me>("/me"),
  conversations: (cursor?: string | null) =>
    request<{ items: Conversation[]; next_cursor: string | null }>(`/conversations${qs({ limit: 30, cursor })}`),
  createConversation: () => request<Conversation>("/conversations", { method: "POST", body: "{}" }),
  deleteConversation: (id: number) => request<void>(`/conversations/${id}`, { method: "DELETE" }),
  messages: (id: number, before?: string | null) =>
    request<{ items: Message[]; next_before: string | null }>(
      `/conversations/${id}/messages${qs({ limit: 50, before })}`,
    ),
  ask: (id: number, question: string) =>
    request<{ user_message: Message; assistant_message: Message; conversation_title: string }>(
      `/conversations/${id}/messages`,
      { method: "POST", body: JSON.stringify({ question }) },
    ),
  source: (chunkId: number) => request<Source>(`/citations/${chunkId}`),

  uploadOptions: () => request<UploadOptions>("/uploads/options"),
  createUpload: (file: File, fields: { doc_type?: string; project_id?: string; title?: string; document_id?: string }) => {
    const form = new FormData();
    form.append("file", file);
    for (const [k, v] of Object.entries(fields)) if (v !== undefined) form.append(k, v);
    return request<{ id: number; status: string }>("/uploads", { method: "POST", body: form });
  },
  uploads: () => request<{ items: UploadItem[] }>("/uploads"),
  upload: (id: number) => request<Draft>(`/uploads/${id}`),
  saveSections: (id: number, sections: DraftSection[], lockVersion: number) =>
    request<Draft>(`/uploads/${id}/sections`, {
      method: "PUT",
      body: JSON.stringify({
        sections: sections.map(({ heading, content, topic }) => ({ heading, content, topic })),
        lock_version: lockVersion,
      }),
    }),
  reviewRequests: () => request<{ items: ReviewRequest[] }>("/uploads/review-requests"),
  publish: (id: number) =>
    request<{ status: string; summary: Record<string, number> }>(`/uploads/${id}/publish`, { method: "POST" }),
  discard: (id: number) => request<void>(`/uploads/${id}/discard`, { method: "POST" }),
  downloadOriginal: async (id: number, fileName: string) => {
    const res = await fetch(`/api/uploads/${id}/file`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new ApiError(res.status, "Download failed");
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: fileName });
    a.click();
    URL.revokeObjectURL(url);
  },
  managedDocuments: () => request<{ items: ManagedDocument[] }>("/documents/manage"),
  setTopic: (documentId: string, ordinal: number, topic: string) =>
    request<{ previous: string }>(`/documents/${encodeURIComponent(documentId)}/sections/${ordinal}`, {
      method: "PATCH",
      body: JSON.stringify({ topic }),
    }),
  restorePrevious: (documentId: string) =>
    request<{ current_version_id: number }>(`/documents/${encodeURIComponent(documentId)}/restore-previous`, {
      method: "POST",
    }),

  team: () => request<Team>("/team"),
  createProject: (name: string, client: string) =>
    request<{ id: string }>("/team/projects", { method: "POST", body: JSON.stringify({ name, client }) }),
  addMember: (projectId: string, userId: string) =>
    request<unknown>(`/team/projects/${projectId}/members`, { method: "POST", body: JSON.stringify({ user_id: userId }) }),
  removeMember: (projectId: string, userId: string) =>
    request<unknown>(`/team/projects/${projectId}/members/${userId}`, { method: "DELETE" }),
  changeRole: (userId: string, role: string) =>
    request<unknown>(`/team/users/${userId}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
};
