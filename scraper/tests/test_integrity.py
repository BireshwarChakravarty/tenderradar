"""Publish gate: nothing reaches the website unless it is open, dated, recent and re-verified."""
import unittest
from datetime import date, datetime, timedelta, timezone

import integrity
from integrity import ai_problem, blockers, fix_fields, gate, publish_blockers
from models import Tender
from store import merge

TODAY = date(2026, 10, 11)


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def good(**kw) -> Tender:
    t = Tender(id="td-57900001", ref_no="57900001",
               url="https://www.tenderdetail.com/Indian-Tenders/TenderNotice/57900001/x",
               title="Selection of social media agency for the Department of Information",
               deadline="2026-10-20", deadline_source="stated", published="2026-10-01",
               verified_at=_ts(2), first_seen=_ts(30), last_seen=_ts(2),
               score=8.0, recommendation="Bid", kind="services")
    for k, v in kw.items():
        setattr(t, k, v)
    return t


class GateTests(unittest.TestCase):
    def test_verified_open_tender_is_published(self):
        self.assertEqual(blockers(good(), TODAY), [])

    def test_closing_today_is_still_open(self):
        self.assertEqual(blockers(good(deadline="2026-10-11"), TODAY), [])

    def test_closed_is_held(self):
        self.assertIn("closed", blockers(good(deadline="2026-10-10"), TODAY))

    def test_no_closing_date_is_held(self):
        self.assertIn("no closing date stated", blockers(good(deadline=""), TODAY))

    def test_pre_2026_notice_is_held(self):
        self.assertIn("published before 2026", blockers(good(published="2025-06-27"), TODAY))

    def test_unknown_publish_date_is_allowed(self):
        self.assertEqual(blockers(good(published=""), TODAY), [])

    def test_never_verified_is_held(self):
        self.assertIn("never verified against the source", blockers(good(verified_at=""), TODAY))

    def test_stale_verification_is_held(self):
        reasons = blockers(good(verified_at=_ts(integrity.MAX_VERIFY_AGE_HOURS + 4)), TODAY)
        self.assertTrue(any(r.startswith("not re-verified") for r in reasons))

    def test_far_future_deadline_is_held(self):
        self.assertIn("closing date more than a year away", blockers(good(deadline="2028-01-01"), TODAY))

    def test_link_must_match_reference(self):
        t = good(url="https://www.tenderdetail.com/Indian-Tenders/TenderNotice/11111111/x")
        self.assertIn("source link doesn't match the reference", blockers(t, TODAY))

    def test_gate_splits_and_reports(self):
        store = {"a": good(), "b": good(id="td-2", ref_no="2", deadline="2019-06-15")}
        published, report = gate(store, TODAY)
        self.assertEqual([t.id for t in published], ["td-57900001"])
        self.assertEqual(report["held_back"], 1)


class RelevanceTests(unittest.TestCase):
    def test_relevant_tender_is_published(self):
        self.assertEqual(publish_blockers(good(), TODAY), [])

    def test_partial_fit_is_published(self):
        self.assertEqual(publish_blockers(good(score=4.0, recommendation="Skip"), TODAY), [])

    def test_goods_works_auctions_are_held(self):
        for kind in ("goods", "works", "auction"):
            self.assertIn("not relevant (goods, works or auction)",
                          publish_blockers(good(kind=kind, score=2.0), TODAY))

    def test_low_fit_is_held(self):
        self.assertIn("not relevant (fit under 3)", publish_blockers(good(score=2.5), TODAY))

    def test_unassessed_is_held_but_still_scored(self):
        t = good(score=None)
        self.assertIn("not yet assessed", publish_blockers(t, TODAY))
        self.assertEqual(blockers(t, TODAY), [])     # so main.py still sends it for scoring


class FieldFixTests(unittest.TestCase):
    def test_future_publish_date_cleared(self):
        t = good(published="2027-01-01")
        fix_fields(t, TODAY)
        self.assertEqual(t.published, "")

    def test_emd_above_value_cleared(self):
        t = good(value_inr=50_000, emd_inr=2_00_000)
        fix_fields(t, TODAY)
        self.assertIsNone(t.emd_inr)
        self.assertEqual(t.value_inr, 50_000)


class AITextTests(unittest.TestCase):
    def test_internal_process_is_rejected(self):
        self.assertTrue(ai_problem(good(reason="Strong fit; check the internal bid tracker.")))

    def test_private_names_rejected_unless_the_tender_names_them(self):
        saved = integrity.PRIVATE_TERMS
        integrity.PRIVATE_TERMS = {"RBI", "MoPSW"}
        try:
            self.assertTrue(ai_problem(good(fit="Similar to the MoPSW mandate.")))
            t = good(title="Empanelment of media agencies for an RBI awareness campaign",
                     fit="Media buying for RBI is a weak fit.")
            self.assertEqual(ai_problem(t), "")
        finally:
            integrity.PRIVATE_TERMS = saved

    def test_clean_text_passes(self):
        self.assertEqual(ai_problem(good(fit="Core social media scope.", reason="Worth pursuing.")), "")


class RefreshTests(unittest.TestCase):
    def test_reread_without_a_date_clears_the_old_date(self):
        store = {"td-57900001": good()}
        fresh = good(deadline="", deadline_source="", verified_at=_ts(0))
        merge(store, [fresh])
        self.assertEqual(store["td-57900001"].deadline, "")
        self.assertIn("no closing date stated", blockers(store["td-57900001"], TODAY))


if __name__ == "__main__":
    unittest.main()
