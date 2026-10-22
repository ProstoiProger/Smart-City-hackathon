import { createRoot } from "react-dom/client";
import App from "./App";
import { PrefsProvider } from "./lib/prefs";
import "./tokens.css";
import "./legacy.css";
import "./ui.css";
import "./low-vision.css";

createRoot(document.getElementById("root")!).render(
  <PrefsProvider>
    <App />
  </PrefsProvider>,
);

// Installable app: the service worker runs in production builds on a secure origin
// (HTTPS or localhost); during development Vite serves changing files, so it stays off.
if (import.meta.env.PROD && "serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Without it the app still works, only not offline or as an installed app.
    });
  });
}
