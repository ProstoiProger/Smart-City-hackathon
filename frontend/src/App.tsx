import { AfishaPanel, ComparePanel, Notification } from "./components/Overlays";
import { Assistant } from "./components/Assistant";
import { Explorer } from "./components/Explorer";
import { MapPanel } from "./components/MapPanel";
import { TopBar } from "./components/TopBar";
import { BackendStatus } from "./lib/BackendStatus";
import { ErrorBoundary } from "./lib/ErrorBoundary";
import { useT } from "./lib/i18n";
import { useWalk, type Panel } from "./useWalk";

const PANELS: Panel[] = ["places", "map", "chat"];

export default function App() {
  const t = useT();
  const walk = useWalk();
  return (
    <>
      <BackendStatus />
      <TopBar meta={walk.meta} weather={walk.weather} onAfisha={walk.afishaState.openAfisha} />
      <nav className="mobile-nav" aria-label={t("nav.sections")}>
        {PANELS.map((p) => (
          <button key={p} aria-pressed={walk.panel === p} onClick={() => walk.setPanel(p)}>
            {t("nav." + p)}
          </button>
        ))}
      </nav>
      <main className={"workspace active-" + walk.panel}>
        <ErrorBoundary>
          <Explorer walk={walk} />
        </ErrorBoundary>
        <ErrorBoundary>
          <MapPanel walk={walk} />
        </ErrorBoundary>
        <ErrorBoundary>
          <Assistant walk={walk} />
        </ErrorBoundary>
      </main>
      <Notification walk={walk} />
      <AfishaPanel walk={walk} />
      <ComparePanel walk={walk} />
    </>
  );
}
