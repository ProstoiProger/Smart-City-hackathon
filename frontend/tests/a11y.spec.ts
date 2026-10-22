import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// WCAG 2.1 A/AA on the main screens for every theme, language and form factor:
// the walk planner, the nearby list and an open place.
const THEMES = ["light", "dark"] as const;
const LANGS = ["ru", "kk", "en"] as const;
const VIEWPORTS = { desktop: { width: 1440, height: 1000 }, mobile: { width: 390, height: 844 } };

async function audit(page: import("@playwright/test").Page) {
  // Entrance animations finish first: half-faded text would read as low contrast.
  await page.waitForTimeout(700);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // The map canvas and its third-party attribution are not our content; pins and controls are checked.
    .exclude(".maplibregl-canvas-container")
    .exclude(".maplibregl-ctrl-attrib")
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
            localStorage.setItem("uiTheme", t);
            localStorage.setItem("lang", l);
          },
          [theme, lang],
        );
        await page.setViewportSize(size);
        await page.goto("/");
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect(page.locator(".cta")).toBeVisible();
        await audit(page);
        await page.locator(".tabbar button").nth(1).click();
        await expect(page.locator(".place-row").first()).toBeVisible();
        await audit(page);
        await page.locator(".place-row").first().click();
        await expect(page.locator(".place-detail")).toBeVisible();
        await audit(page);
      });
    }
  }
}

// The low-vision version in both schemes, desktop and phone: contrast and labels must hold too.
for (const scheme of ["dark", "light"] as const) {
  for (const [name, size] of Object.entries(VIEWPORTS)) {
    test(`axe: low-vision ${scheme} ${name}`, async ({ page }) => {
      await page.addInitScript((s) => {
        localStorage.setItem("lowVision", JSON.stringify({ on: true, size: 2, scheme: s, images: true, spacing: false }));
      }, scheme);
      await page.setViewportSize(size);
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("data-lv", "on");
      await expect(page.locator(".cta")).toBeVisible();
      await audit(page);
      await page.locator(".tabbar button").nth(1).click();
      await expect(page.locator(".place-row").first()).toBeVisible();
      await page.locator(".place-row").first().click();
      await expect(page.locator(".place-detail")).toBeVisible();
      await audit(page);
    });
  }
}
