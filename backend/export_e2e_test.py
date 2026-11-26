#!/usr/bin/env python3
"""Phase 7 export endpoint end-to-end validation."""
import json, subprocess, os, time, zipfile, io, hashlib

BASE = "http://127.0.0.1:8768"
PLAN = "e5b7d0d2-97f5-40a3-948b-01e758a843d8"  # scheme with 1 plan + 1 note
PLAN2 = "9c0294d5-f7e1-467d-8458-cbe32b6cd2b7"  # scheme with 53 ROW rows, 0 plans/notes

def api(method, path, body=None):
    cmd = ["curl", "-s", "-m", "60", "-X", method, f"{BASE}{path}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_raw": r.stdout[:200]}

passed = failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        print(f"  PASS: {name}"); passed += 1
    else:
        print(f"  FAIL: {name} {detail}"); failed += 1

def wait_job(jid, timeout=90):
    for _ in range(timeout):
        j = api("GET", f"/api/export/{jid}")
        if j.get("status") in ("done", "failed"):
            return j
        time.sleep(1)
    return api("GET", f"/api/export/{jid}")

INC_ALL = {
    "cover": True, "coverage": True, "scheme": True,
    "plans": {"include": True, "mode": "all", "weeks": [], "lessonIds": []},
    "notes": {"include": True, "mode": "all", "weeks": [], "lessonIds": []},
    "row": True, "citations": True,
    "includeDrafts": True, "includeAnswers": True, "includeVersionHistory": True,
}

print("=== 1. PDF export, all sections ===")
r = api("POST", "/api/export", {"planId": PLAN, "includes": INC_ALL, "format": "pdf"})
check("POST returns jobId", bool(r.get("jobId")), str(r))
j = wait_job(r["jobId"])
check("Job completes", j.get("status") == "done", str(j)[:300])
check("Has file URL", bool(j.get("fileUrl")))
check("Has page count", j.get("pageCount", 0) > 0)
check("Has file size", j.get("fileSize", 0) > 1000)
secs = j["manifest"]["sections"]
snames = [s["name"] for s in secs]
check("7 sections in order", snames == ["cover","coverage","scheme","plans","notes","row","citations"], str(snames))
check("Scheme is landscape", [s for s in secs if s["name"]=="scheme"][0]["orientation"]=="landscape")
check("Plans are portrait", [s for s in secs if s["name"]=="plans"][0]["orientation"]=="portrait")
check("ROW is landscape", [s for s in secs if s["name"]=="row"][0]["orientation"]=="landscape")
check("Total pages = sum of sections", j["manifest"]["totalPages"] == sum(s["pages"] for s in secs), str(j["manifest"]["totalPages"]))

print("\n=== 2. Download PDF + inspect orientation/text ===")
pdf = subprocess.run(["curl","-s","-m","30",f"{BASE}{j['fileUrl']}"],capture_output=True).stdout
open("C:/tmp/term_e2e.pdf","wb").write(pdf)
check("PDF bytes match fileSize", len(pdf) == j["fileSize"], f"{len(pdf)} vs {j['fileSize']}")
import fitz
d = fitz.open(stream=pdf, filetype="pdf")
check("PDF opens", d.page_count == j["pageCount"])
land = [i for i,p in enumerate(d) if p.rect.width > p.rect.height]
port = [i for i,p in enumerate(d) if p.rect.width <= p.rect.height]
check("Has landscape pages", len(land) > 0, str(land))
check("Has portrait pages", len(port) > 0, str(port))
full_text = "\n".join(p.get_text() for p in d)
check("Cover text present", "CBC Curriculum Companion" in full_text)
check("Coverage text present", "Coverage Summary" in full_text)
check("Scheme text present", "SCHEME OF WORK" in full_text)
check("Plan text present", "LESSON PLAN" in full_text)
check("Notes text present", "LESSON NOTES" in full_text)
check("Answers page present", "Teacher Only" in full_text)
check("ROW text present", "Record of Work" in full_text)
check("Citations text present", "Sources & Transparency Log" in full_text)
check("Global page X of Y present", "Page 2 of" in full_text, full_text[-200:])
check("Draft watermark present", "DRAFT - Not Final" in full_text)
d.close()

print("\n=== 3. Answers OFF ===")
inc_noans = dict(INC_ALL); inc_noans["includeAnswers"] = False
r2 = api("POST","/api/export",{"planId":PLAN,"includes":inc_noans,"format":"pdf"})
j2 = wait_job(r2["jobId"])
check("Answers-off job done", j2.get("status")=="done", str(j2)[:200])
pdf2 = subprocess.run(["curl","-s","-m","30",f"{BASE}{j2['fileUrl']}"],capture_output=True).stdout
d2 = fitz.open(stream=pdf2, filetype="pdf")
t2 = "\n".join(p.get_text() for p in d2)
check("No Teacher Only page", "Teacher Only" not in t2)
check("Notes still present", "LESSON NOTES" in t2)
d2.close()

print("\n=== 4. Weeks filter for plans/notes ===")
inc_w1 = dict(INC_ALL)
inc_w1["plans"] = {"include":True,"mode":"weeks","weeks":[1],"lessonIds":[]}
inc_w1["notes"] = {"include":True,"mode":"weeks","weeks":[1],"lessonIds":[]}
r3 = api("POST","/api/export",{"planId":PLAN,"includes":inc_w1,"format":"pdf"})
j3 = wait_job(r3["jobId"])
check("Weeks-filter job done", j3.get("status")=="done", str(j3)[:200])

print("\n=== 5. ZIP export + manifest ===")
inc_zip = dict(INC_ALL); inc_zip["includeAnswers"] = False
r4 = api("POST","/api/export",{"planId":PLAN,"includes":inc_zip,"format":"zip"})
j4 = wait_job(r4["jobId"])
check("ZIP job done", j4.get("status")=="done", str(j4)[:300])
check("ZIP filename ends .zip", j4.get("fileName","").endswith(".zip"), j4.get("fileName",""))
zdata = subprocess.run(["curl","-s","-m","30",f"{BASE}{j4['fileUrl']}"],capture_output=True).stdout
z = zipfile.ZipFile(io.BytesIO(zdata))
names = z.namelist()
check("ZIP has manifest.json", "manifest.json" in names, str(names))
check("ZIP has 6 PDFs", len([n for n in names if n.endswith('.pdf')]) == 6, str(names))
m = json.loads(z.read("manifest.json"))
check("Manifest has files", len(m.get("files",[])) == 6)
check("Manifest files have page counts", all(f.get("pages",0)>0 for f in m["files"]))
check("Manifest files have orientations", all(f.get("orientation") in ("portrait","landscape") for f in m["files"]))
check("Manifest has coverage", "coverage" in m)
z.close()

print("\n=== 6. History + DELETE ===")
h = api("GET", f"/api/export/history?planId={PLAN}")
check("History has jobs", len(h.get("jobs",[])) >= 4, str(len(h.get("jobs",[]))))
jid_del = h["jobs"][0]["id"]
dl = api("DELETE", f"/api/export/{jid_del}")
check("DELETE succeeds", dl.get("ok") is True, str(dl))
check("GET deleted job 404", "detail" in api("GET", f"/api/export/{jid_del}"))

print("\n=== 7. Library doc -> plans mapping ===")
pfd = api("GET", "/api/export/plans-for-document?documentId=nonexistent")
check("plans-for-document returns list", isinstance(pfd.get("plans"), list), str(pfd))

print("\n=== 8. Parser engine unchanged ===")
for f in ["/c/Users/user/Desktop/mwalimu-studio/backend/services/parser_engine.py",
          "/c/Users/user/Desktop/mwalimu-studio/backend/services/repair.py"]:
    p = f.replace("/c/", "C:/")
    h = hashlib.md5(open(p,"rb").read()).hexdigest()
    print(f"  {os.path.basename(p)}: {h}")

print(f"\n{'='*60}\nRESULTS: {passed} passed, {failed} failed\n{'='*60}")
