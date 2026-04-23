"""
TenderRadar — Deduplicator
Merges newly-scraped tenders into the persistent JSON store,
preserving user-set statuses and AI scores across runs.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from base_scraper import Tender
from config import TENDERS_FILE

logger = logging.getLogger("Deduplicator")

# Portal name variants to normalise → canonical form
_PORTAL_ALIASES = {
    "Govt Portal": "Gov Portal",
    "Government Portal": "Gov Portal",
}


def _normalise(tenders_list: list[dict]) -> list[dict]:
    """
    Clean up data quality issues on every save:
      - Normalise legacy portal name variants
      - Replace 'N/A' / missing deadlines with today+30
    """
    default_dl = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    for t in tenders_list:
        # Portal normalisation
        if t.get("portal") in _PORTAL_ALIASES:
            t["portal"] = _PORTAL_ALIASES[t["portal"]]
        # Deadline normalisation
        if not t.get("deadline") or t["deadline"] == "N/A":
            t["deadline"] = default_dl
    return tenders_list


def load_existing() -> dict[str, dict]:
    """Load existing tenders as {id: tender_dict}."""
    if not TENDERS_FILE.exists():
        return {}
    try:
        with open(TENDERS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {t["id"]: t for t in data.get("tenders", []) if t.get("id")}
    except Exception as e:
        logger.error("Failed to load existing tenders: %s", e)
        return {}


def save_tenders(tender_dict: dict[str, dict]) -> None:
    """Save all tenders back to JSON. Writes meta.last_updated for the dashboard."""
    tenders_list = sorted(
        tender_dict.values(),
        key=lambda t: t.get("scraped_at", ""),
        reverse=True,
    )
    tenders_list = tenders_list[:1000]
    tenders_list = _normalise(tenders_list)

    out = {
        "tenders": tenders_list,
        "meta": {
            "total":        len(tenders_list),
            "portals":      sorted({t.get("portal", "") for t in tenders_list if t.get("portal")}),
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    with open(TENDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d tenders to %s", len(tenders_list), TENDERS_FILE)


def merge_new_tenders(new_tenders: list[Tender]) -> tuple[list[Tender], list[dict]]:
    """
    Merge new tenders into the existing store.
    Returns (truly_new_list, all_tenders_list).
    """
    existing = load_existing()
    truly_new: list[Tender] = []

    for t in new_tenders:
        if t.id not in existing:
            truly_new.append(t)
            existing[t.id] = t.to_dict()
        else:
            stored = existing[t.id]
            if stored.get("status", "New") != "New":
                continue
            stored["deadline"]   = t.deadline or stored.get("deadline", "")
            stored["url"]        = t.url or stored.get("url", "")
            stored["scraped_at"] = t.scraped_at

    save_tenders(existing)
    logger.info(
        "New tenders this run: %d / Total in store: %d",
        len(truly_new), len(existing),
    )
    return truly_new, list(existing.values())
