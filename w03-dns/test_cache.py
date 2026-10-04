#!/usr/bin/env python3
"""Task 3 DNS 캐시의 TTL 동작을 검증하는 단위 테스트."""

import unittest

from task3_cache import YourCache


class FakeUpstream:
    """테스트가 지정한 DNS 응답을 순서대로 돌려주는 작은 가짜 upstream."""

    def __init__(self, responses):
        self.responses = {
            name: list(records) for name, records in responses.items()
        }
        self.calls = []

    def __call__(self, name):
        self.calls.append(name)
        return self.responses[name].pop(0)


class YourCacheTest(unittest.TestCase):
    def make_cache(self, responses):
        upstream = FakeUpstream(responses)
        try:
            cache = YourCache(upstream)
        except NotImplementedError as exc:
            self.fail(f"YourCache가 아직 구현되지 않았습니다: {exc}")
        return cache, upstream

    def test_short_ttl_record_is_refetched_after_expiry(self):
        cache, upstream = self.make_cache(
            {"cdn.example": [("192.0.2.10", 20), ("192.0.2.11", 20)]}
        )

        self.assertEqual(cache.lookup("cdn.example", 100), "192.0.2.10")
        self.assertEqual(cache.lookup("cdn.example", 119.999), "192.0.2.10")
        self.assertEqual(cache.lookup("cdn.example", 121), "192.0.2.11")
        self.assertEqual(upstream.calls, ["cdn.example", "cdn.example"])

    def test_long_ttl_record_remains_cached_beyond_sixty_seconds(self):
        cache, upstream = self.make_cache(
            {"stable.example": [("192.0.2.20", 3600)]}
        )

        self.assertEqual(cache.lookup("stable.example", 10), "192.0.2.20")
        self.assertEqual(cache.lookup("stable.example", 3010), "192.0.2.20")
        self.assertEqual(upstream.calls, ["stable.example"])

    def test_exact_expiry_time_is_a_cache_miss(self):
        cache, upstream = self.make_cache(
            {"edge.example": [("192.0.2.30", 30), ("192.0.2.31", 30)]}
        )

        self.assertEqual(cache.lookup("edge.example", 5), "192.0.2.30")
        self.assertEqual(cache.lookup("edge.example", 35), "192.0.2.31")
        self.assertEqual(upstream.calls, ["edge.example", "edge.example"])

    def test_refresh_uses_changed_address_and_new_ttl(self):
        cache, upstream = self.make_cache(
            {
                "changing.example": [
                    ("192.0.2.40", 10),
                    ("192.0.2.41", 100),
                ]
            }
        )

        self.assertEqual(cache.lookup("changing.example", 0), "192.0.2.40")
        self.assertEqual(cache.lookup("changing.example", 10), "192.0.2.41")
        self.assertEqual(cache.lookup("changing.example", 50), "192.0.2.41")
        self.assertEqual(upstream.calls, ["changing.example", "changing.example"])

    def test_zero_ttl_record_is_never_reused(self):
        cache, upstream = self.make_cache(
            {"zero.example": [("192.0.2.50", 0), ("192.0.2.51", 0)]}
        )

        self.assertEqual(cache.lookup("zero.example", 7), "192.0.2.50")
        self.assertEqual(cache.lookup("zero.example", 7), "192.0.2.51")
        self.assertEqual(upstream.calls, ["zero.example", "zero.example"])

    def test_names_have_independent_expiry_times(self):
        cache, upstream = self.make_cache(
            {
                "short.example": [
                    ("192.0.2.60", 10),
                    ("192.0.2.61", 10),
                ],
                "long.example": [("192.0.2.70", 100)],
            }
        )

        self.assertEqual(cache.lookup("short.example", 0), "192.0.2.60")
        self.assertEqual(cache.lookup("long.example", 0), "192.0.2.70")
        self.assertEqual(cache.lookup("short.example", 11), "192.0.2.61")
        self.assertEqual(cache.lookup("long.example", 11), "192.0.2.70")
        self.assertEqual(
            upstream.calls,
            ["short.example", "long.example", "short.example"],
        )

    def test_stats_counts_names_without_duplicating_refreshed_record(self):
        cache, _ = self.make_cache(
            {
                "one.example": [("192.0.2.80", 1), ("192.0.2.81", 1)],
                "two.example": [("192.0.2.90", 10)],
            }
        )

        cache.lookup("one.example", 0)
        cache.lookup("one.example", 2)
        cache.lookup("two.example", 2)

        self.assertEqual(cache.stats(), {"entries": 2})


class CacheFloorTest(unittest.TestCase):
    def load_floor_functions(self):
        try:
            from cache_floor import analyze_workload, minimum_fetches
        except ImportError as exc:
            self.fail(f"cache_floor 모듈이 아직 구현되지 않았습니다: {exc}")
        return analyze_workload, minimum_fetches

    def test_minimum_fetches_starts_a_new_window_at_exact_expiry(self):
        _, minimum_fetches = self.load_floor_functions()

        self.assertEqual(minimum_fetches([0, 5, 10, 19.9, 20], ttl=10), 3)

    def test_fixed_workload_floor_is_275(self):
        analyze_workload, _ = self.load_floor_functions()

        report = analyze_workload()

        self.assertEqual(report["total_minimum_upstream"], 275)
        self.assertEqual(report["records"]["www.microsoft.com"]["minimum"], 118)


if __name__ == "__main__":
    unittest.main()
