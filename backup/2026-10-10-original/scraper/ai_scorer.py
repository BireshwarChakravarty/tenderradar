import json
import logging
import time
from base_scraper import Tender
from config import ANTHROPIC_API_KEY, COMPANY_PROFILE, MIN_RELEVANCE_SCORE

logger = logging.getLogger("AIScorer")

try:
    import anthropic
    _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
except ImportError:
    _client = None
    logger.warning("anthropic package not installed — AI scoring disabled")


def score_tenders(tenders: list) -> list:
    if not _client:
        logger.warning("AI scoring skipped — no Anthropic client")
        return tenders
    if not tenders:
        return tenders
    logger.info(f"AI scoring {len(tenders)} tenders…")
    for i, tender in enumerate(tenders):
        try:
            _score_one(tender)
            logger.info(f"  [{i+1}/{len(tenders)}] {tender.portal} — {tender.title[:50]} → {tender.score}/10")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Scoring failed for {tender.id}: {e}")
            tender.score = 5.0
            tender.summary = "AI scoring unavailable."
    return tenders


def _score_one(tender) -> None:
    prompt = f"""You are evaluating government tenders for relevance to a PR and communications agency.

COMPANY PROFILE:
{COMPANY_PROFILE}

TENDER:
- Title: {tender.title}
- Portal: {tender.portal}
- Category: {tender.category}
- Value: {tender.value_str}
- Deadline: {tender.deadline}
- Reference: {tender.ref_no}
- Description: {tender.description[:500]}

Respond ONLY with a JSON object (no markdown, no explanation):
{{
  "score": <float 1.0-10.0>,
  "fit": "<one sentence on capability match>",
  "opportunity": "<one sentence on why this is or is not worth pursuing>",
  "recommendation": "<Bid / Watch / Skip>"
}}"""

    msg = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    data = json.loads(raw)
    tender.score   = round(float(data.get("score", 5.0)), 1)
    tender.summary = (
        f"**Fit:** {data.get('fit', '')}\n\n"
        f"**Opportunity:** {data.get('opportunity', '')}\n\n"
        f"**Recommendation:** {data.get('recommendation', '')}"
    )


def filter_relevant(tenders: list) -> list:
    return [t for t in tenders if t.score >= MIN_RELEVANCE_SCORE]
