"""
TenderRadar: relevance rules.

Cheap, rule-based screening that runs before any AI call. It removes tenders
that are never a fit for a communications agency, however they were found:
auctions that *sell* advertising space, construction and civil works, and
goods/equipment supply. Everything else goes to the AI scorer.

Edit SEARCH_KEYWORDS and EXCLUDE_PATTERNS to tune what TenderRadar collects.
"""
import re

from config import MIN_RELEVANCE_SCORE

# TenderDetail.com listing slugs: /Indian-tender/<slug>-tenders
SEARCH_KEYWORDS = [
    "public-relations",
    "pr-agency",
    "communication-agency",
    "integrated-communication",
    "media-monitoring",
    "social-media-management",
    "digital-marketing-agency",
    "digital-outreach",
    "advertising-agency",
    "media-buying",
    "event-publicity",
    "content-development",
    "website-development",
    "seo-services",
]

# A title matching any of these is dropped before scoring.
# Each line was checked against ~1,000 previously scored tenders: together
# they removed hundreds of low-scoring ones and almost no good ones.
# Always excluded: the government is selling or leasing something, or buying
# equipment. Agency wording in the title doesn't rescue these ("Selection of
# advertising agencies for exclusive advertisement rights" is still a sale).
HARD_EXCLUDE_PATTERNS = [
    r"\bauction\b",
    r"\badverti[sz](?:ing|ement)s?(?: space)? rights?\b",
    r"\b(?:display|licen[cs]e|right|grant of rights) (?:of|for|to) (?:commercial )?advert",
    r"\bgrant of rights\b|\bsale of\b|\bscrap\b|\bcondemned\b|\bon lease\b",
    r"\bcctv\b|\bsurveillance\b|\b(?:ip|bullet|dome|ptz) cameras?\b",
    r"\bsupply,? (?:and |& )?(?:installation|fitment|commissioning)\b|\binstallation (?:and|&) commissioning\b",
    r"\b(?:led|light[- ]?box|advertising) (?:advertising )?boards?\b",
    r"\badverti[sz]ing spaces?\b",
    r"\bchannel partner\b|\bauthori[sz]ed distributor\b",
]

# Excluded unless the title clearly describes agency or publicity work
# (KEEP_PATTERNS below), e.g. an IEC campaign that lists hoardings among
# its deliverables.
EXCLUDE_PATTERNS = [
    r"\b(?:hoardings?|unipoles?|kiosks?|glow ?signs?|sign ?boards?|billboards?)\b",
    r"\bwall painting\b|\bvinyl wrap",
    r"\badvertisement (?:on|behind|through) (?:etm|ticket|bus|train|rake)",
    # Construction, civil and engineering works
    r"\bconstruction of\b|\bcivil works?\b|\bskywalk\b|\bflyovers?\b|\bunderpass(?:es)?\b",
    r"\bgeo-? ?technical\b|\bsoil investigation\b|\bsurvey(?:ing)? work\b",
    r"\b(?:meter|electrical|plumbing) (?:repair|replacement|installation)",
    # Goods and equipment supply
    r"\bnbcd\b|\bhelmets?\b|\bprojectors?\b|\bfurniture\b",
    r"\bsound systems?\b|\bstage (?:set ?up|lights?|lighting)\b",
    # "Communication" listings also return telecom hardware
    r"\bcommunication (?:equipments?|sets?|cables?|cards?|modules?|gateway|test sets?|lab)\b",
    r"\bradio sets?\b|\bsoftware defined radio\b|\bofc cables?\b|\bconsumables\b|\bintercom\b",
    r"\b(?:supply|procurement|purchase) of (?:\w+ ){0,3}(?:items?|equipments?|hardware|materials?|goods|accessories)\b",
    # Clearly unrelated services
    r"\bhat fee\b|\bparking\b|\bcanteen\b|\bhousekeeping\b|\bsecurity guards?\b",
    r"\bsoft skills? training\b|\bline producer\b",
]

KEEP_PATTERNS = [
    r"\biec\b", r"\bpublicity\b", r"\bcampaigns?\b", r"\bmulti-?media\b", r"\bcreative\b",
    r"\bpublic relations\b", r"\bsocial media\b", r"\bself-help group\b",
]

_HARD = re.compile("|".join(f"(?:{p})" for p in HARD_EXCLUDE_PATTERNS), re.IGNORECASE)
_EXCLUDE = re.compile("|".join(f"(?:{p})" for p in EXCLUDE_PATTERNS), re.IGNORECASE)
_KEEP = re.compile("|".join(KEEP_PATTERNS), re.IGNORECASE)


def exclusion_reason(title: str) -> str:
    """The matched phrase if the tender should be dropped, else ""."""
    m = _HARD.search(title or "")
    if m:
        return m.group(0)
    m = _EXCLUDE.search(title or "")
    if not m or _KEEP.search(title):
        return ""
    return m.group(0)


CATEGORIES = [
    "Public Relations",
    "Integrated Communications",
    "Social Media",
    "Digital Marketing",
    "Media Monitoring",
    "Advertising & Media Buying",
    "Events & Publicity",
    "Creative & Content",
    "Website & SEO",
    "Other",
]

# First match wins, so the most specific phrases come first
_CATEGORY_RULES = [
    ("Media Monitoring",           r"media monitoring|media analysis|news monitoring"),
    ("Social Media",               r"social media"),
    ("Public Relations",           r"public relations|\bpr agency|\bpr\b|media relations|press"),
    ("Integrated Communications",  r"communication|outreach|\biec\b|awareness campaign"),
    ("Advertising & Media Buying", r"advertis|media buying|media planning|campaign|tvc|creative agency"),
    ("Events & Publicity",         r"event|exhibition|fair|mela|conference|seminar|publicity"),
    ("Website & SEO",              r"website|web portal|\bseo\b|search engine"),
    ("Digital Marketing",          r"digital marketing|performance marketing|digital media|online"),
    ("Creative & Content",         r"content|design|video|film|documentary|photograph|e-?learning"),
]
_CATEGORY_RX = [(c, re.compile(p, re.IGNORECASE)) for c, p in _CATEGORY_RULES]

_KEYWORD_CATEGORY = {
    "public-relations": "Public Relations", "pr-agency": "Public Relations",
    "communication-agency": "Integrated Communications",
    "integrated-communication": "Integrated Communications",
    "media-monitoring": "Media Monitoring",
    "social-media-management": "Social Media",
    "digital-marketing-agency": "Digital Marketing", "digital-outreach": "Digital Marketing",
    "advertising-agency": "Advertising & Media Buying", "media-buying": "Advertising & Media Buying",
    "event-publicity": "Events & Publicity",
    "content-development": "Creative & Content",
    "website-development": "Website & SEO", "seo-services": "Website & SEO",
}


def categorise(title: str, keyword: str = "") -> str:
    """Category from the title, falling back to the search keyword that found it."""
    for cat, rx in _CATEGORY_RX:
        if rx.search(title or ""):
            return cat
    return _KEYWORD_CATEGORY.get(keyword, "Other")


def is_recommended(t) -> bool:
    """Worth the user's attention: scored at or above the threshold, not Skip, and not goods/works/auction."""
    return (t.score is not None and t.score >= MIN_RELEVANCE_SCORE
            and t.recommendation != "Skip" and t.kind not in ("goods", "works", "auction"))
