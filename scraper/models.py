"""
TenderRadar: the tender record.

This is the exact shape written to docs/data/tenders.json and read by the
dashboard, alerts and digest. Dates are IST calendar dates ("YYYY-MM-DD")
or "" when the source doesn't state one; money is whole rupees or None.
"""
import re
from dataclasses import asdict, dataclass, fields

SCHEMA_VERSION = 2

_DASH = re.compile(r"\s*[\u2014\u2015]\s*")


def plain(s: str) -> str:
    """House style: no em dashes in anything we show. "A \u2014 B" becomes "A, B"."""
    return _DASH.sub(", ", s or "").strip(", ")


@dataclass
class Tender:
    id:             str                         # "td-<TenderDetail number>", stable across runs
    ref_no:         str                         # TenderDetail number (TDR)
    url:            str
    title:          str                         # as published
    source:         str = "TenderDetail"
    portal:         str = ""                    # "GeM", "CPPP" or "" when not stated
    authority:      str = ""                    # issuing organisation
    location:       str = ""                    # "Gorakhpur, Uttar Pradesh"
    state:          str = ""                    # "Uttar Pradesh"
    category:       str = "Other"
    value_inr:      float | None = None         # estimated tender value
    emd_inr:        float | None = None         # earnest money deposit
    published:      str = ""
    deadline:       str = ""                    # last date for bid submission
    first_seen:     str = ""                    # UTC timestamps
    last_seen:      str = ""
    # AI assessment, empty until scored
    headline:       str = ""                    # short, clean title
    score:          float | None = None         # 1–10 fit for the company profile
    recommendation: str = ""                    # "Bid" | "Watch" | "Skip"
    kind:           str = ""                    # "services" | "goods" | "works" | "auction" | "other"
    fit:            str = ""
    reason:         str = ""
    scored_at:      str = ""
    scoring_version: int = 0                   # bumped when the scoring prompt changes; older scores are redone

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Tender":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


def tender_id(ref_no: str) -> str:
    return f"td-{ref_no}"
