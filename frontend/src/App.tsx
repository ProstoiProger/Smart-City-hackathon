import { useState } from "react";
import { AfishaPanel, Notification } from "./components/Overlays";
import { Icon } from "./lib/Icon";
import { Assistant } from "./components/Assistant";
import { Explorer } from "./components/Explorer";
import { MapPanel } from "./components/MapPanel";
import { TopBar } from "./components/TopBar";
import { BackendStatus } from "./lib/BackendStatus";
import { ErrorBoundary } from "./lib/ErrorBoundary";
import { useT } from "./lib/i18n";
import { useWalk, type Panel } from "./useWalk";

const PANELS: Panel[] = ["places", "map", "chat"];

/** Desktop: the assistant column can be hidden to give the map its space; remembered per browser. */
function useChatHidden(): [boolean, (v: boolean) => void] {
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem("chatHidden") === "1";
    } catch {
      return false;
    }
  });
  const set = (v: boolean) => {
    setHidden(v);
    try {
      localStorage.setItem("chatHidden", v ? "1" : "0");
    } catch {
      // Kept for this session only.
    }
  };
  return [hidden, set];
}

export default function App() {
  const t = useT();
  const walk = useWalk();
  const [chatHidden, setChatHidden] = useChatHidden();
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
      <main className={"workspace active-" + walk.panel + (chatHidden ? " chat-hidden" : "")}>
        <ErrorBoundary>
          <Explorer walk={walk} />
        </ErrorBoundary>
        <ErrorBoundary>
          <MapPanel walk={walk} />
        </ErrorBoundary>
        <ErrorBoundary>
          <Assistant walk={walk} onHide={() => setChatHidden(true)} />
        </ErrorBoundary>
      </main>
      {chatHidden && (
        <button className="chat-reopen icon-button" onClick={() => setChatHidden(false)}>
          <Icon name="sparkles" />
          {t("chat.show")}
        </button>
      )}
      <Notification walk={walk} />
      <AfishaPanel walk={walk} />
    </>
  );
}
