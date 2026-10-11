#!/usr/bin/env python3
"""Week 4 · Task 2 Part B — B3 numbers from out/throughput.json.

    python3 task2_summary.py > out/throughput-summary.txt

Splits each curl run into the part that is paid in round trips (DNS, TCP
handshake, TLS + request until the first byte) and the transfer itself, so the
handshake's cost to throughput (B5) can be read off directly.
"""
import json, os, statistics as st

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
med = st.median

for rec in json.load(open(os.path.join(OUT, "throughput.json"))):
    runs = rec["runs"]
    mbps = [r["mbps"] for r in runs]
    hs = [r["connect_s"] * 1000 for r in runs]
    setup = [(r["dns_s"] + r["connect_s"] + r["ttfb_s"]) * 1000 for r in runs]
    xfer = [r["bytes"] * 8 / (r["total_s"] - r["dns_s"] - r["connect_s"] - r["ttfb_s"]) / 1e6
            for r in runs]
    print(f"== {rec['label']}   ({rec['when']}, {rec['target']})")
    print(f"   throughput   median {med(mbps):6.2f} Mbps   min {min(mbps):6.2f}   max {max(mbps):6.2f}"
          f"   spread (max-min)/median {(max(mbps) - min(mbps)) / med(mbps):.0%}"
          f"   stdev {st.stdev(mbps):.2f}")
    print(f"   handshake    median {med(hs):6.1f} ms     min {min(hs):6.1f}   max {max(hs):6.1f}")
    print(f"   TLS+request  median {med([r['ttfb_s'] * 1000 for r in runs]):6.1f} ms (ttfb)")
    print(f"   setup total  median {med(setup):6.1f} ms  = DNS + handshake + ttfb, all paid in RTTs")
    print(f"   setup share  median {med([s / 1000 / r['total_s'] for s, r in zip(setup, runs)]):.0%} of each run's time")
    print(f"   transfer-only rate  median {med(xfer):6.2f} Mbps   (bytes / time after the first byte)")
    for i, r in enumerate(runs, 1):
        print(f"     run {i}: {r['mbps']:6.2f} Mbps  handshake {r['connect_s'] * 1000:5.1f} ms"
              f"  ttfb {r['ttfb_s'] * 1000:6.1f} ms  total {r['total_s']:.3f} s")
    print()
