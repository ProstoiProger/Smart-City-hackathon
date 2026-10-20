import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  // API_PROXY lets the dev server run in Docker next to the app service.
  server: { proxy: { "/api": process.env.API_PROXY ?? "http://127.0.0.1:8000" } },
  // The icon sprite is referenced as `${url}#id`; a data: URL would break <use>.
  build: { assetsInlineLimit: (file) => (file.endsWith(".svg") ? false : undefined) },
});
