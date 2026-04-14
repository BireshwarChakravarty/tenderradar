"""
TenderRadar — Main Orchestrator
Source: TenderDetail.com aggregator only (all direct gov portals are IP-blocked)
"""
import logging, sys, json
from datetime import datetime
from deduplicator import merge_new_tenders, load_existing, save_tenders
from ai_scorer import score_tenders

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("Orchestrator")


def run():
    start = datetime.utcnow()
    logger.info("=" * 60)
    logger.info(f"TenderRadar started at {start.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    logger.info("=" * 60)
    all_scraped = []

    # ── TenderDetail.com (only working source) ────────────────
    try:
        from aggregator_scrapers import scrape_all_aggregators
        results = scrape_all_aggregators()
        all_scraped.extend(results)
        logger.info(f"✓ TenderDetail.com: {len(results)} tenders")
    except Exception as e:
        logger.error(f"✗ Aggregator failed: {e}")

    logger.info(f"\nTotal scraped (pre-dedup): {len(all_scraped)}")

    truly_new, _ = merge_new_tenders(all_scraped)
    logger.info(f"New: {len(truly_new)} / Store: {len(load_existing())}")

    if truly_new:
        logger.info("AI scoring new tenders…")
        scored = score_tenders(truly_new)
        from config import TENDERS_FILE
        if TENDERS_FILE.exists():
            with open(TENDERS_FILE) as f:
                data = json.load(f)
            existing = {t["id"]: t for t in data.get("tenders", [])}
            for t in scored:
                if t.id in existing:
                    existing[t.id]["score"]   = t.score
                    existing[t.id]["summary"] = t.summary
            save_tenders(existing)
        logger.info("Scoring done.")
    else:
        logger.info("No new tenders this run.")

    elapsed = (datetime.utcnow() - start).seconds
    logger.info("=" * 60)
    logger.info(f"Done in {elapsed}s | New: {len(truly_new)} | Total: {len(all_scraped)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
