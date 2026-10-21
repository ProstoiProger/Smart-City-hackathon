import { test, expect } from "@playwright/test";

// QA screenshots for the delivery report: only on request (QA_SCREENSHOTS=1), so a normal
// test run does not rewrite the tracked qa/*.png files.
async function qaShot(page: import("@playwright/test").Page, name: string) {
  if (process.env.QA_SCREENSHOTS === "1") await page.screenshot({ path: `../qa/${name}.png`, fullPage: true });
}

// Chat checks must not depend on a Gemini key, quota or network: force the local path.
async function offlineChat(page: import("@playwright/test").Page) {
  await page.route("**/api/chat", (route) =>
    route.continue({ postData: JSON.stringify({ ...route.request().postDataJSON(), provider: "offline" }) }),
  );
}

test("explicit subvenue tickets and afisha ticket links", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator(".place-row").first()).toBeVisible();
  await page.getByText("Условия прогулки", { exact: true }).click();
  await page.locator("#when").fill("2026-10-20T12:00");
  await page.locator("#search").fill("Океанариум Думан");
  await page.locator("#origin").selectOption("ailand");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await page
    .locator(".place-row")
    .filter({ hasText: "Океанариум Ailand (Думан)" })
    .locator(".place-main")
    .click();
  await expect(page.locator(".detail-sheet")).toContainText(/5[ \u00a0]600/);
  await page
    .locator(".detail-sheet")
    .getByText("Опубликованные цены и тарифы", { exact: true })
    .click();
  await expect(page.locator(".detail-sheet")).toContainText(/4[ \u00a0]400/);
  await qaShot(page, "price_policy");
  await page.getByRole("button", { name: "Афиша", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Афиша Астаны" }),
  ).toBeVisible();
  await expect(page.locator(".event-row").first()).toBeVisible();
  // No publisher re-check button: listings link to their Ticketon page (or the publisher).
  await expect(page.locator(".event-row").getByRole("button")).toHaveCount(0);
  await expect(
    page.locator(".event-row").getByRole("link", { name: "Билеты на Ticketon" }).first(),
  ).toHaveAttribute("href", /ticketon\.kz/);
  await page
    .getByRole("button", { name: "Закрыть афишу", exact: true })
    .click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("desktop: actual POIs, route to a place, search and model fallback", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator(".place-row").first()).toBeVisible();
  await expect(page.locator(".leaflet-marker-icon").first()).toBeVisible();
  await page.waitForTimeout(2500);
  await qaShot(page, "desktop");
  await page.locator(".place-main").first().click();
  await expect(page.locator(".detail-sheet")).toBeVisible();
  // Comparison was removed: no "В сравнение" buttons anywhere.
  await expect(page.getByRole("button", { name: "В сравнение" })).toHaveCount(0);
  await page
    .locator(".detail-sheet")
    .getByRole("button", { name: "Маршрут сюда", exact: true })
    .click();
  await expect(page.locator(".itinerary li").first()).toBeVisible();
  await expect(
    page.locator(".leaflet-overlay-pane path").first(),
  ).toBeVisible();
  // Model fallback is covered by API tests; here the offline path keeps the UI test independent of keys and network.
  await offlineChat(page);
  await page.getByLabel("Куда хотите сходить?").fill("Где погулять за час?");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page.locator(".message.assistant").last()).toBeVisible();
  await expect(page.locator(".chat-place").first()).toBeVisible();
  expect(errors).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("mobile: map, filters, chat and Kazakh navigation", async ({ page }) => {
  await offlineChat(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".map-panel")).toBeVisible();
  await expect(page.locator(".map-canvas")).toHaveCSS("height", /\d+px/);
  await page.waitForTimeout(2500);
  await qaShot(page, "mobile");
  await page
    .locator(".mobile-nav")
    .getByRole("button", { name: "Места" })
    .click();
  await expect(page.locator("#search")).toBeVisible();
  await page.locator("#search").fill("кафе");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page.locator(".place-row").first()).toBeVisible();
  await page
    .locator(".mobile-nav")
    .getByRole("button", { name: "Помощник" })
    .click();
  await page
    .getByLabel("Куда хотите сходить?")
    .fill("Куда сходить с ребёнком?");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page.locator(".message.assistant")).toBeVisible();
  await page.getByRole("button", { name: "ҚАЗ", exact: true }).click();
  await expect(
    page.locator(".mobile-nav").getByRole("button", { name: "Көмекші" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("theme and language persist and the UI is fully Kazakh", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "ҚАЗ", exact: true }).click();
  await page.getByRole("button", { name: /тақырыпты қосу/ }).click();
  const theme = await page.locator("html").getAttribute("data-theme");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "kk");
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme!);
  await expect(page.getByRole("button", { name: "Іздеу", exact: true })).toBeVisible();
  await expect(page.locator(".results-heading")).toContainText("Табылды");
  await expect(page.locator(".place-kind").first()).not.toContainText(/Достопримечательности|Кафе и рестораны|Парки и природа/);
  expect(await page.evaluate(() => [...document.styleSheets].some((s) => (s.href || "").includes("googleapis")))).toBe(false);
});

test("chat builds a timed mini-route of up to 3 stops and draws it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await offlineChat(page);
  await page.getByLabel("Мини-маршрут из 3 мест").check();
  await page.getByLabel("Куда хотите сходить?").fill("Хочу прогуляться 90 минут возле Байтерека");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  const card = page.locator(".message.assistant .mini-route").last();
  await expect(card).toContainText("Мини-маршрут");
  await expect(page.locator(".route-meta").first()).toContainText(/^1\. через \d+ мин/);
  await expect(page.locator(".itinerary")).toContainText("Мини-маршрут");
  await expect(page.locator(".leaflet-overlay-pane path").first()).toBeVisible();
  await page.locator(".itinerary").getByRole("button", { name: "Закрыть" }).click();
  await card.getByRole("button", { name: "Показать маршрут на карте" }).click();
  await expect(page.locator(".itinerary li").first()).toBeVisible();
});

test("answers show timing, nearby events and the company budget", async ({ page }) => {
  await offlineChat(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByText("Условия прогулки", { exact: true }).click();
  await page.locator("#when").fill("2026-10-24T15:30");
  await page.getByLabel("Куда хотите сходить?").fill("Идём в Столичный цирк");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  const answer = page.locator(".message.assistant").last();
  await expect(answer.locator(".chat-events")).toContainText("События во время прогулки");
  await expect(answer.locator(".chat-events")).toContainText("24.10, 16:00");
  await expect(answer.locator(".route-meta").first()).toContainText(/мин на месте/);

  await page.locator("#group-size").selectOption("5");
  await page.getByLabel("Куда хотите сходить?").fill("Поужинать возле Байтерека");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  const dinner = page.locator(".message.assistant").last();
  await expect(dinner).toContainText("Подбор для компании из 5");
  await expect(dinner.locator(".group-cost").first()).toContainText(/На 5 чел\. ≈/);
});

test("picking a start on the map does not shift the layout", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/");
  await expect(page.locator(".place-row").first()).toBeVisible();
  await page.getByText("Условия прогулки", { exact: true }).click();
  const widths = () =>
    page.locator(".workspace > *").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().width)));
  const before = await widths();
  await page.getByRole("button", { name: "Выбрать на карте" }).click();
  await page.locator(".map-canvas").click({ position: { x: 200, y: 300 } });
  await expect(page.locator("#origin")).toHaveValue("custom");
  expect(await widths()).toEqual(before);
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
  await expect(page.locator(".map-canvas")).toHaveClass(/leaflet-container/);
});

test("a new start brings the map to it, and the map button returns there", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.locator(".place-row").first()).toBeVisible();
  // Start pin tip relative to the map centre, in pixels.
  const offset = () =>
    page.evaluate(() => {
      const m = document.querySelector(".map-canvas")!.getBoundingClientRect();
      const s = document.querySelector(".start-pin")!.getBoundingClientRect();
      return [Math.round(s.x + s.width / 2 - (m.x + m.width / 2)), Math.round(s.bottom - (m.y + m.height / 2))];
    });
  // The flight takes ~0.6 s; poll until the pin settles in the centre.
  const centred = () =>
    expect.poll(async () => Math.max(...(await offset()).map(Math.abs)), { timeout: 4000 }).toBeLessThan(12);
  await page.locator("#origin").selectOption("expo");
  await centred();
  await page.mouse.move(700, 400);
  await page.mouse.down();
  await page.mouse.move(400, 200, { steps: 5 });
  await page.mouse.up();
  expect(Math.max(...(await offset()).map(Math.abs))).toBeGreaterThan(100);
  await page.getByRole("button", { name: "Показать мою точку на карте" }).click();
  await centred();
});

test("follow-ups refine the last answer: more without repeats, remove the second", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await offlineChat(page);
  // Daytime, so that the cafés are open by schedule whatever the hour of the run.
  await page.getByText("Условия прогулки", { exact: true }).click();
  await page.locator("#when").fill("2026-10-22T13:00");
  const ask = async (text: string) => {
    const before = await page.locator(".message.assistant").count();
    await page.getByLabel("Куда хотите сходить?").fill(text);
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator(".message.assistant")).toHaveCount(before + 1);
    return page.locator(".message.assistant").last().locator(".chat-place strong").allInnerTexts();
  };
  const first = await ask("Хочу выпить кофе");
  // The answer carries no service blocks, only the places and one-tap follow-ups.
  const before = await page.locator(".message.assistant").count();
  const last = page.locator(".message.assistant").nth(before - 1);
  await expect(last.locator(".considered, .trace, .source-tag")).toHaveCount(0);
  await last.locator(".quick-replies").getByRole("button", { name: "Ещё варианты" }).click();
  await expect(page.locator(".message.assistant")).toHaveCount(before + 1);
  await expect(page.locator(".message.user").last()).toContainText("Ещё варианты");
  const more = await page.locator(".message.assistant").last().locator(".chat-place strong").allInnerTexts();
  await expect(last.locator(".quick-replies")).toHaveCount(0);
  expect(first.length).toBeGreaterThan(1);
  expect(more.length).toBeGreaterThan(0);
  expect(more.filter((name) => first.includes(name))).toEqual([]);
  const trimmed = await ask("Убери второе");
  expect(trimmed).toEqual(more.filter((_, i) => i !== 1));
});

test("walk buttons on the map talk in the chat", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await offlineChat(page);
  await page.getByText("Условия прогулки", { exact: true }).click();
  await page.locator("#when").fill("2026-10-22T13:00");
  await page.getByLabel("Куда хотите сходить?").fill("Погулять 2 часа: парк, кофе и музей");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  const sheet = page.locator(".itinerary");
  await expect(sheet.getByRole("button", { name: "Здесь закрыто" })).toBeVisible();
  const first = (await sheet.locator("li").first().locator("strong").innerText()).trim();
  await sheet.getByRole("button", { name: "Здесь закрыто" }).click();
  await expect(page.locator(".message.user").last()).toContainText(`«${first}» закрыто`);
  await expect(page.locator(".message.assistant").last()).toContainText("закрыто — убрал из плана");
  // The map follows: the numbered stops are the new route, the closed place is gone.
  const replacement = (await sheet.locator("ol > li").first().locator("strong").innerText()).trim();
  await expect(page.locator(".stop-pin").first().locator("..")).toHaveAttribute("title", `1. ${replacement}`);
  const pinned = await page.locator(".stop-pin").evaluateAll((els) => els.map((e) => e.parentElement!.title));
  expect(pinned.some((title) => title.endsWith(first))).toBe(false);
  await sheet.getByRole("button", { name: "Посетили, дальше" }).click();
  await expect(page.locator(".message.user").last()).toContainText("Посетили, дальше");
  await expect(page.locator(".message.assistant").last()).toContainText(/Дальше|Остановок больше нет|последняя остановка/);
});
