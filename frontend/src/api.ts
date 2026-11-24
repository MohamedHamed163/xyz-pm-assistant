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
  organization: string | null;
  projects: { id: string; name: string }[];
  company_wide: boolean;
  client_view: boolean;
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
  if (init.body) headers.set("Content-Type", "application/json");
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
};
