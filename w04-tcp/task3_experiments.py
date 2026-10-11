#!/usr/bin/env python3
"""Week 4 · Task 3 evidence for observation.md.

Uses bench.simulate() unmodified. The last table changes bench's link
constants in memory only (bench.py on disk is untouched) to see what the
design assumes about the link.

    python3 task3_experiments.py > out/task3-experiments.txt
"""
import statistics, sys

import bench
from task3_congestion import FixedWindow, YourControl


def fixed(w):
    class Fixed(FixedWindow):
        def __init__(self):
            self.window = w
    return Fixed


class Reno:
    """Textbook AIMD: slow start, halve on every loss, +1 per RTT."""

    def __init__(self):
        self.window, self.ssthresh = 1.0, float("inf")

    def on_ack(self):
        self.window += 1 if self.window < self.ssthresh else 1 / self.window

    def on_loss(self):
        self.window = self.ssthresh = max(2.0, self.window / 2)


def mine(beta=YourControl.BETA_PROBE, hold=YourControl.HOLD):
    class Variant(YourControl):
        BETA_PROBE, HOLD = beta, hold
    return Variant


def traced(cls):
    """Window each slot (the harness reads .window once per slot) and every cut."""
    windows, cuts = [], []

    class Traced(cls):
        @property
        def window(self):
            if sys._getframe(1).f_code is bench.simulate.__code__:
                windows.append(self._w)        # the harness's one read per slot
            return self._w

        @window.setter
        def window(self, v):
            self._w = v

        def on_loss(self):
            before = self._w
            super().on_loss()
            if self._w != before:
                cuts.append((len(windows), round(before, 1), round(self._w, 1)))

    return bench.simulate(Traced), windows, cuts


def row(name, r, base):
    return (f"  {name:<36} goodput {r['goodput']:6.1f} ({r['goodput'] / base['goodput']:5.1%})"
            f"   loss {r['loss']:6.2%}   retx {r['retx']:5}   avg queue {r['queue']:5.2f}")


def main():
    base = bench.simulate(FixedWindow)
    print(f"== Link: {bench.CAPACITY} pkt/slot, RTT {bench.RTT}, queue {bench.QUEUE}, "
          f"{bench.SLOTS} slots, timeout {bench.TIMEOUT}\n")
    print(row("FixedWindow 64 (baseline)", base, base))
    for w in (18, 20, 22, 25, 30, 31, 40):
        print(row(f"fixed window {w}", bench.simulate(fixed(w)), base))
    print(row("textbook Reno (halve on every loss)", bench.simulate(Reno), base))
    print(row("YourControl (submitted)", bench.simulate(YourControl), base))

    print("\n== Where the submitted window goes")
    r, ws, cuts = traced(YourControl)
    print("   cuts (slot, window before -> after):")
    for c in cuts:
        print(f"     slot {c[0]:4}: {c[1]:5.1f} -> {c[2]:5.1f}")
    tail = ws[1000:]
    print(f"   slots 1000-3999: window median {statistics.median(tail):.1f}, "
          f"min {min(tail):.1f}, max {max(tail):.1f}, "
          f"time at <= 22: {sum(w <= 22 for w in tail) / len(tail):.0%}")
    print("   every 250 slots: " + " ".join(f"{ws[i]:.0f}" for i in range(0, len(ws), 250)))

    print("\n== Gentler backoff: cut factor after a probe loss, no hold (pure AIMD, one cut per event)")
    for b in (0.5, 0.6, 2 / 3, 0.75, 0.85, 0.9):
        print(row(f"beta {b:.2f}, hold 0", bench.simulate(mine(b, 0)), base))
    print("\n== Same cut factors with the hold")
    for b in (0.5, 0.6, 2 / 3, 0.75, 0.85, 0.9):
        print(row(f"beta {b:.2f}, hold {YourControl.HOLD}", bench.simulate(mine(b)), base))
    print("\n== Hold length (beta 2/3)")
    for h in (0, 100, 250, 500, 1000, 2000):
        print(row(f"hold {h}", bench.simulate(mine(hold=h)), base))

    print("\n== Other links (bench constants changed in memory only)")
    saved = bench.RTT, bench.QUEUE, bench.TIMEOUT
    for rtt, q in ((20, 10), (10, 10), (20, 20), (40, 10), (20, 5), (40, 40)):
        bench.RTT, bench.QUEUE, bench.TIMEOUT = rtt, q, 3 * rtt
        b = bench.simulate(FixedWindow)
        m = bench.simulate(YourControl)
        print(f"  RTT {rtt:2} queue {q:2} (cliff ~{rtt + q:2}, pipe/cliff {rtt / (rtt + q):.2f})"
              f"   mine {m['goodput'] / b['goodput']:5.1%} of baseline, loss {m['loss']:5.2%},"
              f" queue {m['queue']:5.2f}")
    bench.RTT, bench.QUEUE, bench.TIMEOUT = saved


if __name__ == "__main__":
    main()
