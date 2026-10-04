"""Task 2 collector/report tests.

Real DNS is intentionally outside the unit tests: answers change by time and
network.  The tests replace only that external boundary with deterministic
answers and exercise the real collection and analysis code.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dns.exception

import task2_steering as steering


def answer(status, addresses=None, error=None):
    item = {"server": None, "status": status, "addresses": addresses or []}
    if error:
        item["error"] = error
    return item


def site_result(final_name, addresses_by_resolver, status="ok"):
    chain = [final_name] if final_name.startswith("www.") else ["origin.test", final_name]
    return {
        "cname": {
            "status": status,
            "chain": chain,
            "final_hostname": final_name,
            "hops": len(chain) - 1,
        },
        "answers": addresses_by_resolver,
    }


def steering_fixture():
    campus = {
        "run_id": "campus-1", "network": "campus", "collected_at": "2026-09-15T01:00:00Z",
        "resolvers": {
            "system": {"server": None, "nameservers": ["192.0.2.53"]},
            "google": {"server": "8.8.8.8", "nameservers": ["8.8.8.8"]},
            "quad9": {"server": "9.9.9.9", "nameservers": ["9.9.9.9"]},
        }, "sites": {
            "www.microsoft.com": site_result("edge.akamaiedge.net", {
                "system": answer("ok", ["192.0.2.1"]),
                "google": answer("error", error="blocked"),
                "quad9": answer("ok", ["192.0.2.1"]),
            }),
            "www.netflix.com": site_result("www.netflix.com", {
                "system": answer("ok", ["192.0.2.3"]),
                "google": answer("ok", ["192.0.2.4"]),
                "quad9": answer("error", error="blocked"),
            }),
            "www.adobe.com": site_result("edge.akamaiedge.net", {
                "system": answer("ok", ["192.0.2.5"]),
                "google": answer("error", error="blocked"),
                "quad9": answer("error", error="blocked"),
            }),
            "www.wikipedia.org": site_result("dyna.wikimedia.org", {
                "system": answer("ok", ["192.0.2.7"]),
                "google": answer("ok", ["192.0.2.7"]),
                "quad9": answer("ok", ["192.0.2.7"]),
            }),
        },
    }
    hotspot = {
        "run_id": "hotspot-1", "network": "phone-hotspot", "collected_at": "2026-09-15T02:00:00Z",
        "resolvers": {
            "system": {"server": None, "nameservers": ["198.51.100.53"]},
            "google": {"server": "8.8.8.8", "nameservers": ["8.8.8.8"]},
            "quad9": {"server": "9.9.9.9", "nameservers": ["9.9.9.9"]},
        }, "sites": {
            "www.microsoft.com": site_result("edge.akamaiedge.net", {
                "system": answer("ok", ["192.0.2.2"]),
                "google": answer("ok", ["192.0.2.2"]),
                "quad9": answer("error", error="blocked"),
            }),
            "www.netflix.com": site_result("www.netflix.com", {
                "system": answer("error", error="blocked"),
                "google": answer("ok", ["192.0.2.4"]),
                "quad9": answer("ok", ["192.0.2.4"]),
            }),
            "www.adobe.com": site_result("edge.akamaiedge.net", {
                "system": answer("error", error="blocked"),
                "google": answer("ok", ["192.0.2.6"]),
                "quad9": answer("error", error="blocked"),
            }),
            "www.wikipedia.org": site_result("dyna.wikimedia.org", {
                "system": answer("ok", ["192.0.2.7"]),
                "google": answer("ok", ["192.0.2.7"]),
                "quad9": answer("ok", ["192.0.2.7"]),
            }),
        },
    }
    return {"schema_version": 1, "sites": list(steering.SITES), "runs": [campus, hotspot]}


class NormalizationTests(unittest.TestCase):
    def test_addresses_are_unique_valid_and_sorted_numerically(self):
        """Catch duplicate, malformed, or lexicographically sorted A records."""
        normalize = getattr(steering, "normalize_addresses", None)
        self.assertTrue(callable(normalize), "normalize_addresses() is missing")
        self.assertEqual(
            normalize(
                ["10.0.0.10", "not-an-address", "10.0.0.2", "10.0.0.2"]
            ),
            ["10.0.0.2", "10.0.0.10"],
        )


class CnameChainTests(unittest.TestCase):
    @staticmethod
    def _chain_function(testcase):
        follow = getattr(steering, "follow_cname_chain", None)
        testcase.assertTrue(callable(follow), "follow_cname_chain() is missing")
        return follow

    def test_chain_stops_on_valid_empty_cname_answer(self):
        """Catch treating a terminal name as an error or omitting a hop."""
        replies = {
            "www.example.com": {"status": "ok", "records": ["edge.example.net."]},
            "edge.example.net": {"status": "ok", "records": []},
        }

        def fake_query(name, rtype="A", server=None):
            self.assertEqual(rtype, "CNAME")
            return replies[name]

        result = self._chain_function(self)("www.example.com", query_fn=fake_query)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["chain"], ["www.example.com", "edge.example.net"])
        self.assertEqual(result["final_hostname"], "edge.example.net")
        self.assertEqual(result["hops"], 1)

    def test_chain_reports_a_loop_instead_of_hanging(self):
        """Catch following a repeated target forever."""
        replies = {
            "a.example": {"status": "ok", "records": ["b.example."]},
            "b.example": {"status": "ok", "records": ["a.example."]},
        }

        result = self._chain_function(self)(
            "a.example", query_fn=lambda name, rtype="A", server=None: replies[name]
        )

        self.assertEqual(result["status"], "loop")
        self.assertEqual(result["chain"], ["a.example", "b.example", "a.example"])

    def test_chain_reports_transport_failure_distinctly(self):
        """Catch confusing an unreachable resolver with 'no CNAME'."""
        result = self._chain_function(self)(
            "down.example",
            query_fn=lambda *args, **kwargs: {
                "status": "error",
                "records": [],
                "error": "timeout",
            },
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "timeout")

    def test_chain_stops_at_the_configured_depth(self):
        """Catch an unexpectedly long or malicious chain escaping the cap."""
        def endless_chain(name, rtype="A", server=None):
            number = int(name.removeprefix("n"))
            return {"status": "ok", "records": [f"n{number + 1}."]}

        result = self._chain_function(self)(
            "n0", query_fn=endless_chain, max_depth=2
        )

        self.assertEqual(result["status"], "depth_limit")
        self.assertEqual(result["chain"], ["n0", "n1", "n2"])


class DnsTransportTests(unittest.TestCase):
    @staticmethod
    def _query_function(testcase):
        query = getattr(steering, "query_dns", None)
        testcase.assertTrue(callable(query), "query_dns() is missing")
        return query

    def test_no_data_is_a_successful_empty_answer(self):
        """Catch a valid no-CNAME response being stored as unreachable."""
        query = self._query_function(self)
        fake_resolver = mock.Mock()
        fake_resolver.resolve.return_value = []
        with mock.patch.object(steering.dns.resolver, "Resolver", return_value=fake_resolver):
            result = query("plain.example", "CNAME")

        self.assertEqual(result, {"status": "ok", "records": []})

    def test_timeout_is_preserved_as_an_error(self):
        """Catch an unreachable resolver becoming an empty address set."""
        query = self._query_function(self)
        fake_resolver = mock.Mock()
        fake_resolver.resolve.side_effect = dns.exception.Timeout(timeout=1)
        with mock.patch.object(steering.dns.resolver, "Resolver", return_value=fake_resolver):
            result = query("down.example", "A", "203.0.113.53")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["records"], [])
        self.assertIn("timeout", result["error"].lower())


class CollectionTests(unittest.TestCase):
    def test_collect_appends_runs_and_preserves_answer_status(self):
        """Catch a second measurement overwriting the first network evidence."""
        collect = getattr(steering, "collect", None)
        self.assertTrue(callable(collect), "collect() is missing")

        def fake_query(name, rtype="A", server=None):
            if rtype == "CNAME":
                return {"status": "ok", "records": []}
            if server == "8.8.8.8":
                return {"status": "error", "records": [], "error": "blocked"}
            if server == "9.9.9.9":
                return {"status": "ok", "records": []}
            return {"status": "ok", "records": ["192.0.2.10", "192.0.2.10"]}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chains.json"
            try:
                first = collect(
                    "campus",
                    output_path=path,
                    query_fn=fake_query,
                    system_nameservers_fn=lambda: ["192.0.2.53"],
                )
                second = collect(
                    "campus",
                    output_path=path,
                    query_fn=fake_query,
                    system_nameservers_fn=lambda: ["192.0.2.53"],
                )
            except (TypeError, NotImplementedError) as exc:
                self.fail(f"collect() API is not implemented: {exc}")
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(saved["schema_version"], 1)
        self.assertEqual(len(saved["runs"]), 2)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual([run["network"] for run in saved["runs"]], ["campus", "campus"])
        self.assertEqual(
            saved["runs"][0]["resolvers"]["system"]["nameservers"],
            ["192.0.2.53"],
        )
        answers = saved["runs"][0]["sites"]["www.microsoft.com"]["answers"]
        self.assertEqual(answers["system"]["addresses"], ["192.0.2.10"])
        self.assertEqual(answers["google"]["status"], "error")
        self.assertEqual(answers["quad9"], {
            "server": "9.9.9.9", "status": "ok", "addresses": []
        })

    def test_collect_cli_accepts_an_explicit_network_label(self):
        """Catch collecting evidence without the network identity required by B3."""
        build_parser = getattr(steering, "build_parser", None)
        self.assertTrue(callable(build_parser), "build_parser() is missing")

        args = build_parser().parse_args(["--collect", "--network", "campus"])

        self.assertTrue(args.collect)
        self.assertEqual(args.network, "campus")


class SteeringAnalysisTests(unittest.TestCase):
    def test_errors_do_not_create_false_steering_or_denominator_entries(self):
        """Catch failed lookups being compared as if they were address sets."""
        analyze = getattr(steering, "analyze_steering", None)
        self.assertTrue(callable(analyze), "analyze_steering() is missing")

        result = analyze(steering_fixture())

        self.assertEqual(result["cdn_candidates"], 3)
        self.assertEqual(result["resolver_comparable"], 2)
        self.assertEqual(result["resolver_changed"], 1)
        # Only Google is a verified identical resolver across both runs here.
        # The two "system" labels name different endpoints and are excluded.
        self.assertEqual(result["network_comparable"], 1)
        self.assertEqual(result["network_changed"], 0)
        # A broader B5 observation may still compare the network environments,
        # as long as the report does not call this the same resolver.
        self.assertEqual(result["broad_network_comparable"], 2)
        self.assertEqual(result["broad_network_changed"], 1)
        self.assertEqual(result["combined_comparable"], 2)
        self.assertEqual(result["combined_changed"], 2)
        self.assertNotIn("www.adobe.com", result["combined_comparable_sites"])

    def test_latest_successful_chain_survives_a_later_network_timeout(self):
        """Catch a transient CNAME error erasing valid earlier CDN evidence."""
        data = steering_fixture()
        hotspot_cname = data["runs"][1]["sites"]["www.microsoft.com"]["cname"]
        hotspot_cname.clear()
        hotspot_cname.update({
            "status": "error",
            "chain": ["www.microsoft.com"],
            "final_hostname": "www.microsoft.com",
            "hops": 0,
            "error": "timeout",
        })
        raw_before = copy.deepcopy(data)

        result = steering.analyze_steering(data)
        microsoft = result["classifications"]["www.microsoft.com"]

        self.assertEqual(microsoft["third_party"], "예")
        self.assertTrue(microsoft["cdn_candidate"])
        self.assertEqual(microsoft["source_network"], "campus")
        self.assertEqual(microsoft["source_run_id"], "campus-1")
        self.assertIn("www.microsoft.com", result["combined_comparable_sites"])
        self.assertEqual(data, raw_before, "analysis must preserve the raw error run")


class ClassificationTests(unittest.TestCase):
    def test_documented_netlify_cdn_suffix_is_a_third_party_candidate(self):
        """Catch Stanford's observed Netlify CDN chain being discarded as unknown."""
        result = steering.classify_site("www.stanford.edu", {
            "status": "ok",
            "chain": ["www.stanford.edu", "stanford.netlifyglobalcdn.com"],
            "final_hostname": "stanford.netlifyglobalcdn.com",
            "hops": 1,
        })

        self.assertEqual(result["third_party"], "예")
        self.assertTrue(result["cdn_candidate"])
        self.assertIn("Netlify", result["evidence"])
        self.assertIn(
            "https://answers.netlify.com/t/how-can-i-change-which-netlify-site-my-hostname-is-pointing-to/3259",
            result["evidence"],
        )


class ReportTests(unittest.TestCase):
    def test_report_uses_observed_data_and_includes_manual_capture_analysis(self):
        """Catch fabricated rows or overwriting the human packet observations."""
        make_report = getattr(steering, "report", None)
        self.assertTrue(callable(make_report), "report() is missing")

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            input_path = folder / "chains.json"
            output_path = folder / "report.md"
            capture_path = folder / "capture-analysis.md"
            input_path.write_text(
                json.dumps(steering_fixture(), ensure_ascii=False), encoding="utf-8"
            )
            capture_text = "위임 패킷 7, 정답 패킷 11, 최대 응답 512 bytes."
            capture_path.write_text(capture_text, encoding="utf-8")

            try:
                make_report(
                    input_path=input_path,
                    output_path=output_path,
                    capture_analysis_path=capture_path,
                )
            except (TypeError, NotImplementedError) as exc:
                self.fail(f"report() API is not implemented: {exc}")
            report_text = output_path.read_text(encoding="utf-8")

        for site in steering.SITES:
            self.assertIn(f"| {site} |", report_text)
        self.assertIn("2/2", report_text)
        self.assertIn("campus", report_text)
        self.assertIn("phone-hotspot", report_text)
        self.assertIn("www.wikipedia.org", report_text)
        self.assertIn("dyna.wikimedia.org", report_text)
        self.assertIn("https://wikimediafoundation.org/what-we-do/wikimedia-projects/", report_text)
        self.assertIn("CNAME chain은 system resolver", report_text)
        self.assertIn("capture-analysis.md", report_text)
        self.assertIn(capture_text, report_text)

    def test_report_attributes_older_chain_and_lists_newer_error(self):
        """Catch an older successful chain being presented as hotspot evidence."""
        data = steering_fixture()
        data["runs"][1]["sites"]["www.microsoft.com"]["cname"] = {
            "status": "error",
            "chain": ["www.microsoft.com"],
            "final_hostname": "www.microsoft.com",
            "hops": 0,
            "error": "timeout",
        }

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            input_path = folder / "chains.json"
            output_path = folder / "report.md"
            input_path.write_text(json.dumps(data), encoding="utf-8")
            steering.report(input_path=input_path, output_path=output_path)
            report_text = output_path.read_text(encoding="utf-8")

        microsoft_row = next(
            line for line in report_text.splitlines()
            if line.startswith("| www.microsoft.com |")
        )
        self.assertIn("campus", microsoft_row)
        self.assertNotIn("campus-1", microsoft_row)
        self.assertIn("phone-hotspot", report_text)
        self.assertIn("hotspot-1", report_text)
        self.assertIn("timeout", report_text)


if __name__ == "__main__":
    unittest.main()
