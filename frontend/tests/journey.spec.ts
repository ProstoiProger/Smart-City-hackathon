import { test, expect, type Page } from "@playwright/test";

// QA screenshots for the delivery report: only on request (QA_SCREENSHOTS=1), so a normal
// test run does not rewrite the tracked qa/*.png files.
async function qaShot(page: Page, name: string) {
  if (process.env.QA_SCREENSHOTS === "1") await page.screenshot({ path: `../qa/${name}.png` });
}

// Chat checks must not depend on a Gemini key, quota or network: force the local path.
async function offlineChat(page: Page) {
  await page.route("**/api/chat", (route) =>
    route.continue({ postData: JSON.stringify({ ...route.request().postDataJSON(), provider: "offline" }) }),
  );
}

/** "Только туда": answers are 1–3 options instead of a round-trip route. */
async function oneWay(page: Page) {
  await page.addInitScript(() => localStorage.setItem("walkMode", "oneway"));
}

const tab = (page: Page, name: string) => page.locator(".tabbar").getByRole("button", { name });
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

async function setWhen(page: Page, value: string) {
  await page.locator(".more-settings summary").click();
  await page.locator('input[type="datetime-local"]').fill(value);
}

async function askChat(page: Page, text: string) {
  const before = await page.locator(".bubble.assistant").count();
  await page.getByLabel("Куда хотите сходить?").fill(text);
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page.locator(".bubble.assistant")).toHaveCount(before + 1, { timeout: 30000 });
  return page.locator(".bubble.assistant").last();
}

test("explicit subvenue tickets and afisha ticket links", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await setWhen(page, "2026-10-20T12:00");
  await page.locator(".origin-card").click();
  await page.getByRole("button", { name: "Ailand" }).click();
  await tab(page, "Места").click();
  await page.locator("#search").fill("Океанариум Думан");
  await page.locator("#search").press("Enter");
  await page.locator(".place-row").filter({ hasText: "Океанариум Ailand (Думан)" }).first().click();
  const detail = page.locator(".place-detail");
  await expect(detail).toContainText(/5[ \u00a0]600/);
  await detail.getByText("Опубликованные цены и тарифы", { exact: true }).click();
  await expect(detail).toContainText(/4[ \u00a0]400/);
  await qaShot(page, "price_policy");
  await tab(page, "Город").click();
  await page.locator(".tile").filter({ hasText: "Афиша" }).click();
  await expect(page.getByRole("region", { name: "Афиша Астаны" })).toBeVisible();
  await expect(page.locator(".event-row").first()).toBeVisible();
  // No publisher re-check button: listings link to their Ticketon page (or the publisher).
  await expect(page.locator(".event-row").getByRole("button")).toHaveCount(0);
  await expect(page.locator(".event-row").getByRole("link", { name: "Билеты на Ticketon" }).first()).toHaveAttribute(
    "href",
    /ticketon\.kz/,
  );
  await page.getByRole("button", { name: "Закрыть афишу", exact: true }).click();
  await expect(page.locator(".tile").first()).toBeVisible();
  expect(await noSideScroll(page)).toBe(true);
});

test("desktop: 3D map, nearby places, route to a place and the chat", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.getByRole("button", { name: "Плоская карта" })).toHaveAttribute("aria-pressed", "true");
  await page.waitForTimeout(2500);
  await qaShot(page, "desktop");
  await tab(page, "Места").click();
  await expect(page.locator(".place-row").first()).toBeVisible();
  await expect(page.locator(".map-pin").first()).toBeVisible();
  // Every place carries a Noto emoji of its kind, in the list and on the map.
  await expect(page.locator(".place-row .emoji-tile .emo-still").first()).toHaveAttribute("src", /\/emoji\/[0-9a-f_]+\.svg$/);
  await expect(page.locator(".map-pin .emo-still").first()).toHaveAttribute("src", /\/emoji\//);
  await expect
    .poll(() => page.locator(".place-row .emo-still").first().evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth))
    .toBeGreaterThan(0);
  await page.locator(".place-row").first().click();
  await expect(page.locator(".place-detail")).toBeVisible();
  await expect(page.locator(".budget-card .ring")).toBeVisible();
  await page.getByRole("button", { name: "Маршрут сюда", exact: true }).click();
  await expect(page.locator(".timeline .tl-stop").first()).toBeVisible();
  await expect(tab(page, "Маршрут")).toHaveAttribute("aria-current", "page");
  await offlineChat(page);
  await tab(page, "Помощник").click();
  const answer = await askChat(page, "Где погулять за час?");
  await expect(answer.locator(".mini-place, .route-chip").first()).toBeVisible();
  // The 3D toggle flattens the map and back.
  await page.getByRole("button", { name: "Плоская карта" }).click();
  await expect(page.getByRole("button", { name: "Показать здания в 3D" })).toHaveAttribute("aria-pressed", "false");
  expect(errors).toEqual([]);
  expect(await noSideScroll(page)).toBe(true);
});

test("mobile: bottom sheet, nearby, chat and Kazakh navigation", async ({ page }) => {
  await offlineChat(page);
  await oneWay(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  const sheet = await page.locator(".panel").boundingBox();
  expect(sheet!.y).toBeGreaterThan(200);
  await page.waitForTimeout(2500);
  await qaShot(page, "mobile");
  await tab(page, "Места").click();
  await page.locator("#search").fill("кафе");
  await page.locator("#search").press("Enter");
  await expect(page.locator(".place-row").first()).toBeVisible();
  await tab(page, "Помощник").click();
  await askChat(page, "Куда сходить с ребёнком?");
  await page.getByRole("button", { name: "ҚАЗ", exact: true }).click();
  await expect(tab(page, "Көмекші")).toBeVisible();
  // The grip folds the sheet so the map can be used.
  await page.getByRole("button", { name: "Панельді жию" }).click();
  await expect(page.locator(".panel")).toHaveClass(/folded/);
  expect(await noSideScroll(page)).toBe(true);
});

test("theme and language persist and the UI is fully Kazakh", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "ҚАЗ", exact: true }).click();
  await tab(page, "Қала").click();
  await page.getByRole("button", { name: /Қараңғы тақырып/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "kk");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("radio", { name: /Барып-қайту/ })).toBeVisible();
  await tab(page, "Орындар").click();
  await expect(page.locator(".list-head")).toContainText("Табылды");
  await expect(page.locator(".place-row .option-kind").first()).not.toContainText(
    /Достопримечательности|Кафе и рестораны|Парки и природа/,
  );
  expect(await page.evaluate(() => [...document.styleSheets].some((s) => (s.href || "").includes("googleapis")))).toBe(false);
});

test("there and back: a round-trip walk with a return time and a time ring", async ({ page }) => {
  await offlineChat(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await setWhen(page, "2026-10-22T13:00");
  await expect(page.getByRole("radio", { name: /Туда и обратно/ })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("radio", { name: /^90/ }).click();
  await expect(page.locator(".cta")).toContainText("Снова на старте к");
  await page.getByRole("button", { name: /Парк/ }).first().click();
  await page.getByRole("button", { name: /Кофе/ }).first().click();
  await page.locator(".cta").click();
  await expect(page.locator(".timeline")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".screen-title")).toContainText("Маршрут на 90 мин");
  await expect(page.locator(".route-card")).toContainText("Дорога назад");
  await expect(page.locator(".route-card .finish-line")).toContainText(/Снова на старте в \d\d:\d\d/);
  await expect(page.locator(".tl-finish")).toBeVisible();
  await expect(page.locator(".map-pin.numbered").first()).toBeVisible();
  await qaShot(page, "round_trip");
});

test("one way: options for the time, each with its ring", async ({ page }) => {
  await offlineChat(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await setWhen(page, "2026-10-22T13:00");
  await page.getByRole("radio", { name: /Только туда/ }).click();
  await expect(page.locator(".cta")).toContainText("Финиш к");
  await page.getByRole("radio", { name: /^45/ }).click();
  await page.getByRole("button", { name: /Кофе/ }).first().click();
  await page.locator(".cta").click();
  await expect(page.locator(".option-card").first()).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".screen-title")).toContainText("Что успеть за 45 мин");
  const count = await page.locator(".option-card").count();
  expect(count).toBeGreaterThan(0);
  expect(count).toBeLessThanOrEqual(3);
  await expect(page.locator(".option-card .ring").first()).toBeVisible();
  // Hovering a card lights its pin on the map.
  await page.locator(".option-card").first().hover();
  await expect(page.locator(".map-pin.active")).toHaveCount(1);
  await page.locator(".option-card").first().click();
  await expect(page.locator(".place-detail")).toBeVisible();
  await page.getByRole("button", { name: "Назад" }).click();
  await expect(page.locator(".option-card").first()).toBeVisible();
});

test("answers show nearby events and the company budget", async ({ page }) => {
  await offlineChat(page);
  await oneWay(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await setWhen(page, "2026-10-24T15:30");
  await tab(page, "Помощник").click();
  const answer = await askChat(page, "Идём в Столичный цирк");
  await expect(answer.locator(".events-card")).toContainText("События во время прогулки");
  await expect(answer.locator(".events-card")).toContainText("24.10, 16:00");
  await expect(answer.locator(".mini-place small").first()).toContainText(/мин на месте/);
  await tab(page, "Маршрут").click();
  await page.locator(".more-settings summary").click();
  await page.getByLabel("Сколько вас").selectOption("5");
  await tab(page, "Помощник").click();
  const dinner = await askChat(page, "Поужинать возле Байтерека");
  await expect(dinner).toContainText("Подбор для компании из 5");
  await expect(dinner.locator(".group-cost").first()).toContainText(/На 5 чел\. ≈/);
});

test("picking a start on the map keeps the layout", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/");
  const width = () => page.locator(".panel").evaluate((e) => Math.round(e.getBoundingClientRect().width));
  const before = await width();
  await page.locator(".origin-card").click();
  await page.getByRole("button", { name: "Выбрать на карте" }).click();
  await expect(page.locator(".pick-banner")).toBeVisible();
  await page.mouse.click(800, 400);
  await expect(page.locator(".origin-card")).toContainText("Точка на карте");
  expect(await width()).toEqual(before);
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
});

test("a new start brings the map to it, and the map button returns there", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  // Start flag relative to the middle of the map area right of the panel, in pixels.
  const offset = () =>
    page.evaluate(() => {
      const panel = document.querySelector(".panel")!.getBoundingClientRect();
      const f = document.querySelector(".map-flag.start .map-flag-dot")!.getBoundingClientRect();
      const cx = (panel.right + innerWidth) / 2;
      return [Math.round(f.x + f.width / 2 - cx), Math.round(f.y + f.height / 2 - innerHeight / 2)];
    });
  const near = () => expect.poll(async () => Math.max(...(await offset()).map(Math.abs)), { timeout: 5000 }).toBeLessThan(60);
  await page.locator(".origin-card").click();
  await page.getByRole("button", { name: "EXPO 2017" }).click();
  await expect(page.locator(".origin-card")).toContainText("EXPO 2017");
  await near();
  await page.mouse.move(900, 400);
  await page.mouse.down();
  await page.mouse.move(600, 200, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => Math.max(...(await offset()).map(Math.abs))).toBeGreaterThan(100);
  await page.getByRole("button", { name: "Показать мою точку на карте" }).click();
  await near();
});

test("follow-ups refine the last answer: more without repeats, remove the second", async ({ page }) => {
  await offlineChat(page);
  await oneWay(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  // Daytime, so that the cafés are open by schedule whatever the hour of the run.
  await setWhen(page, "2026-10-22T13:00");
  await tab(page, "Помощник").click();
  const names = (bubble: import("@playwright/test").Locator) => bubble.locator(".mini-place strong").allInnerTexts();
  const first = await names(await askChat(page, "Хочу выпить кофе"));
  const last = page.locator(".bubble.assistant").last();
  await expect(last.locator(".considered, .trace, .source-tag")).toHaveCount(0);
  const before = await page.locator(".bubble.assistant").count();
  await last.locator(".quick-replies").getByRole("button", { name: "Ещё варианты" }).click();
  await expect(page.locator(".bubble.assistant")).toHaveCount(before + 1, { timeout: 30000 });
  await expect(page.locator(".bubble.user").last()).toContainText("Ещё варианты");
  const more = await names(page.locator(".bubble.assistant").last());
  expect(first.length).toBeGreaterThan(1);
  expect(more.length).toBeGreaterThan(0);
  expect(more.filter((name) => first.includes(name))).toEqual([]);
  const trimmed = await names(await askChat(page, "Убери второе"));
  expect(trimmed).toEqual(more.filter((_, i) => i !== 1));
});

test("walk buttons re-plan the route and talk in the chat", async ({ page }) => {
  await offlineChat(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await setWhen(page, "2026-10-22T13:00");
  await page.getByLabel("Что хочется").fill("Погулять 2 часа: парк, кофе и музей");
  await page.locator(".cta").click();
  await expect(page.locator(".trip-panel")).toBeVisible({ timeout: 30000 });
  const stopName = () => page.locator(".tl-stop strong").first().innerText();
  const first = (await stopName()).trim();
  await page.getByRole("button", { name: "Здесь закрыто" }).click();
  await expect(page.locator(".trip-history li.closed")).toContainText(first.split(",")[0]);
  await expect.poll(async () => (await stopName()).trim()).not.toBe(first);
  await page.getByRole("button", { name: "Посетили, дальше" }).click();
  await expect(page.locator(".trip-history li.visited")).toHaveCount(1);
  await tab(page, "Помощник").click();
  await expect(page.locator(".bubble.user").filter({ hasText: `«${first.split(",")[0]}» закрыто` })).toBeVisible();
  await expect(page.locator(".bubble.user").last()).toContainText("Посетили, дальше");
});
