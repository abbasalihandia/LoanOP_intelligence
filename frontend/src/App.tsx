import { api } from "./api/client";
import { AnalystProvider, useAnalyst } from "./lib/analyst";
import { useLoad, useRoute } from "./lib/hooks";
import { ExceptionDetailPage } from "./pages/ExceptionDetailPage";
import { ExceptionListPage } from "./pages/ExceptionListPage";

export default function App() {
  return (
    <AnalystProvider>
      <Shell />
    </AnalystProvider>
  );
}

function Shell() {
  const route = useRoute();
  return (
    <div className="page">
      <header className="topbar">
        <a href="#/" className="brand">
          <span className="brand-mark" aria-hidden="true">LO</span>
          <span className="brand-name">LoanOps Intelligence</span>
          <span className="brand-sub">Operations Workbench</span>
        </a>
        <div className="topbar-right">
          <AnalystField />
          <BackendIndicator />
        </div>
      </header>
      <main className="content">
        {route.name === "detail"
          ? <ExceptionDetailPage key={route.exceptionId} exceptionId={route.exceptionId} tab={route.tab} />
          : <ExceptionListPage />}
      </main>
    </div>
  );
}

function AnalystField() {
  const { analystId, setAnalystId } = useAnalyst();
  return (
    <label className="analyst-field" title="POC: no authentication. Recorded on every action you take.">
      <span>Analyst ID</span>
      <input value={analystId} placeholder="analyst.yourname" onChange={(e) => setAnalystId(e.target.value)} />
    </label>
  );
}

function BackendIndicator() {
  const health = useLoad(() => api.health(), []);
  const state = health.loading ? "pending" : health.data ? "ok" : "error";
  const label = state === "ok" ? `Backend ${health.data?.version}` : state === "pending" ? "Checking backend" : "Backend unreachable";
  return (
    <span className={`backend backend-${state}`} title={health.error?.message ?? label}>
      <span className="dot" aria-hidden="true" /> {label}
    </span>
  );
}
