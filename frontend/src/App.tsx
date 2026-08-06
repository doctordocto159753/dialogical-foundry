import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { IntakeView } from "./IntakeView";
import { RunView } from "./RunView";
import { SettingsView } from "./SettingsView";

type View = "intake" | "run" | "settings";

const VALID_VIEWS = new Set<View>(["intake", "run", "settings"]);
const RUN_STORAGE_KEY = "dialogical-foundry.current-run";

function initialView(): View {
  const hash = window.location.hash.replace("#", "") as View;
  return VALID_VIEWS.has(hash) ? hash : localStorage.getItem(RUN_STORAGE_KEY) ? "run" : "intake";
}

export default function App() {
  const [view, setView] = useState<View>(initialView);
  const [runId, setRunId] = useState(() => localStorage.getItem(RUN_STORAGE_KEY));
  const [connection, setConnection] = useState<"checking" | "local" | "offline">("checking");

  const checkConnection = useCallback(async () => {
    if (!navigator.onLine) {
      setConnection("offline");
      return;
    }
    try {
      await api.health();
      setConnection("local");
    } catch {
      setConnection("offline");
    }
  }, []);

  useEffect(() => {
    void checkConnection();
    const timer = window.setInterval(checkConnection, 20_000);
    window.addEventListener("online", checkConnection);
    window.addEventListener("offline", checkConnection);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", checkConnection);
      window.removeEventListener("offline", checkConnection);
    };
  }, [checkConnection]);

  useEffect(() => {
    const onHash = () => {
      const next = window.location.hash.replace("#", "") as View;
      if (VALID_VIEWS.has(next)) setView(next);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = (next: View) => {
    setView(next);
    window.history.replaceState(null, "", `#${next}`);
  };

  const selectRun = (id: string) => {
    localStorage.setItem(RUN_STORAGE_KEY, id);
    setRunId(id);
    navigate("run");
  };

  const clearRun = () => {
    localStorage.removeItem(RUN_STORAGE_KEY);
    setRunId(null);
    navigate("run");
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" type="button" onClick={() => navigate("intake")} aria-label="Dialogical Foundry home">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span className="brand-type"><strong>Dialogical Foundry</strong><small>planning studio / v1</small></span>
        </button>

        <nav className="primary-nav" aria-label="Primary navigation">
          {(["intake", "run", "settings"] as View[]).map((item) => (
            <button
              key={item}
              type="button"
              className={view === item ? "active" : ""}
              aria-current={view === item ? "page" : undefined}
              onClick={() => navigate(item)}
            >
              {item === "run" && runId ? <span className="nav-live-dot" aria-hidden="true" /> : null}
              {item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </nav>

        <div className={`connection-state ${connection}`} role="status" aria-live="polite">
          <span aria-hidden="true" />
          {connection === "local" ? "Local service" : connection === "checking" ? "Checking" : "Service offline"}
        </div>
      </header>

      <main id="main-content">
        {view === "intake" ? <IntakeView onRunCreated={selectRun} /> : null}
        {view === "run" ? <RunView runId={runId} onSelectRun={selectRun} onRunDeleted={clearRun} onNewRun={() => navigate("intake")} /> : null}
        {view === "settings" ? <SettingsView /> : null}
      </main>

      <footer className="app-footer">
        <span className="footer-rule" aria-hidden="true" />
        <p><strong>Boundary of the forge.</strong> v1 produces planning artifacts—PRD, architecture, and work package. It never executes target-product code.</p>
        <span>Local-first · data stays on this machine</span>
      </footer>
    </div>
  );
}
