import { chromium } from "playwright";
const B = "http://localhost:5199";
const b = await chromium.launch({ headless: true });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs = [];
p.on("pageerror", e => errs.push(e.message));
let pass = 0, fail = 0;
const ok = (n, c, d="") => { c ? pass++ : fail++; console.log(`${c?"PASS":"FAIL"}: ${n}${d?" "+d:""}`); };
try {
  await p.goto(`${B}/#/dashboard`, { waitUntil: "domcontentloaded" });
  await p.getByTestId("dash-root").waitFor({ timeout: 20000 });
  await p.waitForTimeout(1200);
  const gid = await p.locator('[data-testid^="dash-gap-check-"]').first().getAttribute("data-testid").then(x => x.replace("dash-gap-check-",""));
  ok("gap row rendered", !!gid, gid);
  await p.getByTestId(`dash-gap-taught-${gid}`).click();
  ok("taught modal", await p.getByTestId("dash-action-modal").count() === 1);
  await p.getByTestId("dash-modal-submit").click();
  await p.waitForTimeout(400);
  ok("workDone required", (await p.locator("body").innerText()).includes("Work Done required"));
  await p.getByTestId("dash-modal-work").fill("Taught sorting with counters.");
  await p.getByTestId("dash-modal-submit").click();
  await p.waitForTimeout(1500);
  ok("gap removed after mark taught", await p.getByTestId(`dash-gap-${gid}`).count() === 0);
  ok("coverage updated", (await p.getByTestId("dash-stat-coverage").innerText()).includes("100%"));

  // Seed another gap via API then test skip + carry-over via UI.
  await p.request.post(`${B}/api/row/${gid}/edit`, { data: { status: "Not Taught - Carry Over", reflection: "Sports Day" } });
  await p.reload({ waitUntil: "domcontentloaded" });
  await p.getByTestId("dash-root").waitFor({ timeout: 15000 });
  await p.waitForTimeout(1200);
  const gid2 = await p.locator('[data-testid^="dash-gap-check-"]').first().getAttribute("data-testid").then(x => x.replace("dash-gap-check-",""));
  await p.getByTestId(`dash-gap-skip-${gid2}`).click();
  await p.getByTestId("dash-modal-submit").click();
  await p.waitForTimeout(400);
  ok("reason required", (await p.locator("body").innerText()).includes("Reason required"));
  await p.getByTestId("dash-modal-reason").fill("Sports Day");
  await p.getByTestId("dash-modal-submit").click();
  await p.waitForTimeout(1500);
  const stillGap = await p.getByTestId(`dash-gap-${gid2}`).count();
  ok("skipped gap still visible", stillGap === 1);
  ok("skipped label shown", (await p.getByTestId(`dash-gap-${gid2}`).innerText()).includes("Skipped"));

  await p.getByTestId(`dash-gap-carry-${gid2}`).click();
  ok("carry modal", await p.getByTestId("dash-action-modal").count() === 1);
  const weeks = await p.getByTestId("dash-modal-week").locator("option").allTextContents();
  ok("future weeks offered", weeks.length > 0, weeks.join(","));
  await p.getByTestId("dash-modal-lesson").fill("3");
  await p.getByTestId("dash-modal-submit").click();
  await p.waitForTimeout(1500);
  await p.waitForTimeout(800);
  const gapText = await p.getByTestId(`dash-gap-${gid2}`).innerText().catch(() => "");
  ok("carry-over target shown", !/W\d+ L\d+[\s\S]*—/.test(gapText) && gapText.length > 0, gapText.replace(/\n/g, " | ").slice(0, 160));
  ok("no runtime errors", errs.length === 0, errs.slice(0,2).join(" | "));
} catch (e) { console.error("SCRIPT ERROR:", e.message); fail++; }
await b.close();
console.log(`\n${pass}/${pass+fail} gap-action checks passed`);
if (fail) process.exitCode = 1;
