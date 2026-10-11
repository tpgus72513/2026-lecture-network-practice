#!/usr/bin/env python3
"""Week 4 · Task 1 evidence for observation.md.

Runs the real Sender/Receiver from task1_rdt.py, then four versions with one
defence removed each, against the unmodified UnreliableChannel. The channel's
own constructor arguments switch one impairment on at a time, so each failure
can be pinned on loss, reordering or duplication.

Note on the payload: verify() builds its data with
`bytes(random.Random(seed).getrandbits(8) for _ in range(size))`, which
re-seeds for every byte, so all 2,000 bytes are the same value and a receiver
that delivers out of order still passes. Here the bytes come from one
generator, so order is really tested.

    python3 task1_experiments.py > out/task1-experiments.txt
"""
import hashlib, random

import task1_rdt as t
from task1_rdt import UnreliableChannel, Sender, Receiver, PAYLOAD


class NoRetransmit(Sender):
    """Sends every packet once and never again."""

    def step(self):
        self.clock = -10**9                  # timers never expire
        return super().step()


class CountingSender(Sender):
    """Believes every ACK means "the oldest outstanding packet arrived"."""

    def step(self):
        self.clock += 1
        while (pkt := self.inp.receive()) is not None:
            if self.sent_at:
                oldest = min(self.sent_at)   # ignores the number on the ACK
                del self.sent_at[oldest]
                self.acked[oldest] = True
        while self.base < len(self.chunks) and self.acked[self.base]:
            self.base += 1
        for seq, ts in list(self.sent_at.items()):
            if self.clock - ts >= t.TIMEOUT:
                self._send(seq)
        while self.next_seq < min(self.base + t.WINDOW, len(self.chunks)):
            self._send(self.next_seq)
            self.next_seq += 1
        return self.base < len(self.chunks)


class ArrivalOrderReceiver(Receiver):
    """Appends payloads in the order they arrive (still drops exact duplicates)."""

    def step(self):
        while (pkt := self.inp.receive()) is not None:
            _, seq, payload = pkt
            self.out.send(("ACK", seq))
            if seq in self.buffer:
                continue
            self.buffer[seq] = payload
            self.chunks.append(payload)


class NoDupCheckReceiver(Receiver):
    """Reorders correctly but stores every copy it receives."""

    def step(self):
        while (pkt := self.inp.receive()) is not None:
            _, seq, payload = pkt
            self.out.send(("ACK", seq))
            self.buffer.setdefault(seq, []).append(payload)

    def data(self):
        return b"".join(p for s in sorted(self.buffer) for p in self.buffer[s])


IMPAIRMENTS = {
    "full channel":   dict(loss=0.10, dup=0.03, reorder=0.10),
    "loss only":      dict(loss=0.10, dup=0.0, reorder=0.0),
    "reorder only":   dict(loss=0.0, dup=0.0, reorder=0.10),
    "duplicate only": dict(loss=0.0, dup=0.03, reorder=0.0),
}
VARIANTS = [
    ("selective repeat (submitted)", Sender, Receiver),
    ("no retransmission", NoRetransmit, Receiver),
    ("ACK number not checked", CountingSender, Receiver),
    ("no reorder buffer", Sender, ArrivalOrderReceiver),
    ("no duplicate check", Sender, NoDupCheckReceiver),
]
SEEDS = (246, 999)


def payload(seed, size=2000, harness=False):
    if harness:   # exactly what verify() does
        return bytes(random.Random(seed).getrandbits(8) for _ in range(size))
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(size))


def run(sender_cls, receiver_cls, seed, size=2000, max_steps=200_000,
        harness=False, **imp):
    original = payload(seed, size, harness)
    up, down = UnreliableChannel(seed, **imp), UnreliableChannel(seed + 1, **imp)
    s, r = sender_cls(up, down, original), receiver_cls(up, down)
    first_bad = last_growth = None
    have = steps = 0
    for steps in range(1, max_steps + 1):
        alive = s.step()
        r.step()
        got = r.data() or b""
        if first_bad is None and not original.startswith(got):
            first_bad = steps
        if len(got) > have:
            have, last_growth = len(got), steps
        if not alive and len(got) >= size:
            break
    got = r.data() or b""
    if hashlib.sha256(got).digest() == hashlib.sha256(original).digest():
        verdict = "IDENTICAL"
    elif len(got) < size:
        verdict = f"SHORT {len(got)}B"
    elif len(got) > size:
        verdict = f"EXTRA {len(got)}B"
    else:
        verdict = "WRONG ORDER"
    return dict(verdict=verdict, steps=steps, up=up, down=down, s=s, r=r,
                first_bad=first_bad, last_growth=last_growth, have=have)


def table(harness):
    print(f"  {'variant':<30}" + "".join(f"{k:<28}" for k in IMPAIRMENTS))
    for name, scls, rcls in VARIANTS:
        cells = []
        for imp in IMPAIRMENTS.values():
            vs = [run(scls, rcls, seed, harness=harness, **imp)["verdict"] for seed in SEEDS]
            cells.append(vs[0] if vs[0] == vs[1] else " / ".join(vs))
        print(f"  {name:<30}" + "".join(f"{c:<28}" for c in cells))


def main():
    print(f"== Cost of reliability, submitted protocol "
          f"(WINDOW={t.WINDOW}, TIMEOUT={t.TIMEOUT} steps, PAYLOAD={PAYLOAD} B)\n")
    minimum = -(-2000 // PAYLOAD)
    for seed in SEEDS:
        x = run(Sender, Receiver, seed)
        up, down, s, r = x["up"], x["down"], x["s"], x["r"]
        total = up.stats["sent"] + down.stats["sent"]
        print(f"  seed {seed}: {x['verdict']} (random payload) in {x['steps']} steps")
        print(f"    data  {up.stats}   retransmissions {s.retransmissions}")
        print(f"    acks  {down.stats}")
        print(f"    data packets {up.stats['sent']} / minimum {minimum} = "
              f"{up.stats['sent'] / minimum:.2f}x;  data+ACK {total} / {2 * minimum} = "
              f"{total / (2 * minimum):.2f}x")
        print(f"    receiver: {r.out_of_order} DATA arrived ahead of a gap, "
              f"{r.duplicates} DATA arrived it already had\n")

    print("== One defence removed x one impairment at a time, random payload "
          f"(seeds {SEEDS[0]} / {SEEDS[1]})\n")
    table(harness=False)

    print("\n== Same, with verify()'s payload (2000 identical bytes)\n")
    table(harness=True)

    print("\n== When each broken variant went wrong on the full channel, random payload\n")
    for name, scls, rcls in VARIANTS[1:]:
        for seed in SEEDS:
            x = run(scls, rcls, seed)
            what = (f"output stopped matching the input at step {x['first_bad']}"
                    if x["first_bad"] else
                    f"never wrong, but stuck at {x['have']} B from step {x['last_growth']}")
            print(f"  {name:<24} seed {seed}: {what}")


if __name__ == "__main__":
    main()
