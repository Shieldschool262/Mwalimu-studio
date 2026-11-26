import { chromium } from "playwright";
const B = "http://localhost:5200";
const PLAN = "d48698d7";
let pass = 0, fail = 0;
const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log(`${c ? "PASS" : "FAIL"}: ${n}${d ? " " + d : ""}`); };
const b = await chromium.launch({ headless: true });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs = [];
p.on("pageerror", (e) => errs.push(e.message));
p.on("console", (m) => { if (m.type() === "error" && !m.text().includes("validateDOMNesting")) errs.push(m.text()); });
try {
  await p.goto(`${B}/#/plan`, { waitUntil: "domcontentloaded" });
  await p.getByTestId("scheme-list").waitFor({ timeout: 20000 }).catch(() => {});
  const schemeBtn = p.locator(`[data-testid^="scheme-open-"]`).first();
  const all = await p.locator('[data-testid^="scheme-open-"]').evaluateAll(els => els.map(e => e.getAttribute("data-testid")));
  const match = all.find(x => x.includes(PLAN)) || all[0];
  await p.getByTestId(match).click();
  await p.getByTestId("scheme-table").waitFor({ timeout: 20000 });
  await p.waitForTimeout(800);

  const expected = ["Week", "Lesson", "Strand / Sub-Strand", "Specific Learning Outcomes",
    "Learning Experiences", "Key Inquiry Questions", "Learning Resources", "Assessment",
    "Reflection (Teacher to fill after teaching)"];
  const heads = await p.locator('[data-testid="scheme-table"] thead th').allInnerTexts();
  ok("9 scheme headers exact", heads.length === 9 && expected.every((e, i) => heads[i].trim() === e), heads.join(" | "));
  const pos = await p.locator('[data-testid="scheme-table"] thead th').first().evaluate(e => getComputedStyle(e).position);
  ok("scheme header sticky", pos === "sticky", pos);
  const bg = await p.locator('[data-testid="scheme-table"] thead th').first().evaluate(e => getComputedStyle(e).backgroundColor);
  ok("header dark blue", bg === "rgb(31, 78, 121)", bg);

  const bodyText = await p.locator('[data-testid="scheme-table"] tbody').innerText();
  ok("no cross-reference KIQs in web", !/see week|see above|— do —/i.test(bodyText));
  const full = "How can we group objects? How can we arrange objects?";
  const occurrences = bodyText.split(full).length - 1;
  ok("full KIQ repeated", occurrences >= 2, `occurrences=${occurrences}`);

  const rows = p.locator('[data-testid="scheme-table"] tbody tr');
  if (await rows.count() > 30) {
    await rows.nth(30).scrollIntoViewIfNeeded();
    await p.waitForTimeout(300);
    const box = await p.locator('[data-testid="scheme-table"] thead th').first().boundingBox();
    ok("header visible after scrolling to row 30", !!box && box.y >= 0 && box.y < 200, JSON.stringify(box));
  }

  await p.getByTestId("nav-lesson-plans").click();
  await p.waitForTimeout(1000);
  const lessonBtn = p.locator('[data-testid^="lesson-open-"]').first();
  await lessonBtn.waitFor({ timeout: 15000 });
  await lessonBtn.click();
  await p.getByTestId("lesson-admin-grid").waitFor({ timeout: 15000 });
  const tag = await p.getByTestId("lesson-admin-grid").evaluate(e => e.tagName);
  ok("admin block is a table", tag === "TABLE", tag);
  const adminText = await p.getByTestId("lesson-admin-grid").innerText();
  for (const label of ["School", "Learning Area", "Grade", "Term", "Year", "Week", "Lesson", "Date", "Time", "Strand", "Sub-Strand", "Focus", "Teacher", "TSC No."]) {
    ok(`admin label ${label}`, adminText.includes(label));
  }
  ok("empty date shows blank line", adminText.includes("________"));
  const stages = await p.locator("h4").allInnerTexts();
  const stageText = stages.join(" | ");
  ok("stage headings unnumbered", !/\b[1-9]\.\s*(Introduction|Development|Conclusion)/.test(stageText), stageText.slice(0, 200));
  ok("introduction heading present", stages.some(x => /^Introduction \(\d+ min\)$/.test(x.trim())), stageText);
  ok("no runtime errors", errs.length === 0, errs.slice(0, 2).join(" | "));
  await p.screenshot({ path: "C:/tmp/fmt-ui.png", fullPage: true });
} catch (e) { console.error("SCRIPT ERROR:", e.message); fail++; }
await b.close();
console.log(`\n${pass}/${pass + fail} format UI checks passed`);
if (fail) process.exitCode = 1;
