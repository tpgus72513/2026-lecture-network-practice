#!/usr/bin/env python3
"""Task 3 고정 workload에서 올바른 DNS 캐시의 upstream 하한을 계산한다.

이 계산은 ``YourCache``를 사용하지 않는다. 요청 시각을 DNS 이름별로
분리한 뒤, 이전 조회의 TTL로 덮이지 않는 첫 요청마다 새 조회를 하나 센다.
"""

import json
from pathlib import Path

from bench import FIXTURE, QUERIES, workload


OUTPUT_PATH = Path(__file__).with_name("out") / "cache-floor.json"


def minimum_fetches(query_times, ttl):
    """정렬된 요청 시각 목록을 모두 처리하는 데 필요한 최소 조회 수."""
    fetches = 0
    valid_until = None

    for now in query_times:
        # 만료 시각에는 남은 TTL이 0이므로 새 응답이 필요하다.
        if valid_until is None or now >= valid_until:
            fetches += 1
            valid_until = now + ttl

    return fetches


def analyze_workload():
    """이름별 요청 수와 최소 upstream 조회 수를 JSON용 사전으로 만든다."""
    query_times_by_name = {name: [] for name in FIXTURE}
    for now, name in workload():
        query_times_by_name[name].append(now)

    records = {}
    total_minimum = 0
    for name, (_, ttl) in FIXTURE.items():
        query_times = query_times_by_name[name]
        minimum = minimum_fetches(query_times, ttl)
        records[name] = {
            "ttl_seconds": ttl,
            "queries": len(query_times),
            "minimum": minimum,
        }
        total_minimum += minimum

    return {
        "assumptions": [
            "캐시는 처음에 비어 있다.",
            "요청이 들어온 시점에만 해당 이름을 upstream에서 조회한다.",
            "응답은 권한 서버가 준 TTL 동안만 유효하며 만료 시각에는 재사용하지 않는다.",
        ],
        "method": (
            "이름별로 첫 요청에서 조회하고, 그 응답의 만료 시각 이상인 "
            "첫 요청에서 다시 조회하는 과정을 반복했다. 더 일찍 조회하면 만료도 "
            "더 빨라지고, 더 늦게 조회하면 현재 요청에 답할 수 없으므로 이 수보다 "
            "적은 조회로 모든 요청에 유효한 답을 줄 수 없다."
        ),
        "total_queries": QUERIES,
        "total_minimum_upstream": total_minimum,
        "records": records,
    }


def main():
    report = analyze_workload()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"upstream 하한: {report['total_minimum_upstream']}")
    print(f"근거 파일: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
