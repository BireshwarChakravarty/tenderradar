"""
TenderRadar: AI assessment of each tender with Claude.

For every new tender, Claude returns a structured assessment: a short clean
headline, the issuing authority, what kind of procurement it is, a 1 to 10 fit
score against the company profile (scraper/knowledge/profile.md plus private notes), a Bid / Watch / Skip call, and two one-line
explanations. Structured outputs guarantee the shape, so there is no JSON
parsing to go wrong.

Tenders that can't be scored (no API key, API error) keep score=None and are
retried on the next run rather than being given a made-up score.
"""
import logging
from typing import Literal

from pydantic import BaseModel, Field

from config import AI_MODEL, ANTHROPIC_API_KEY, COMPANY_PROFILE, HAS_PRIVATE_KNOWLEDGE
from dates import days_until, iso_now
from models import Tender, plain

# Bump when SYSTEM_PROMPT changes in a way that should re-score stored tenders
SCORING_VERSION = 3

log = logging.getLogger("AIScorer")


class Assessment(BaseModel):
    headline: str = Field(description="What is being procured, in under 80 characters of plain English")
    authority: str = Field(description="Issuing organisation if identifiable from the text, else empty")
    kind: Literal["services", "goods", "works", "auction", "other"]
    score: float = Field(description="Fit for the company, 1.0 to 10.0")
    recommendation: Literal["Bid", "Watch", "Skip"]
    fit: str = Field(description="One sentence: how the scope matches the company's capabilities")
    reason: str = Field(description="One sentence: why it is or isn't worth pursuing")


SYSTEM_PROMPT = f"""You assess Indian government tenders for one company and decide whether it should bid.

<company_profile>
{COMPANY_PROFILE}
</company_profile>

For each tender you get the title, the issuing details we could read, and the deadline.

Fields:
- headline: what the buyer wants, in plain English, under 80 characters. Drop boilerplate such as
  "Tender for", "Bids are invited for", "Custom Bid For Services -", "Corrigendum", reference numbers
  and location suffixes. Example: "Social media management agency for the Ministry of Coal".
- authority: the buyer's name (ministry, department, PSU, municipal body) if the text names it;
  otherwise an empty string. Don't guess.
- kind: "services" when the buyer hires an agency or service provider (including empanelment);
  "goods" for supply of items or equipment; "works" for construction or civil works;
  "auction" when the government sells or licenses something (for example advertising rights on
  hoardings, buses or stations). The company would be paying, not being paid.
- score: follow "How to score" in the company profile. The overall scale is
  9 to 10  a core service of the company, clearly scoped, for a buyer it targets
  7 to 8   a strong fit; most of the scope is work the company does
  5 to 6   a partial fit; worth a look, or a consortium or subcontracting angle
  3 to 4   tangential; only a small part of the scope fits
  1 to 2   not relevant. Anything that is goods, works or an auction scores here
- recommendation: "Bid" for strong fits (score 7 or more), "Watch" for partial fits or when key
  details are missing, "Skip" otherwise, and "Skip" when the tender demands an empanelment the
  company doesn't hold. Don't lower the score because the deadline is close; the deadline is shown
  separately.
- fit: one plain sentence on which of the company's services or past work this matches.
- reason: one plain sentence on whether to pursue it, naming the main risk if there is one
  (missing empanelment, very large contract, sectional cut-off, deadline under about 10 days,
  already bid). No filler.

Write in plain sentences. Never use em dashes; use commas, full stops or "and" instead."""


def _client():
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed, AI scoring disabled")
        return None
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=3)


def _describe(t: Tender) -> str:
    left = days_until(t.deadline)
    closes = (f"{t.deadline} ({left} days from today)" if left is not None
              else "not stated")
    lines = [
        f"Title: {t.title}",
        f"Category (keyword-based guess): {t.category}",
        f"Issued by: {t.authority or 'not stated'}",
        f"Location: {t.location or 'not stated'}",
        f"Portal: {t.portal or 'not stated'}",
        f"Estimated value: {f'₹{t.value_inr:,.0f}' if t.value_inr else 'not stated'}",
        f"Bid deadline: {closes}",
    ]
    return "\n".join(lines)


def score(tenders: list[Tender]) -> int:
    """Assess each tender in place. Returns how many were scored."""
    client = _client()
    if client is None:
        if tenders:
            log.warning("ANTHROPIC_API_KEY not set, %d tenders left unscored", len(tenders))
        return 0

    import anthropic

    if not HAS_PRIVATE_KNOWLEDGE:
        log.info("COMPANY_KNOWLEDGE not set, scoring with the public profile only")
    done = 0
    for i, t in enumerate(tenders, 1):
        try:
            resp = client.messages.parse(
                model=AI_MODEL,
                max_tokens=2000,
                system=[{"type": "text", "text": SYSTEM_PROMPT,
                         "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": _describe(t)}],
                output_format=Assessment,
            )
        except anthropic.AuthenticationError:
            log.error("Anthropic API key rejected, stopping AI scoring for this run")
            break
        except anthropic.APIError as e:
            log.warning("[%d/%d] %s: API error, will retry next run: %s", i, len(tenders), t.id, e)
            continue

        a = resp.parsed_output
        if resp.stop_reason != "end_turn" or a is None:
            log.warning("[%d/%d] %s: no assessment (stop_reason=%s), will retry next run",
                        i, len(tenders), t.id, resp.stop_reason)
            continue

        t.headline = plain(a.headline)[:120]
        t.authority = plain(a.authority) or t.authority
        t.kind = a.kind
        t.score = round(min(10.0, max(1.0, a.score)), 1)
        t.recommendation = a.recommendation
        t.fit = plain(a.fit)
        t.reason = plain(a.reason)
        t.scored_at = iso_now()
        t.scoring_version = SCORING_VERSION
        done += 1
        log.info("[%d/%d] %4.1f %-5s %s", i, len(tenders), t.score, t.recommendation, t.headline[:70])
    return done
