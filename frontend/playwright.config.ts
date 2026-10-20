import { defineConfig } from "@playwright/test";

// Local runs use installed Google Chrome against a server on :8765;
// in Docker, BASE_URL points at the app service and PW_CHANNEL=chromium uses the bundled browser.
const channel = process.env.PW_CHANNEL ?? "chrome";

export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:8765",
    channel: channel === "chromium" ? undefined : channel,
    headless: true,
  },
  workers: 1,
  reporter: "list",
});
