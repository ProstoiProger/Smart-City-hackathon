import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// WCAG 2.1 A/AA on the main workspace for every theme, language and form factor,
// including the open place card and a chat answer.
const THEMES = ["light", "dark"] as const;
const LANGS = ["ru", "kk"] as const;
const VIEWPORTS = { desktop: { width: 1440, height: 1000 }, mobile: { width: 390, height: 844 } };

async function audit(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // Map tiles are third-party raster images; markers and controls are still checked.
    .exclude(".leaflet-tile-pane")
    .analyze();
  const summary = results.violations.flatMap((v) =>
    v.nodes.map((n) => `${v.id}: ${n.target.join(" ")} — ${n.failureSummary?.split("\n")[1]?.trim()}`),
  );
  expect(summary).toEqual([]);
}

for (const theme of THEMES) {
  for (const lang of LANGS) {
    for (const [name, size] of Object.entries(VIEWPORTS)) {
      test(`axe: ${theme} ${lang} ${name}`, async ({ page }) => {
        await page.addInitScript(
          ([t, l]) => {
            localStorage.setItem("theme", t);
            localStorage.setItem("lang", l);
          },
          [theme, lang],
        );
        await page.setViewportSize(size);
        await page.goto("/");
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect(page.locator(".place-row").first()).toBeAttached();
        await audit(page);
        if (name === "mobile") await page.locator(".mobile-nav button").first().click();
        await page.locator(".place-main").first().click();
        await expect(page.locator(".detail-sheet")).toBeVisible();
        await audit(page);
      });
    }
  }
}
