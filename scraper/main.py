"""
TenderRadar: scrape run (every 4 hours via GitHub Actions).

  read CPPP (the newest tenders, then the next third of the full list, so
  every open tender is re-verified every 12 hours)
  → merge into the store → AI-score what can be published → prune
  → save data/store.json, and publish only what passes integrity.gate
    to docs/data/tenders.json

SCRAPE_MODE=full reads the whole list in one run (it carries on in the next
runs if it runs out of time); the first run always does.

Exits non-zero when the crawl fails, so GitHub marks the run red and emails
the repo owner instead of failing silently.
"""
import logging
import os
import sys
import time

import cppp
import store as store_mod
from ai_scorer import SCORING_VERSION, score
from dates import iso_now, today_ist
from integrity import blockers, gate
from store import load, load_alerted, load_rejected, merge, prune, save, save_alerted, save_rejected

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("Run")

CYCLE_RUNS = int(os.getenv("CPPP_CYCLE_RUNS") or 3)    # runs to re-read the whole list


def run() -> int:
    started = time.monotonic()
    run_info = {"started": iso_now(), "ok": True}
    store, meta = load()
    state = {k: v for k, v in meta.items() if k.startswith("cppp_")}
    rejected = load_rejected()
    full = (os.getenv("SCRAPE_MODE") or "").strip().lower() == "full"
    log.info("Store: %d tenders", len(store))

    try:
        res = cppp.crawl(since_published=state.get("cppp_newest_published", ""),
                         cursor=int(state.get("cppp_cursor") or 0), cycle_runs=CYCLE_RUNS, full=full)
    except Exception as e:
        log.error("Crawl failed: %s", e)
        run_info.update(ok=False, error=str(e)[:300])
        res = None

    if res:
        now = iso_now()
        for tid in res.listed_ids & store.keys():
            store[tid].last_seen = now
        stats = merge(store, res.tenders)
        today_s = today_ist().isoformat()
        for tid in [*stats["rejected_ids"], *res.closed_ids]:
            rejected.setdefault(tid, today_s)
        state["cppp_cursor"] = res.next_cursor
        if res.newest_published:
            state["cppp_newest_published"] = res.newest_published
        run_info.update(
            listed=len(res.listed_ids), pages=res.pages, rows=res.seen_rows, new=stats["new"],
            updated=stats["updated"], excluded=stats["excluded"], duplicates=stats["duplicates"],
            closed_on_arrival=stats["closed_on_arrival"] + res.closed_on_arrival,
            unparsed=res.unparsed, backlog=res.backlog,
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
