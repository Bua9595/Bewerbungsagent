import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bewerbungsagent.job_collector import (
    _batch_terms,
    _contains_blocked_terms,
    _extract_jobposting_location,
    _infer_location_from_normalized_text,
    _empty_cache_key,
    _extract_relevant_detail_text,
    _prune_empty_search_cache,
    _split_tasks,
)
from bewerbungsagent.job_adapters_extra import (
    IctCareerAdapter,
    IctJobsAdapter,
    ItJobsAdapter,
    MyItJobAdapter,
    SwissDevJobsAdapter,
    _is_detail_link,
)


class TestJobCollectorUtils(unittest.TestCase):
    def test_batch_terms_passthrough(self) -> None:
        terms = ["a", "b"]
        self.assertEqual(_batch_terms(terms, 1, "OR"), terms)

    def test_batch_terms_grouped(self) -> None:
        terms = ["alpha", "beta", "gamma", "delta"]
        batched = _batch_terms(terms, 2, "OR")
        self.assertEqual(batched, ["alpha OR beta", "gamma OR delta"])

    def test_empty_cache_key_normalized(self) -> None:
        key = _empty_cache_key("JobWinner", "IT Support", "Zuerich HB", 25)
        self.assertEqual(key, "jobwinner|it support|zuerich hb|25")

    def test_prune_empty_cache(self) -> None:
        now = 10000.0
        cache = {
            "keep": now - 30.0,
            "drop": now - 9000.0,
        }
        pruned = _prune_empty_search_cache(cache, 3600.0, now)
        self.assertIn("keep", pruned)
        self.assertNotIn("drop", pruned)

    def test_split_tasks_round_robin(self) -> None:
        tasks = [("a",), ("b",), ("c",), ("d",)]
        chunks = _split_tasks(tasks, 3)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0], [("a",), ("d",)])
        self.assertEqual(chunks[1], [("b",)])
        self.assertEqual(chunks[2], [("c",)])

    def test_ictjobs_detail_link_detection(self) -> None:
        self.assertTrue(_is_detail_link("https://ictjobs.ch/support-it-services/it-supporterin-60-80/"))
        self.assertFalse(_is_detail_link("https://ictjobs.ch/stellen/it-jobs/it-support/"))

    def test_itjobs_detail_link_detection(self) -> None:
        self.assertTrue(_is_detail_link("https://www.itjobs.ch/jobs/200375839-ict-system-administrator-80-100"))
        self.assertFalse(_is_detail_link("https://www.itjobs.ch/jobs/in-switzerland"))

    def test_swissdevjobs_detail_link_detection(self) -> None:
        self.assertTrue(
            _is_detail_link(
                "https://swissdevjobs.ch/jobs/TwinCap-First-AG-Technical-Consultant--Microsoft-365--Azure"
            )
        )
        self.assertFalse(_is_detail_link("https://swissdevjobs.ch/jobs/Support/all"))

    def test_jobscout24_detail_link_detection(self) -> None:
        self.assertTrue(
            _is_detail_link(
                "https://www.jobscout24.ch/de/job/2dc9a470-dcd0-4eae-ab8e-7be3863724b5/"
            )
        )
        self.assertFalse(_is_detail_link("https://www.jobscout24.ch/de/jobs/hauswart/"))

    def test_jobwinner_detail_link_detection(self) -> None:
        self.assertTrue(_is_detail_link("https://www.jobwinner.ch/de/job/2143685974"))
        self.assertFalse(_is_detail_link("https://www.jobwinner.ch/jobs/?q=IT+Support"))

    def test_it_only_adapter_urls(self) -> None:
        ictjobs = IctJobsAdapter()
        itjobs = ItJobsAdapter()
        swissdevjobs = SwissDevJobsAdapter()
        ictcareer = IctCareerAdapter()
        myitjob = MyItJobAdapter()
        self.assertEqual(
            ictjobs.build_url("IT Support", "Zuerich Oerlikon", 25),
            "https://ictjobs.ch/stellen/it-jobs/it-support/",
        )
        self.assertEqual(
            itjobs.build_url("System Administrator", "Zuerich Oerlikon", 25),
            "https://www.itjobs.ch/jobs/system-administration",
        )
        self.assertEqual(
            swissdevjobs.build_url("IT Support", "Zuerich Oerlikon", 25),
            "https://swissdevjobs.ch/jobs/Support/all",
        )
        self.assertEqual(
            ictcareer.build_url("IT Support", "Zuerich Oerlikon", 25),
            "https://ictcareer.ch/en/jobs?q=IT+Support",
        )
        self.assertEqual(
            myitjob.build_url("IT Support", "Zuerich Oerlikon", 25),
            "https://myitjob.ch/",
        )
        self.assertFalse(ictjobs.supports_location)
        self.assertFalse(itjobs.supports_location)
        self.assertFalse(ictcareer.supports_location)
        self.assertFalse(myitjob.supports_location)
        self.assertFalse(swissdevjobs.supports_location)

    def test_extract_relevant_detail_text_prefers_jsonld(self) -> None:
        html = """
        <html><body>
        <header>Franzoesisch erforderlich</header>
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"IT Supporter","description":"Windows 11 und M365 Support"}
        </script>
        <main><p>Diese Stelle ist ideal.</p></main>
        </body></html>
        """
        text = _extract_relevant_detail_text(html)
        self.assertIn("IT Supporter", text)
        self.assertIn("Windows 11 und M365 Support", text)
        self.assertNotIn("Franzoesisch erforderlich", text)

    def test_extract_jobposting_location_reads_jsonld(self) -> None:
        html = """
        <script type="application/ld+json">
        {
          "@type":"JobPosting",
          "title":"IT Supporter",
          "jobLocation":{
            "@type":"Place",
            "address":{
              "@type":"PostalAddress",
              "addressLocality":"Zuerich",
              "addressRegion":"ZH",
              "addressCountry":"CH"
            }
          }
        }
        </script>
        """
        self.assertEqual(
            _extract_jobposting_location(html),
            "Zuerich, ZH, CH",
        )

    def test_infer_location_from_normalized_text_uses_aliases(self) -> None:
        normalized = "m365 workplace engineer standorte zurich wallisellen hybrid"
        self.assertEqual(
            _infer_location_from_normalized_text(normalized),
            "Wallisellen",
        )

    def test_extract_relevant_detail_text_removes_layout_noise(self) -> None:
        html = """
        <html><body>
        <header><p>Italian speaking preferred</p></header>
        <nav><a href="/jobs">Jobs</a></nav>
        <main><h1>IT Support Specialist</h1><p>Windows, Azure, Active Directory</p></main>
        <aside><p>5+ years experience</p></aside>
        <footer><p>French required</p></footer>
        </body></html>
        """
        normalized = text = _extract_relevant_detail_text(html)
        self.assertIn("IT Support Specialist", text)
        self.assertIn("Windows, Azure, Active Directory", text)
        self.assertFalse(
            _contains_blocked_terms(
                " ".join(normalized.lower().split()),
                {"french", "italian", "5+ years experience"},
            )
        )


if __name__ == "__main__":
    unittest.main()
