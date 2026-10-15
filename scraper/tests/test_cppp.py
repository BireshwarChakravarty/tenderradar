"""CPPP collector: list parsing, candidate screening, and how its records meet the store and the gate."""
import base64
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import cppp
import store as store_mod
from integrity import blockers
from models import Tender
from relevance import is_candidate
from store import merge, prune

TODAY = date(2026, 10, 15)


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode().rstrip("=")


def _row(key, published, closing, title, ref, tid, org, corr="--"):
    # The shape CPPP served on 15 Oct 2026
    link = (f"https://eprocure.gov.in/cppp/tendersfullview/{base64.b64encode(str(key).encode()).decode()}"
            f"A13h1OGQ2NzAxYTMwZTJh=A13h1{_b64(ref)}A13h1{_b64(tid)}")
    td = '<td style="text-align: left;font-family: tahoma;font-size: 12px">'
    return (f"<tr>{td}1.</td>{td}{published}</td>{td}{closing}</td>{td}{closing}</td>"
            f"{td}<a href=\"{link}\" title=\"External Url\">{title}</a>/{ref}/{tid}</td>"
            f"{td}{org}</td>{td}{corr}</td></tr>")


PAGE = ("<html><body><div>Total Tenders : 29,687</div><table>"
        "<tr><th>Sl.No</th><th>e-Published Date</th><th>Bid Submission Closing Date</th></tr>"
        + _row(14203125, "15-Oct-2026 10:30 AM", "04-Nov-2026 11:30 AM",
               "Hiring of PR agency for publicity of flagship schemes", "DIPR/PR/2026/12",
               "2026_DIPR_930101_1", "Department of Information and Public Relations")
        + _row(14203124, "15-Oct-2026 10:15 AM", "28-Oct-2026 05:00 PM",
               "Special Repair Work for NH-26 &amp; drains", "07/SE NH/2026-27", "2026_MoRTH_930304_1",
               "Ministry of Road Transport and Highways", "Corrigendum 1")
        # Listed by reference number only: nothing to screen, so skipped
        + _row(14203123, "15-Oct-2026 10:10 AM", "22-Oct-2026 03:00 PM", "83/EE(E)/DED-301/2026-27",
               "83/EE(E)/DED-301/2026-27", "172293", "Central Public Works Department (CPWD)")
        + "</table></body></html>")


class ListParsingTests(unittest.TestCase):
    def test_rows_are_parsed(self):
        rows = cppp.parse_list(PAGE)
        self.assertEqual([r.tender_id for r in rows], ["2026_DIPR_930101_1", "2026_MoRTH_930304_1"])
        self.assertEqual([r.key for r in rows], ["14203125", "14203124"])
        r = rows[0]
        self.assertEqual(r.title, "Hiring of PR agency for publicity of flagship schemes")
        self.assertEqual(r.ref, "DIPR/PR/2026/12")
        self.assertEqual((r.published, r.closing), ("2026-10-15T10:30", "2026-11-04T11:30"))
        self.assertEqual(r.organisation, "Department of Information and Public Relations")
        self.assertFalse(r.corrigendum)
        self.assertTrue(rows[1].corrigendum)
        self.assertEqual(rows[1].title, "Special Repair Work for NH-26 & drains")

    def test_total(self):
        self.assertEqual(cppp.total_tenders(PAGE), 29687)

    def test_page_url_encodes_the_page_number(self):
        self.assertEqual(cppp.page_url(1), cppp.LIST)
        url = cppp.page_url(7)
        enc = url.split("?url=", 1)[1].replace("%3D", "=")
        self.assertEqual(base64.b64decode(enc).decode(), f"{cppp.LIST}?page=7")

    def test_layout_change_gives_no_rows(self):
        self.assertEqual(cppp.parse_list("<html><table><tr><td>Maintenance</td></tr></table></html>"), [])

    def test_only_candidates_are_kept(self):
        res = cppp.CrawlResult()
        with mock.patch("cppp.iso_now", return_value="2026-10-15T05:00:00Z"):
            cppp._collect(res, cppp.parse_list(PAGE), "2026-10-15", "2026-10-15T05:00:00Z")
        self.assertEqual([t.id for t in res.tenders], ["cppp-14203125"])
        t = res.tenders[0]
        self.assertEqual((t.source, t.ref_no, t.published, t.deadline, t.deadline_source),
                         ("CPPP", "2026_DIPR_930101_1", "2026-10-15", "2026-11-04", "stated"))
        self.assertEqual(res.seen_rows, 2)
        self.assertEqual(res.newest_published, "2026-10-15T10:30")

    def test_closed_rows_are_not_collected(self):
        res = cppp.CrawlResult()
        cppp._collect(res, cppp.parse_list(PAGE), "2026-11-10", "2026-11-10T05:00:00Z")
        self.assertEqual(res.tenders, [])
        self.assertEqual(res.closed_ids, {"cppp-14203125"})


class CandidateTests(unittest.TestCase):
    def test_communications_work_is_a_candidate(self):
        for title in ["Hiring of PR agency for Ministry", "Selection of agency for social media management",
                      "Design and development of website for the institute",
                      "Engagement of agency for IEC and BCC activities", "Production of documentary films",
                      "Event management for the investors summit", "Media monitoring services"]:
            self.assertTrue(is_candidate(title), title)

    def test_everything_else_is_not(self):
        for title in ["Term Contract for Repairing roads", "Supply of communication equipment",
                      "Construction of conference hall", "Procurement of laboratory chemicals",
                      "Auction of scrap vehicles for publicity vans", "1-Long travelling wheel press fitted with fire axle",
                      "FLEET GRAPHICS FILM", "C/O Magazine building at BSF campus",
                      "Transformer oil for locomotives as per IEC 60296", "Spares kit, Make/Brand-Schunk",
                      "Provision of conference system at RDSO office"]:
            self.assertFalse(is_candidate(title), title)


def _cppp(key="14203125", tid="2026_DIPR_930101_1", **kw) -> Tender:
    t = Tender(id=f"cppp-{key}", ref_no=tid, url=cppp.LOOKUP, source="CPPP", portal="CPPP",
               title="Hiring of PR agency for publicity of flagship schemes", deadline="2026-11-04",
               deadline_source="stated", published="2026-10-15", verified_at=_ts(1),
               first_seen=_ts(1), last_seen=_ts(1), score=8.0, recommendation="Bid", kind="services")
    for k, v in kw.items():
        setattr(t, k, v)
    return t


class GateTests(unittest.TestCase):
    def test_cppp_tender_passes_the_source_checks(self):
        self.assertEqual(blockers(_cppp(), TODAY), [])

    def test_cppp_id_must_match_reference(self):
        self.assertIn("source link doesn't match the reference", blockers(_cppp(id="cppp-x1"), TODAY))
        self.assertIn("source link doesn't match the reference", blockers(_cppp(ref_no=""), TODAY))
        self.assertIn("source link doesn't match the reference",
                      blockers(_cppp(url="https://example.com/x"), TODAY))


class StoreTests(unittest.TestCase):
    def _legacy(self):
        return Tender(id="td-1", ref_no="1", url="https://www.tenderdetail.com/Indian-Tenders/TenderNotice/1/a",
                      title="Hiring of PR agency for publicity of flagship schemes", deadline="2026-11-04",
                      first_seen=_ts(200), last_seen=_ts(100), verified_at=_ts(100), source="TenderDetail",
                      score=7.5, recommendation="Bid", kind="services", headline="PR agency for schemes",
                      value_inr=5_00_000)

    def test_live_source_replaces_legacy_duplicate_and_keeps_its_assessment(self):
        store = {"td-1": self._legacy()}
        stats = merge(store, [_cppp(score=None, recommendation="", kind="")])
        self.assertEqual(stats["new"], 1)          # not rejected as a duplicate of the legacy record
        prune(store)
        self.assertEqual(list(store), ["cppp-14203125"])
        kept = store["cppp-14203125"]
        self.assertEqual((kept.score, kept.headline, kept.value_inr), (7.5, "PR agency for schemes", 5_00_000))
        self.assertEqual(store_mod.replaced, {"td-1": "cppp-14203125"})


class AuditParserTests(unittest.TestCase):
    def test_second_parser_agrees_with_the_collector(self):
        import verify_dates
        b = verify_dates.text_rows(PAGE)
        for r in cppp.parse_list(PAGE):
            self.assertEqual(b[r.key], (r.published, r.closing, r.tender_id))


class PlanTests(unittest.TestCase):
    def test_slices_cover_the_list_with_overlap_and_wrap(self):
        p = cppp.plan(last_page=3000, newest_end=20, cursor=0, chunk=1000, full=False)
        self.assertEqual((p[0], p[-1]), (21, 1020))
        p = cppp.plan(3000, 20, cursor=1021, chunk=1000, full=False)
        self.assertEqual((p[0], p[-1]), (1021 - cppp.OVERLAP_PAGES, 2020 - cppp.OVERLAP_PAGES))
        p = cppp.plan(3000, 20, cursor=3100, chunk=1000, full=False)
        self.assertEqual(p[0], 21)              # past the end: start again from the top

    def test_full_reads_everything_after_the_newest(self):
        p = cppp.plan(3000, 20, cursor=500, chunk=1000, full=True)
        self.assertEqual((p[0], p[-1], len(p)), (21, 3000, 2980))


if __name__ == "__main__":
    unittest.main()
