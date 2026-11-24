import { useCallback, useEffect, useState } from "react";
import { api, hasToken, setToken, setUnauthorizedHandler, type Me } from "./api";
import Chat from "./Chat";
import Documents from "./Documents";
import Login from "./Login";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [booting, setBooting] = useState(hasToken());
  const [view, setView] = useState<"chat" | "documents">("chat");

  const logout = useCallback(() => {
    setToken(null);
    setMe(null);
    setView("chat");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null));
    if (!hasToken()) return;
    api
      .me()
      .then(setMe)
      .catch(() => setToken(null))
      .finally(() => setBooting(false));
  }, []);

  if (booting) return <div className="boot">Loading…</div>;
  if (!me) return <Login onLoggedIn={setMe} />;
  if (view === "documents" && me.can_upload) return <Documents me={me} onBack={() => setView("chat")} />;
  return <Chat key={me.id} me={me} onLogout={logout} onOpenDocuments={() => setView("documents")} />;
}
