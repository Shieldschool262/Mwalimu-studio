import { chromium } from "playwright";

const browser = await chromium.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error" && !m.text().includes("favicon.ico")) errors.push(m.text());
});
page.on("pageerror", (e) => errors.push(e.message));

await page.goto("http://127.0.0.1:5199/", { waitUntil: "networkidle" });
await page.getByTestId("nav-record-of-work").click();
await page.getByTestId("row-list").waitFor({ timeout: 15000 });
await page.waitForTimeout(500);

const listReport = {
  navLabel: (await page.getByTestId("nav-record-of-work").innerText()).trim(),
  leftNavRow: await page.getByTestId("left-nav-record-of-work").count(),
  schemeCards: await page.locator('[data-testid^="row-scheme-"]').count(),
  generateButtons: await page.locator('[data-testid^="row-generate-"]').count(),
  createdBadges: await page.locator('[data-testid^="row-created-"]').count(),
};
await page.screenshot({ path: ".row-list.png", fullPage: true });

// Open the scheme that already has generated rows in the isolated DB.
const PID = "9c0294d5-f7e1-467d-8458-cbe32b6cd2b7";
await page.getByTestId(`row-view-${PID}`).click();
await page.getByTestId("row-editor").waitFor({ timeout: 15000 });
await page.waitForTimeout(600);

const editorReport = {
  title: (await page.locator('[data-testid="row-editor"] h2').first().innerText()).trim(),
  coverageText: (await page.getByTestId("row-coverage").innerText()).replace(/\s+/g, " ").slice(0, 220),
  tableRows: await page.locator('[data-testid^="row-line-"]').count(),
  statusSelects: await page.locator('[data-testid^="row-status-"]').count(),
  workAreas: await page.locator('[data-testid^="row-work-"]').count(),
  reflectionAreas: await page.locator('[data-testid^="row-reflection-"]').count(),
  aiButtons: await page.locator('[data-testid^="row-ai-"]').count(),
  resetButtons: await page.locator('[data-testid^="row-reset-"]').count(),
  firstWorkValue: await page.locator('[data-testid^="row-work-"]').first().inputValue(),
  plannedItalicCount: await page.locator('textarea.italic').count(),
  gapsButton: await page.getByTestId("row-view-gaps").innerText(),
  exportHref: await page.getByTestId("row-export-pdf").getAttribute("href"),
};

// Open gaps drawer + version history drawer.
await page.getByTestId("row-view-gaps").click();
await page.getByTestId("row-gaps-drawer").waitFor();
const gapsCount = await page.locator('[data-testid^="row-gap-"]').count();
await page.getByTestId("row-gaps-drawer").getByText("Close").click();
await page.getByTestId("row-history").click();
await page.getByTestId("row-version-history").waitFor();
await page.waitForTimeout(300);
const versionCards = await page.locator('[data-testid^="row-version-"]').count();
await page.getByTestId("row-version-history").getByText("Close").click();

await page.screenshot({ path: ".row-editor.png", fullPage: true });
console.log(JSON.stringify({ listReport, editorReport, gapsCount, versionCards, consoleErrors: errors }, null, 2));
await browser.close();
