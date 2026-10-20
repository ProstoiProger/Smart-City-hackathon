import { createRoot } from "react-dom/client";
import App from "./App";
import { PrefsProvider } from "./lib/prefs";
import "./style.css";

createRoot(document.getElementById("root")!).render(
  <PrefsProvider>
    <App />
  </PrefsProvider>,
);
