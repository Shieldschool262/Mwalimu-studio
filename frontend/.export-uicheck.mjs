import { chromium } from "playwright";

const BASE = "http://localhost:5198";
const PID = "e5b7d0d2-97f5-40a3-948b-01e758a843d8";

const results = [];
function ok(name, cond, detail = "") {
  results.push({ name, pass: !!cond, detail });
  console.log(`${cond ? "PASS" : "FAIL"}: ${name}${detail ? " " + detail : ""}`);
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error" && !m.text().includes("validateDOMNesting")) errors.push(m.text()); });

try {
  // Navigate straight to the scheme view via the hash router.
  await page.goto(BASE + "/#/plan", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);

  // Open a scheme from the list by clicking its open button.
  const schemeBtns = page.locator('[data-testid^="scheme-open-"]');
  const n = await schemeBtns.count();
  ok("scheme list has open buttons", n > 0, `count=${n}`);
  if (n > 0) {
    // Prefer our target scheme if present.
    let target = page.locator(`[data-testid="scheme-open-${PID}"]`);
    if (await target.count() === 0) target = schemeBtns.first();
    await target.click();
    await page.waitForTimeout(1000);
  }

  const termBtn = page.getByTestId("plan-export-term-pack");
  ok("Scheme has Export Term Pack button", await termBtn.count() > 0);
  if (await termBtn.count() > 0) {
    await termBtn.click();
    await page.waitForTimeout(400);
  }

  ok("Export modal opens", await page.getByTestId("export-modal").count() > 0);
  // All default checkboxes ON.
  for (const id of ["export-inc-cover", "export-inc-coverage", "export-inc-scheme",
                    "export-inc-row", "export-inc-citations"]) {
    const cb = page.getByTestId(id).locator("input[type=checkbox]");
    ok(`${id} default checked`, await cb.count() > 0 && await cb.first().isChecked());
  }
  // Plans/notes include ON.
  for (const id of ["export-plans-include", "export-notes-include"]) {
    const cb = page.getByTestId(id);
    ok(`${id} default checked`, await cb.count() > 0 && await cb.isChecked());
  }
  // Opt-in options are OFF by default per spec.
  for (const id of ["export-inc-drafts", "export-inc-answers", "export-inc-versions"]) {
    const cb = page.getByTestId(id).locator("input[type=checkbox]");
    ok(`${id} default OFF`, await cb.count() > 0 && !(await cb.first().isChecked()));
  }
  ok("PDF format selected by default", await page.getByTestId("export-format-pdf").isChecked());
  ok("Selected mode radio present", await page.getByTestId("export-plans-mode-selected").count() > 0);

  // Toggle answers ON, weeks mode for plans.
  const ans = page.getByTestId("export-inc-answers").locator("input");
  await ans.click();
  ok("Answers toggle works (OFF -> ON)", await ans.isChecked());
  await ans.click(); // back OFF

  // Start export.
  await page.getByTestId("export-start").click();
  // Wait for completion (small term packs can finish faster than one poll tick).
  await page.waitForSelector('[data-testid="export-done"]', { timeout: 60000 });
  ok("Progress shown or done shown", await page.getByTestId("export-done").count() > 0);
  ok("Export completes with download", await page.getByTestId("export-download").count() > 0);
  const dl = await page.getByTestId("export-download").getAttribute("href");
  ok("Download href is job file URL", !!dl && dl.includes("/api/export/"), String(dl));
  ok("Download Again button present", await page.getByTestId("export-again").count() > 0);

  // Close modal.
  await page.getByTestId("export-close").click();
  await page.waitForTimeout(200);
  ok("Modal closes", await page.getByTestId("export-modal").count() === 0);

  // Library entry: go to library, check approved card has Export button.
  await page.goto(BASE + "/#/library", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  const cards = page.locator('[data-testid^="doc-card-"]');
  ok("Library has cards", await cards.count() > 0, `count=${await cards.count()}`);
  const libExport = page.getByTestId("card-export-term-pack");
  ok("Library approved cards have Export Term Pack", await libExport.count() > 0, `count=${await libExport.count()}`);

  // ROW entry: go to ROW, open a scheme, check button.
  await page.goto(BASE + "/#/plan", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(800);
  await page.getByTestId("nav-record-of-work").click();
  await page.waitForTimeout(800);
  const rowSchemes = page.locator('[data-testid^="row-view-"]');
  ok("ROW list has schemes", await rowSchemes.count() > 0);
  if (await rowSchemes.count() > 0) {
    await rowSchemes.first().click();
    await page.waitForTimeout(900);
    ok("ROW editor has Export Term Pack button", await page.getByTestId("row-export-term-pack").count() > 0);
  }

  ok("No page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
} catch (e) {
  ok("UI check completed without exception", false, String(e).slice(0, 300));
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.pass);
console.log(`\nRESULTS: ${results.length - failed.length} passed, ${failed.length} failed`);
process.exit(failed.length ? 1 : 0);
