"""
TenderRadar — Claude AI Relevance Scorer
Scores each new tender 1-10 based on your company profile.
Batches requests to stay within API limits.
"""
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


def score_tenders(tenders: list[Tender]) -> list[Tender]:
    """Score a list of tenders. Returns them with .score and .summary populated."""
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
            time.sleep(1)  # rate limit courtesy
        except Exception as e:
            logger.error(f"Scoring failed for {tender.id}: {e}")
            tender.score = 5.0
            tender.summary = "AI scoring unavailable."

    return tenders


def _score_one(tender: Tender) -> None:
    """Call Claude and update tender.score and tender.summary in-place."""
    prompt = f"""You are evaluating government tenders for a communications and PR agency.

AGENCY PROFILE:
{COMPANY_PROFILE}

TENDER:
- Title: {tender.title}
- Portal: {tender.portal}
- Service Area: {tender.category}
- Value: {tender.value_str}
- Deadline: {tender.deadline}
- Reference: {tender.ref_no}
- Description: {tender.description[:500]}

Score this tender's relevance to the agency. Consider: Does it involve PR, communications, 
social media, digital outreach, content, media monitoring, events, or reputation work?
Is the client type (government/PSU/institutional) a fit? Is the scale appropriate?

Respond ONLY with a JSON object (no markdown, no explanation):
{{
  "score": <float 1.0-10.0>,
  "fit": "<one sentence on capability fit>",
  "opportunity": "<one sentence on why this is or isn't worth pursuing>",
  "recommendation": "<Bid / Shortlist / Pass>"
}}"""

    msg = _client.messages.create(
        model="claude-haiku-4-5-20251001",   # cheapest, fast enough for scoring
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = msg.content[0].text.strip()
    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data = json.loads(raw)
    tender.score   = round(float(data.get("score", 5.0)), 1)
    tender.summary = (
        f"**Fit:** {data.get('fit','')}\n\n"
        f"**Opportunity:** {data.get('opportunity','')}\n\n"
        f"**Recommendation:** {data.get('recommendation','')}"
    )


def filter_relevant(tenders: list[Tender]) -> list[Tender]:
    """Return only tenders scoring above the threshold."""
    return [t for t in tenders if t.score >= MIN_RELEVANCE_SCORE]
