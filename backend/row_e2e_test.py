#!/usr/bin/env python3
"""End-to-end ROW validation via HTTP against port 8767."""
import json, subprocess, sys, os, sqlite3, hashlib

BASE = "http://127.0.0.1:8767"
PLAN_ID = "9c0294d5-f7e1-467d-8458-cbe32b6cd2b7"

def api(method, path, body=None):
    cmd = ["curl", "-s", "-m", "60", "-X", method, f"{BASE}{path}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except:
        return {"_raw": r.stdout[:200]}

passed = failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        print(f"  PASS: {name}"); passed += 1
    else:
        print(f"  FAIL: {name} {detail}"); failed += 1

# Clean slate on the scratch DB (direct SQL since we own it)
conn = sqlite3.connect("C:/tmp/mwalimu_e2e.db")
for t in ["record_of_work_versions", "record_of_work_rows", "record_of_work_docs"]:
    conn.execute(f"DELETE FROM {t}")
conn.commit(); conn.close()

print("=== 1. Generate ROW ===")
res = api("POST", "/api/row", {"planId": PLAN_ID, "addMissingOnly": False})
check("Generation returns doc id", res.get("id") == PLAN_ID)
check("Rows generated", res.get("created", 0) > 0, f"created={res.get('created')}")
row_count = len(res.get("rows", []))
print(f"  (Generated {row_count} rows)")

print("\n=== 2. Get Document / initial field state ===")
doc = api("GET", f"/api/row?planId={PLAN_ID}")
check("Doc has rows", len(doc.get("rows", [])) > 0)
check("Status is Draft", doc.get("status") == "Draft")
r0 = doc["rows"][0]
check("Work Done starts with 'Planned:'", r0["workDone"].startswith("Planned:"), repr(r0["workDone"][:40]))
check("Reflection is empty", r0["reflection"] == "", repr(r0["reflection"]))
check("Status is blank", r0["status"] == "", repr(r0["status"]))
check("teacherEdited False", r0["teacherEdited"] is False)
check("isPlanned True", r0["isPlanned"] is True)
check("origin 'planned'", r0["origin"] == "planned")

print("\n=== 3. Idempotency ===")
res2 = api("POST", "/api/row", {"planId": PLAN_ID, "addMissingOnly": False})
check("Second generation creates 0 new rows", res2.get("created", -1) == 0, f"created={res2.get('created')}")

print("\n=== 4. Edit Row ===")
rid = r0["id"]
er = api("POST", f"/api/row/{rid}/edit", {"workDone": "Taught with counters.", "status": "Taught"})
check("Edit returns row", "row" in er)
check("workDone updated", er["row"]["workDone"] == "Taught with counters.")
check("teacherEdited True", er["row"]["teacherEdited"] is True)
check("isPlanned False", er["row"]["isPlanned"] is False)
check("status Taught", er["row"]["status"] == "Taught")
check("coverage in response", "coverage" in er)

print("\n=== 5. Reset Row ===")
r1 = doc["rows"][1]
rr = api("POST", f"/api/row/{r1['id']}/reset", {})
check("Reset returns row", "row" in rr, str(rr)[:150])
if "row" in rr:
    check("Work Done back to Planned:", rr["row"]["workDone"].startswith("Planned:"))
    check("Reflection cleared", rr["row"]["reflection"] == "")
    check("Status cleared", rr["row"]["status"] == "")
    check("isPlanned True again", rr["row"]["isPlanned"] is True)

print("\n=== 6. Bulk Status (week 1) ===")
bulk = api("POST", f"/api/row/{PLAN_ID}/bulk-status", {"week": 1, "status": "Taught"})
check("Bulk returns updated count", "updated" in bulk, str(bulk)[:150])
doc2 = api("GET", f"/api/row?planId={PLAN_ID}")
w1 = [r for r in doc2["rows"] if r["week"] == 1]
check("All week-1 rows Taught", all(r["status"] == "Taught" for r in w1), str([r["status"] for r in w1]))
check("Bulk leaves reflections empty", all(r["reflection"] == "" for r in w1))

print("\n=== 7. Coverage ===")
cov = doc2["coverage"]
check("Coverage has stats", all(k in cov for k in ["planned","taught","coveragePct","coverageLabel","gaps"]))
check("taught > 0", cov["taught"] > 0, str(cov["taught"]))
print(f"  {cov['coverageLabel']} | taught={cov['taught']} planned={cov['planned']} gaps={len(cov['gaps'])}")

print("\n=== 8. Carry Over ===")
carry_row = doc2["rows"][-1]
api("POST", f"/api/row/{carry_row['id']}/edit", {"status": "Not Taught - Carry Over"})
cr = api("POST", f"/api/row/{carry_row['id']}/carry-over", {"week": 2, "lesson": 1})
check("Carry-over returns rows", "rows" in cr, str(cr)[:150])
doc3 = api("GET", f"/api/row?planId={PLAN_ID}")
check("Carry-over added a row", len(doc3["rows"]) > row_count, f"{row_count}->{len(doc3['rows'])}")
crows = [r for r in doc3["rows"] if r.get("origin") == "carry-over"]
check("New row origin=carry-over", len(crows) > 0)
if crows:
    check("Carry-over note present", bool(crows[-1].get("carryOverNote")), repr(crows[-1].get("carryOverNote")))
    check("Target week matches", crows[-1]["week"] == 2)

print("\n=== 9. Version History ===")
vr = api("POST", f"/api/row/{PLAN_ID}/versions", {"comment": "after week 1"})
check("Version created", "label" in vr, str(vr)[:150])
vlist = api("GET", f"/api/row/{PLAN_ID}/versions")
check("Version list has versions", len(vlist.get("versions", [])) >= 1)
if vlist["versions"]:
    vid = vlist["versions"][0]["id"]
    prev = api("GET", f"/api/row/{PLAN_ID}/versions/{vid}")
    check("Version preview has label", "label" in prev)
    diff = api("GET", f"/api/row/{PLAN_ID}/versions/{vid}/diff")
    check("Diff has summary", "summary" in diff, str(diff)[:120])
    before = len(api("GET", f"/api/row/{PLAN_ID}/versions")["versions"])
    rest = api("POST", f"/api/row/{PLAN_ID}/versions/{vid}/restore", {})
    check("Restore returns doc", "rows" in rest, str(rest)[:120])
    after = len(api("GET", f"/api/row/{PLAN_ID}/versions")["versions"])
    check("Restore created new version", after > before, f"{before}->{after}")

print("\n=== 10. Save requires comment ===")
nc = api("POST", f"/api/row/{PLAN_ID}/versions", {"comment": ""})
check("Empty comment rejected", "detail" in nc, str(nc)[:150])

print("\n=== 11. Mark Final / Unlock ===")
d4 = api("GET", f"/api/row?planId={PLAN_ID}")
for r in d4["rows"]:
    if not r["status"]:
        api("POST", f"/api/row/{r['id']}/edit", {"status": "Taught"})
fin = api("POST", f"/api/row/{PLAN_ID}/status", {"status": "Final"})
check("Mark Final succeeds", ("rows" in fin or fin.get("status") == "Final"), str(fin)[:150])
blocked = api("POST", "/api/row", {"planId": PLAN_ID, "addMissingOnly": True})
check("Final blocks generation", "detail" in blocked, str(blocked)[:150])
unl = api("POST", f"/api/row/{PLAN_ID}/status", {"status": "Draft"})
check("Unlock to Draft", ("rows" in unl or unl.get("status") == "Draft"), str(unl)[:150])

print("\n=== 12. Vetting Guard ===")
conn = sqlite3.connect("C:/tmp/mwalimu_e2e.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("""SELECT ps.plan_id FROM plan_sections ps
WHERE NOT EXISTS (SELECT 1 FROM plan_citations pc WHERE pc.section_id = ps.id)
GROUP BY ps.plan_id LIMIT 1""")
guard_row = cur.fetchone(); conn.close()
if guard_row:
    gr = api("POST", "/api/row", {"planId": guard_row["plan_id"], "addMissingOnly": False})
    check("Vetting guard returns error", "detail" in gr or "errors" in gr, str(gr)[:150])
else:
    print("  SKIP: no unvetted plan available")

print("\n=== 13. PDF Export ===")
pdf_url = f"{BASE}/api/row/{PLAN_ID}/export.pdf"
pr = subprocess.run(["curl", "-s", "-m", "60", "-o", "C:/tmp/row_test.pdf", "-w", "%{http_code} %{content_type} %{size_download}", pdf_url], capture_output=True, text=True)
check("PDF 200", "200" in pr.stdout, pr.stdout)
check("PDF content-type", "application/pdf" in pr.stdout, pr.stdout)
check("PDF has bytes", os.path.getsize("C:/tmp/row_test.pdf") > 1000)

print("\n=== 14. AI Suggest Reflection (gated) ===")
before = api("GET", f"/api/row?planId={PLAN_ID}")["rows"][2]
ai = api("POST", f"/api/row/{before['id']}/ai/reflection", {})
after = api("GET", f"/api/row?planId={PLAN_ID}")["rows"][2]
check("AI did not modify WorkDone", after["workDone"] == before["workDone"])
check("AI did not modify Status", after["status"] == before["status"])
check("AI draft empty when AI unavailable", not after.get("aiDraft"))

print("\n=== 15. Parser engine unchanged ===")
for f in ["backend/services/parser_engine.py", "backend/services/repair.py"]:
    h = hashlib.md5(open(f, "rb").read()).hexdigest()
    print(f"  {f}: {h}")
check("parser_engine.py present", os.path.exists("backend/services/parser_engine.py"))
check("repair.py present", os.path.exists("backend/services/repair.py"))

print(f"\n{'='*60}\nRESULTS: {passed} passed, {failed} failed\n{'='*60}")
sys.exit(0 if failed == 0 else 1)
