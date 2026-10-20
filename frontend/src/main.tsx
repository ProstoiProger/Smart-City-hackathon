import { createRoot } from "react-dom/client";
import App from "./App";
import { PrefsProvider } from "./lib/prefs";
import "./style.css";
import "./map-app.css";

createRoot(document.getElementById("root")!).render(
  <PrefsProvider>
    <App />
  </PrefsProvider>,
);
