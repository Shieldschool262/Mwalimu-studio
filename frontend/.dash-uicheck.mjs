import { chromium } from "playwright";

const BASE = "http://localhost:5199";
const results = [];
function ok(name, cond, detail = "") {
  results.push({ name, pass: !!cond, detail });
  console.log(`${cond ? "PASS" : "FAIL"}: ${name}${detail ? " " + detail : ""}`);
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error" && !m.text().includes("validateDOMNesting")) errors.push(m.text()); });

try {
  await page.goto(`${BASE}/#/dashboard`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("dash-root").waitFor({ timeout: 20000 });
  await page.waitForTimeout(1500);
  ok("Dashboard route renders", await page.getByTestId("dash-root").count() === 1);
  ok("Main nav shows dashboard", await page.getByTestId("nav-dashboard").count() === 1);

  for (const id of ["dash-tab-this-term", "dash-tab-all-terms", "dash-tab-by-subject", "dash-tab-gaps-only"]) {
    ok(`${id} present`, await page.getByTestId(id).count() === 1);
  }
  for (const id of ["dash-filter-term", "dash-filter-year", "dash-filter-grade", "dash-filter-subject", "dash-filter-week"]) {
    ok(`${id} present`, await page.getByTestId(id).count() === 1);
  }
  for (const id of ["dash-stat-planned", "dash-stat-taught", "dash-stat-partially",
                    "dash-stat-not-taught", "dash-stat-carry-over", "dash-stat-coverage"]) {
    ok(`${id} present`, await page.getByTestId(id).count() === 1);
  }
  const planned = await page.getByTestId("dash-stat-planned").innerText();
  const coverage = await page.getByTestId("dash-stat-coverage").innerText();
  ok("Header stats have numbers", /\d/.test(planned) && /%/.test(coverage), `planned=${planned} coverage=${coverage}`);

  ok("Subject table present", await page.getByTestId("dash-subject-table").count() === 1);
  const subjectRows = await page.locator('[data-testid^="dash-subject-row-"]').count();
  ok("Subject rows rendered", subjectRows > 0, `rows=${subjectRows}`);
  const firstId = await page.locator('[data-testid^="dash-subject-row-"]').first()
    .getAttribute("data-testid").then((x) => x.replace("dash-subject-row-", ""));
  await page.getByTestId(`dash-subject-row-${firstId}`).click();
  ok("Row click expands week detail", await page.getByTestId(`dash-week-detail-${firstId}`).count() === 1);
  ok("Subject actions present", await page.getByTestId(`dash-view-scheme-${firstId}`).count() === 1
      && await page.getByTestId(`dash-view-row-${firstId}`).count() === 1
      && await page.getByTestId(`dash-export-${firstId}`).count() === 1);

  ok("Week chart present", await page.getByTestId("dash-week-chart").count() === 1);
  const bars = await page.locator('[data-testid^="dash-week-bar-"]').count();
  ok("Week bars rendered", bars > 0, `bars=${bars}`);

  ok("Gaps section present", await page.getByTestId("dash-gaps-section").count() === 1);
  const gapChecks = await page.locator('[data-testid^="dash-gap-check-"]').count();
  ok("Gap rows or empty state", gapChecks > 0 || await page.getByTestId("dash-empty-gaps").count() > 0,
     `gaps=${gapChecks}`);

  if (gapChecks > 0) {
    const gid = await page.locator('[data-testid^="dash-gap-check-"]').first()
      .getAttribute("data-testid").then((x) => x.replace("dash-gap-check-", ""));
    await page.getByTestId(`dash-gap-taught-${gid}`).click();
    ok("Mark-taught modal opens", await page.getByTestId("dash-action-modal").count() === 1);
    await page.getByTestId("dash-modal-work").fill("");
    await page.getByTestId("dash-modal-submit").click();
    await page.waitForTimeout(400);
    const bodyText = await page.locator("body").innerText();
    ok("Empty Work Done blocked", bodyText.includes("Work Done required"), bodyText.slice(-160));
    await page.getByTestId("dash-modal-cancel").click();

    await page.getByTestId(`dash-gap-skip-${gid}`).click();
    await page.getByTestId("dash-modal-reason").fill("");
    await page.getByTestId("dash-modal-submit").click();
    await page.waitForTimeout(400);
    ok("Empty Skip reason blocked", (await page.locator("body").innerText()).includes("Reason required"));
    await page.getByTestId("dash-modal-cancel").click();
  }

  ok("Next-week planner present", await page.getByTestId("dash-next-week").count() === 1);
  ok("PDF export button present", await page.getByTestId("dash-export-pdf").count() === 1);

  // Tabs switch sections.
  await page.getByTestId("dash-tab-by-subject").click();
  await page.waitForTimeout(300);
  ok("By Subject tab hides gaps", await page.getByTestId("dash-gaps-section").count() === 0);
  await page.getByTestId("dash-tab-gaps-only").click();
  await page.waitForTimeout(300);
  ok("Gaps Only tab hides subject table", await page.getByTestId("dash-subject-table").count() === 0);
  await page.getByTestId("dash-tab-this-term").click();

  // URL persistence.
  await page.getByTestId("dash-filter-week").selectOption({ index: 1 });
  await page.waitForTimeout(600);
  ok("Filters persist in URL", page.url().includes("week="), page.url().split("#")[1] || "");

  // Library link.
  await page.goto(`${BASE}/#/library`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("library-dashboard-link").waitFor({ timeout: 12000 });
  ok("Library header has dashboard link", await page.getByTestId("library-dashboard-link").count() === 1);
  await page.getByTestId("library-dashboard-link").click();
  await page.getByTestId("dash-root").waitFor({ timeout: 12000 });
  ok("Library link navigates to dashboard", await page.getByTestId("dash-root").count() === 1);

  await page.screenshot({ path: "C:/tmp/dash-ui.png", fullPage: true });
  ok("No page/console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
} catch (e) {
  console.error("SCRIPT ERROR:", e.message);
  ok("Script completed without exception", false, e.message);
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} UI checks passed`);
if (failed.length) process.exitCode = 1;
