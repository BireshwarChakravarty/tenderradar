"""Run from the repo root:  python -m unittest discover -s scraper/tests -t scraper"""
import unittest
from datetime import timedelta

from dates import today_ist
from models import Tender
from relevance import categorise, exclusion_reason, is_recommended
from page_parser import is_sector_label, parse_where
from store import dupe_key, merge, prune


def _t(ref="1", title="Selection of PR agency for state tourism", deadline_in=10, **kw):
    dl = (today_ist() + timedelta(days=deadline_in)).isoformat() if deadline_in is not None else ""
    return Tender(id=f"td-{ref}", ref_no=ref, url=f"https://x/TenderNotice/{ref}/a", title=title,
                  deadline=dl, first_seen="2026-10-01T00:00:00Z", last_seen="2026-10-01T00:00:00Z", **kw)


class RelevanceTests(unittest.TestCase):
    def test_excludes_ad_space_auctions_and_works(self):
        for title in [
            "Auction For Advertisement Through New Hoarding Of Tentative Dimension 10X10",
            "Tender For Awarding Advertisements Rights By Setting Up Advertising Media At Bus Stations",
            "Bids Are Invited For Custom Bid For Services - Geo-Technical Investigation At Vadodara",
            "Tender for Construction of Skywalk",
            "Pre-Bid EOI for Selection of Channel Partner/Authorized Distributor for IP-MPLS network",
        ]:
            self.assertTrue(exclusion_reason(title), title)

    def test_keeps_agency_work_that_mentions_hoardings(self):
        for title in [
            "Tender For Conducting IEC Activities Of Municipal Corporation, Advertisement On Hoardings",
            "Request For Proposal (RFP) For Appointment Of Public Relations (PR) Agency",
            "Tender For Engagement Of Social Media Management Agencies",
        ]:
            self.assertEqual(exclusion_reason(title), "", title)

    def test_categories(self):
        self.assertEqual(categorise("Selection of agency for media monitoring and analysis"), "Media Monitoring")
        self.assertEqual(categorise("Social Media Management for Ministry"), "Social Media")
        self.assertEqual(categorise("Something vague", "seo-services"), "Website & SEO")

    def test_recommended(self):
        self.assertTrue(is_recommended(_t(score=7.5, recommendation="Bid", kind="services")))
        self.assertFalse(is_recommended(_t(score=7.5, recommendation="Skip", kind="services")))
        self.assertFalse(is_recommended(_t(score=8.0, recommendation="Bid", kind="auction")))
        self.assertFalse(is_recommended(_t(score=None)))


class StoreTests(unittest.TestCase):
    def test_merge_rules(self):
        store = {}
        stats = merge(store, [
            _t("1"),
            _t("2", deadline_in=-1),                                          # closed when found
            _t("3", title="Auction For Display Of Advertisement On 20 Water Tanks"),
            _t("4", deadline_in=None),                                        # no deadline: kept, not invented
        ])
        self.assertEqual(sorted(store), ["td-1", "td-4"])
        self.assertEqual(store["td-4"].deadline, "")
        self.assertEqual((stats["new"], stats["closed_on_arrival"], stats["excluded"]), (2, 1, 1))

    def test_merge_refreshes_extended_deadline_and_keeps_score(self):
        store = {"td-1": _t("1", deadline_in=1, score=8.0, recommendation="Bid")}
        merge(store, [_t("1", deadline_in=12)])
        self.assertEqual(store["td-1"].deadline, (today_ist() + timedelta(days=12)).isoformat())
        self.assertEqual(store["td-1"].score, 8.0)

    def test_corrigenda_of_the_same_tender_are_merged(self):
        store = {}
        stats = merge(store, [
            _t("1", title="Corrigendum Tender For Appointment Of Public Relations (Pr) And Social Media Agency"),
            _t("2", title="Corrigendum Appointment Of Public Relations (Pr) And Social Media Agency"),
            _t("3", title="Corrigendum Appointment Of Public Relations (Pr) And Social Media Agency", deadline_in=20),
        ])
        self.assertEqual(sorted(store), ["td-1", "td-3"])          # different deadline = different tender
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["rejected_ids"], ["td-2"])

    def test_prune_collapses_stored_duplicates(self):
        a, b = _t("1", title="Tender For PR Agency For Tourism"), _t("2", title="Corrigendum PR Agency For Tourism")
        b.first_seen = "2026-10-02T00:00:00Z"
        store = {a.id: a, b.id: b}
        self.assertEqual(dupe_key(a), dupe_key(b))
        prune(store)
        self.assertEqual(list(store), ["td-1"])

    def test_sector_labels_are_not_buyers(self):
        self.assertTrue(is_sector_label("Government Departments"))
        self.assertTrue(is_sector_label("Statutory Bodies & Commissions/Committees"))
        self.assertTrue(is_sector_label("Boards / Undertakings / PSU"))
        self.assertFalse(is_sector_label("Bareilly Development Authority"))
        self.assertEqual(parse_where("Issued by Government Departments · Patna, Bihar\n")["authority"], "")
        self.assertEqual(parse_where("Issued by Health Department · Patna, Bihar\n")["authority"], "Health Department")

    def test_prune(self):
        store = {t.id: t for t in [_t("1", deadline_in=-5), _t("2", deadline_in=-60),
                                   _t("3", deadline_in=None)]}
        store["td-3"].last_seen = "2020-01-01T00:00:00Z"
        self.assertEqual(prune(store), 2)
        self.assertEqual(list(store), ["td-1"])


if __name__ == "__main__":
    unittest.main()
