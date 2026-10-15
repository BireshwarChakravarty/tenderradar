"""Temporary dry run of the real pipeline on a small slice of both lists. Commits nothing."""
import json, os, subprocess, sys
os.environ["CPPP_CYCLE_RUNS"] = "60"
r = subprocess.run([sys.executable, "scraper/main.py"], text=True)
print("main.py exit code", r.returncode)
d = json.load(open("data/store.json"))
print("store meta:", {k: v for k, v in d["meta"].items()})
new = [t for t in d["tenders"] if t["source"] == "CPPP"]
print(f"CPPP/GeM records: {len(new)}")
for t in new:
    print(f"  {t['portal']:4} {t['ref_no'][:24]:24} {t['published']} -> {t['deadline']} | {t['authority'][:40]} | {t['title'][:110]}")
p = json.load(open("docs/data/tenders.json"))
print("published meta:", {k: v for k, v in p["meta"].items() if k != "last_run"}, p["meta"].get("last_run"))
