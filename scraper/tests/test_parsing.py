"""Run from the repo root:  python -m unittest discover -s scraper/tests -t scraper"""
import unittest
from datetime import date

from dates import days_until, parse_date, plausible
from page_parser import detect_portal, parse_detail, parse_money, split_location, to_inr

TODAY = date(2026, 10, 10)

# Text of a detail page as rendered since July 2026 (document.body.innerText)
NEW_LAYOUT = """Indian Tenders
 AI Search
Sales : +91-777 804 8217
Home  ›
Indian Tenders  › Tender #57300001
Media and Publicity
State Government
Closing in 6 days
TDR #57300001
Tender For Hiring Of Public Relations Agency For Department Of Information And Public Relations
Issued by Department Of Information · Lucknow, Uttar Pradesh
Tender Value ₹ 45.50 Lakh
EMD ₹ 91,000
"""

# Text of a detail page in the layout used until June 2026
OLD_LAYOUT = """Indian Tenders
Home  ›  Indian Tenders  › Tender Notice : 55145448
Tender For Providing Outdoor Media Services, Jaipur-Rajasthan
TDR : 55145448
Tender Notice
5 Days Left
Click Here To View Tendering Authority.
 Jaipur , Rajasthan
Tender Brief : Corrigendum : Tender For Providing Outdoor Media Services For All Rajasthan
Document Fees
Refer document
EMD
₹ 2,50,000 /-
Tender Value
₹ 1.25 Crore
Submission Date
15-10-2026
Published Date : 01/10/2026
"""


# Real TenderDetail pages, October 2026 (from the deadline verification run).
# Expired tenders still say "Closing in 0 days"; the header box has the date.
EXPIRED_2019 = """Home  ›
Indian Tenders  › Tender #20524678
Road Transport and Highways
Government Departments
Closing in 0 days
TDR #20524678
Paper and Printing Services, Paper Materials, Paper Products, Stationery
Share
Set Alert
TENDER VALUE
Ref. Documents
Estimated cost
BID SUBMISSION
15 Jun 2019
0 days left
EMD
10000
"""

EXPIRED_2024 = """Closing in 0 days
TDR #45640369
Tender For Request For Proposal For Selection Of Agency For Mass Media Network Platform
TENDER VALUE
21.16 Crore
BID SUBMISSION
29 Oct 2024
0 days left
Corrigendum
Sr No Corrigendum Date Corrigendum Type New Submission Date
1
17-Oct-2024
Final RFP After Prebid
TENDER VALUE 21.16 Crore
LAST DATE
29-10-2024
KEY DATES
PUBLISH DATE
10 Oct 2024
SUBMISSION DATE
29 Oct 2024
"""

# Live tender with a corrigendum table whose first date is the corrigendum's own
LIVE_WITH_CORRIGENDUM = """Closing in 1 days
TDR #57529822
Bids Are invited for Equipment For Establishment Of Police Research Institute
BID SUBMISSION
12 Oct 2026
1 days left
Corrigendum
Sr No Corrigendum Date Corrigendum Type New Submission Date
1
03-Oct-2026
12-Oct-2026
LAST DATE
12-10-2026
KEY DATES
PUBLISH DATE
19 Sep 2026
"""


class DateTests(unittest.TestCase):
    def test_formats_are_day_first(self):
        self.assertEqual(parse_date("15-10-2026"), date(2026, 10, 15))
        self.assertEqual(parse_date("05/03/26"), date(2026, 3, 5))
        self.assertEqual(parse_date("14 Oct 2026"), date(2026, 10, 14))
        self.assertEqual(parse_date("14-Oct-2026 05:00 PM"), date(2026, 10, 14))
        self.assertEqual(parse_date("October 14, 2026"), date(2026, 10, 14))
        self.assertEqual(parse_date("2026-10-14"), date(2026, 10, 14))
        self.assertIsNone(parse_date("Refer document"))
        self.assertIsNone(parse_date("31-02-2026"))

    def test_implausible_dates_rejected(self):
        self.assertFalse(plausible(date(2018, 3, 7), TODAY))
        self.assertFalse(plausible(date(2031, 1, 1), TODAY))
        self.assertTrue(plausible(date(2026, 11, 1), TODAY))

    def test_open_through_closing_day(self):
        self.assertEqual(days_until("2026-10-10", TODAY), 0)
        self.assertEqual(days_until("2026-10-09", TODAY), -1)
        self.assertIsNone(days_until("", TODAY))


class PageParserTests(unittest.TestCase):
    def test_new_layout(self):
        p = parse_detail(NEW_LAYOUT, TODAY)
        self.assertEqual(p["title"], "Tender For Hiring Of Public Relations Agency For "
                                     "Department Of Information And Public Relations")
        self.assertEqual(p["deadline"], "2026-10-16")           # from "Closing in 6 days"
        self.assertEqual(p["authority"], "Department Of Information")
        self.assertEqual(p["location"], "Lucknow, Uttar Pradesh")
        self.assertEqual(p["state"], "Uttar Pradesh")
        self.assertEqual(p["value_inr"], 4_550_000)
        self.assertEqual(p["emd_inr"], 91_000)
        self.assertFalse(p["closed"])

    def test_old_layout(self):
        p = parse_detail(OLD_LAYOUT, TODAY)
        self.assertEqual(p["title"], "Tender For Providing Outdoor Media Services For All Rajasthan")
        self.assertEqual(p["deadline"], "2026-10-15")           # labelled date wins over countdown
        self.assertEqual(p["published"], "2026-10-01")
        self.assertEqual(p["state"], "Rajasthan")
        self.assertEqual(p["value_inr"], 12_500_000)
        self.assertEqual(p["emd_inr"], 250_000)

    def test_past_labelled_date_loses_to_live_countdown(self):
        # Seen on the July 2026 layout: the label picked up an unrelated, past date
        text = NEW_LAYOUT + "Due Date 08-09-2026\n"
        self.assertEqual(parse_detail(text, TODAY)["deadline"], "2026-10-16")

    def test_expired_page_is_closed(self):
        text = OLD_LAYOUT.replace("5 Days Left", "Expired").replace("15-10-2026", "01-10-2026")
        p = parse_detail(text, TODAY)
        self.assertTrue(p["closed"])
        self.assertEqual(p["deadline"], "2026-10-01")

    def test_no_deadline_is_left_empty(self):
        text = NEW_LAYOUT.replace("Closing in 6 days\n", "")
        self.assertEqual(parse_detail(text, TODAY)["deadline"], "")

    def test_expired_tender_with_zero_countdown_is_closed(self):
        # "Closing in 0 days" on a 2019 tender used to read as "closes today"
        today = date(2026, 10, 11)
        p = parse_detail(EXPIRED_2019, today)
        self.assertEqual(p["deadline"], "2019-06-15")
        self.assertTrue(p["closed"])
        p = parse_detail(EXPIRED_2024, today)
        self.assertEqual(p["deadline"], "2024-10-29")
        self.assertTrue(p["closed"])

    def test_header_date_beats_corrigendum_table(self):
        p = parse_detail(LIVE_WITH_CORRIGENDUM, date(2026, 10, 11))
        self.assertEqual(p["deadline"], "2026-10-12")
        self.assertEqual(p["published"], "2026-09-19")
        self.assertFalse(p["closed"])

    def test_zero_countdown_without_a_date_is_unknown(self):
        text = NEW_LAYOUT.replace("Closing in 6 days", "Closing in 0 days")
        p = parse_detail(text, TODAY)
        self.assertEqual(p["deadline"], "")
        self.assertFalse(p["closed"])

    def test_closes_today_when_the_page_says_today(self):
        text = EXPIRED_2019.replace("15 Jun 2019", "10 Oct 2026")
        p = parse_detail(text, TODAY)
        self.assertEqual(p["deadline"], "2026-10-10")
        self.assertFalse(p["closed"])

    def test_future_published_date_is_dropped(self):
        text = LIVE_WITH_CORRIGENDUM.replace("19 Sep 2026", "19 Sep 2027")
        self.assertEqual(parse_detail(text, date(2026, 10, 11))["published"], "")

    def test_gem_not_matched_inside_management(self):
        self.assertEqual(detect_portal("TENDER FOR SOCIAL MEDIA MANAGEMENT AGENCY"), "")
        self.assertEqual(parse_detail(NEW_LAYOUT + "Bid No: GEM/2026/B/123\n", TODAY)["portal"], "GeM")

    def test_money(self):
        self.assertEqual(to_inr("2.5", "Crore"), 25_000_000)
        self.assertEqual(to_inr("12,34,567", None), 1_234_567)
        self.assertIsNone(to_inr("24", None))                      # "Apr. 24" style mis-reads
        self.assertEqual(parse_money("Tender Value\nRefer document\nEMD\nRefer document"),
                         {"value_inr": None, "emd_inr": None})

    def test_location(self):
        self.assertEqual(split_location(" Jaipur , Rajasthan"), ("Jaipur, Rajasthan", "Rajasthan"))
        self.assertEqual(split_location("New Delhi"), ("New Delhi", "Delhi"))
        self.assertEqual(split_location("jalandhar, Punjab"), ("Jalandhar, Punjab", "Punjab"))
        self.assertEqual(split_location("Delhi, Delhi"), ("Delhi", "Delhi"))
        self.assertEqual(split_location("multi state, Multi State"), ("Multi State", ""))


if __name__ == "__main__":
    unittest.main()
