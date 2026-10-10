"""
TenderRadar: scrape run (every 4 hours via GitHub Actions).

  crawl TenderDetail → merge into the store → AI-score anything unscored
  → prune old tenders → save docs/data/tenders.json

Exits non-zero when the crawl fails, so GitHub marks the run red and emails
the repo owner instead of failing silently.
"""
import logging
import sys
import time

from ai_scorer import SCORING_VERSION, score
from dates import from_str, iso_now, today_ist
from store import load, load_rejected, merge, prune, save, save_rejected
from tenderdetail import crawl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("Run")


def run() -> int:
    started = time.monotonic()
    run_info = {"started": iso_now(), "ok": True}
    store, _ = load()
    rejected = load_rejected()
    log.info("Store: %d tenders", len(store))

    try:
        res = crawl(store, set(rejected))
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
        run_info.update(
            listed=len(res.listed_ids), pages=res.pages, new=stats["new"],
            updated=stats["updated"], excluded=stats["excluded"], duplicates=stats["duplicates"],
            closed_on_arrival=stats["closed_on_arrival"] + res.closed_on_arrival,
            unparsed=res.unparsed, backlog=res.backlog,
        )
        log.info("New %d · refreshed %d · excluded by rules %d · already closed %d",
                 stats["new"], stats["updated"], stats["excluded"], run_info["closed_on_arrival"])

    today = today_ist()
    # New tenders, plus any scored with an older version of the prompt
    unscored = [t for t in store.values()
                if (t.score is None or t.scoring_version < SCORING_VERSION)
                and (not t.deadline or from_str(t.deadline) >= today)]
    if unscored:
        log.info("Scoring %d tenders…", len(unscored))
        run_info["scored"] = score(unscored)

    before = set(store)
    run_info["pruned"] = prune(store)
    for tid in before - set(store):            # don't fetch pruned duplicates or closed tenders again
        rejected.setdefault(tid, today.isoformat())
    run_info["finished"] = iso_now()
    save(store, run_info)
    save_rejected(rejected)
    log.info("Done in %ds: %s", time.monotonic() - started,
             {k: v for k, v in run_info.items() if k not in ("started", "finished")})
    return 0 if run_info["ok"] else 1


if __name__ == "__main__":
    sys.exit(run())
