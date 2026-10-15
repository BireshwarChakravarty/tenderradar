"""
TenderRadar: scrape run (every 4 hours via GitHub Actions).

  read CPPP's tender list and its copy of the GeM bid list, side by side
  (the newest tenders, then the next slice of each list, so every open tender
  is re-verified about once a day)
  → merge into the store → AI-score what can be published → prune
  → save data/store.json, and publish only what passes integrity.gate
    to docs/data/tenders.json

SCRAPE_MODE=full reads as much of both lists as time allows in one run (for
a first fill); the next runs carry on from where it stopped.

Exits non-zero when the crawl fails, so GitHub marks the run red and emails
the repo owner instead of failing silently.
"""
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import cppp
import store as store_mod
from ai_scorer import SCORING_VERSION, score
from dates import iso_now, today_ist
from integrity import blockers, gate
from store import load, load_alerted, load_rejected, merge, prune, save, save_alerted, save_rejected

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("Run")

CYCLE_RUNS = int(os.getenv("CPPP_CYCLE_RUNS") or 6)    # runs to re-read each whole list (6 = a day)
WORKERS = {"cppp": 3, "gem": 4}                         # GeM pages are slower to serve
FULL_BUDGET_MIN = float(os.getenv("FULL_BUDGET_MIN") or 100)


def collect(state: dict, full: bool) -> tuple[list, list[str]]:
    """Read every feed side by side. Returns (results, errors)."""
    def one(key):
        return cppp.crawl(key, since_published=state.get(f"{key}_newest_published", ""),
                          cursor=int(state.get(f"{key}_cursor") or 0), cycle_runs=CYCLE_RUNS, full=full,
                          workers=WORKERS[key], budget_min=FULL_BUDGET_MIN if full else None)
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=len(cppp.FEEDS)) as pool:
        futures = {key: pool.submit(one, key) for key in cppp.FEEDS}
        for key, fut in futures.items():
            try:
                res = fut.result()
            except Exception as e:
                log.error("%s failed: %s", cppp.FEEDS[key].name, e)
                errors.append(str(e)[:200])
                continue
            state[f"{key}_cursor"] = res.next_cursor
            if res.newest_published:
                state[f"{key}_newest_published"] = res.newest_published
            results.append(res)
    return results, errors


def run() -> int:
    started = time.monotonic()
    run_info = {"started": iso_now(), "ok": True}
    store, meta = load()
    state = {k: v for k, v in meta.items() if k.split("_", 1)[0] in cppp.FEEDS}
    rejected = load_rejected()
    full = (os.getenv("SCRAPE_MODE") or "").strip().lower() == "full"
    log.info("Store: %d tenders", len(store))

    results, errors = collect(state, full)
    if errors:
        run_info.update(ok=False, error=" | ".join(errors)[:300])

    if results:
        now = iso_now()
        listed = set().union(*(r.listed_ids for r in results))
        for tid in listed & store.keys():
            store[tid].last_seen = now
        stats = merge(store, [t for r in results for t in r.tenders])
        today_s = today_ist().isoformat()
        for tid in [*stats["rejected_ids"], *(i for r in results for i in r.closed_ids)]:
            rejected.setdefault(tid, today_s)
        run_info.update(
            listed=len(listed), pages=sum(r.pages for r in results), rows=sum(r.seen_rows for r in results),
            new=stats["new"], updated=stats["updated"], excluded=stats["excluded"],
            duplicates=stats["duplicates"],
            closed_on_arrival=stats["closed_on_arrival"] + sum(r.closed_on_arrival for r in results),
            unparsed=sum(r.unparsed for r in results), backlog=sum(r.backlog for r in results),
        )
        log.info("New %d · refreshed %d · excluded by rules %d · already closed %d",
                 stats["new"], stats["updated"], stats["excluded"], run_info["closed_on_arrival"])

    today = today_ist()
    before = set(store)
    run_info["pruned"] = prune(store)      # first, so a duplicate's assessment is reused, not paid for again
    for tid in before - set(store):            # don't fetch pruned duplicates or closed tenders again
        rejected.setdefault(tid, today.isoformat())
    alerted = load_alerted()
    carried = {kept for gone, kept in store_mod.replaced.items() if gone in alerted}
    if carried - alerted:
        save_alerted(alerted | carried)        # already alerted under the dropped duplicate's ID

    gate(store, today)   # correct bad fields and clear unpublishable AI text before scoring
    # Score what passes the source checks (relevance is what scoring decides):
    # new tenders, AI text that was cleared, and older prompt versions
    unscored = [t for t in store.values()
                if (t.score is None or t.scoring_version < SCORING_VERSION)
                and not blockers(t, today)]
    if unscored:
        log.info("Scoring %d tenders…", len(unscored))
        run_info["scored"] = score(unscored)

    run_info["finished"] = iso_now()
    report = save(store, run_info, state)
    run_info["published"] = report["published"]
    save_rejected(rejected)
    log.info("Done in %ds: %s", time.monotonic() - started,
             {k: v for k, v in run_info.items() if k not in ("started", "finished")})
    return 0 if run_info["ok"] else 1


if __name__ == "__main__":
    sys.exit(run())
