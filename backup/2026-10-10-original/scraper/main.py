"""
TenderRadar — Main Orchestrator
Source: TenderDetail.com aggregator (all direct gov portals are IP-blocked from GitHub Actions)
"""
import json
import logging
import sys
from datetime import datetime

from deduplicator import load_existing, merge_new_tenders, save_tenders
from ai_scorer import score_tenders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("Orchestrator")


def run():
    start = datetime.utcnow()
    logger.info("=" * 60)
    logger.info("TenderRadar started at %s UTC", start.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)
    all_scraped = []

    try:
        from aggregator_scrapers import scrape_all_aggregators
        results = scrape_all_aggregators()
        all_scraped.extend(results)
        logger.info("✓ TenderDetail.com: %d tenders", len(results))
    except Exception as e:
        logger.error("✗ Aggregator failed: %s", e)

    logger.info("\nTotal scraped (pre-dedup): %d", len(all_scraped))

    truly_new, _ = merge_new_tenders(all_scraped)
    logger.info("New: %d / Store: %d", len(truly_new), len(load_existing()))

    if truly_new:
        logger.info("AI scoring %d new tenders…", len(truly_new))
        scored = score_tenders(truly_new)

        from config import TENDERS_FILE
        if TENDERS_FILE.exists():
            with open(TENDERS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            existing = {t["id"]: t for t in data.get("tenders", [])}
            for t in scored:
                if t.id in existing:
                    existing[t.id]["score"]   = t.score
                    existing[t.id]["summary"] = t.summary
            save_tenders(existing)
            logger.info("Scores saved for %d tenders.", len(scored))
    else:
        logger.info("No new tenders this run.")

    elapsed = (datetime.utcnow() - start).seconds
    logger.info("=" * 60)
    logger.info("Done in %ds | New: %d | Total scraped: %d", elapsed, len(truly_new), len(all_scraped))
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
