import { createRoot } from "react-dom/client";
import App from "./App";
import { PrefsProvider } from "./lib/prefs";
import "./tokens.css";
import "./legacy.css";
import "./ui.css";

createRoot(document.getElementById("root")!).render(
  <PrefsProvider>
    <App />
  </PrefsProvider>,
);
