#!/usr/bin/env python3
"""Week 4 · Task 1 — Build reliable delivery on top of an unreliable channel.

Textbook §3.4 (reliable data transfer) and §3.5 (TCP's sequence numbers).

`UnreliableChannel` below loses packets, reorders them, duplicates them, and
delays them. It is the network as §3.4 models it. Your job is to move a file
across it and have the bytes arrive intact and in order.

That is the whole of TCP's reliability story with the congestion control taken
out, and it is worth building once by hand before you ever trust a socket again.

    python3 task1_rdt.py --verify
"""
import argparse, hashlib, random

PAYLOAD = 8            # bytes per packet - small, so you see the sequencing


class UnreliableChannel:
    """Loses 10%, duplicates 3%, reorders, and delays. Deterministic by seed.

    You may not make it nicer. You may not read its internals. It is the only
    way your sender can reach your receiver.
    """

    def __init__(self, seed=246, loss=0.10, dup=0.03, reorder=0.10):
        self.rng = random.Random(seed)
        self.loss, self.dup, self.reorder = loss, dup, reorder
        self.wire = []          # packets in flight, in no particular order
        self.stats = {"sent": 0, "lost": 0, "duplicated": 0, "delivered": 0}

    def send(self, packet):
        """Hand a packet to the network. It may never come out."""
        self.stats["sent"] += 1
        if self.rng.random() < self.loss:
            self.stats["lost"] += 1
            return
        copies = 2 if self.rng.random() < self.dup else 1
        self.stats["duplicated"] += copies - 1
        for _ in range(copies):
            if self.rng.random() < self.reorder and self.wire:
                self.wire.insert(self.rng.randrange(len(self.wire)), packet)
            else:
                self.wire.append(packet)

    def receive(self):
        """Take the next packet out, or None if the network has nothing."""
        if not self.wire:
            return None
        self.stats["delivered"] += 1
        return self.wire.pop(0)


WINDOW = 16           # packets the sender may have unacknowledged at once
TIMEOUT = 6           # steps to wait for an ACK before sending a packet again


class Sender:
    """Selective-repeat sliding window (textbook §3.4.4).

    Every packet is ("DATA", seq, payload) and gets its own timer. An ACK is
    ("ACK", seq) and acknowledges exactly that one packet, so a lost ACK costs
    one retransmission and nothing else. An ACK is only believed after its
    number is checked: one that is not for an outstanding packet (a duplicate,
    or an old one that wandered in late) is ignored.
    """

    def __init__(self, data_channel, ack_channel, data):
        self.out, self.inp = data_channel, ack_channel
        self.chunks = [data[i:i + PAYLOAD] for i in range(0, len(data), PAYLOAD)]  # R1
        self.acked = [False] * len(self.chunks)
        self.sent_at = {}                     # seq -> step last (re)sent, unacked only
        self.base = 0                         # oldest seq not yet acknowledged
        self.next_seq = 0                     # next seq never sent
        self.clock = 0
        self.transmissions = self.retransmissions = 0

    def _send(self, seq):
        self.out.send(("DATA", seq, self.chunks[seq]))
        self.sent_at[seq] = self.clock
        self.transmissions += 1

    def step(self):
        self.clock += 1
        while (pkt := self.inp.receive()) is not None:
            kind, seq = pkt[0], pkt[1]
            if kind != "ACK" or seq not in self.sent_at:
                continue                      # R3: duplicate or stale ACK
            del self.sent_at[seq]
            self.acked[seq] = True
        while self.base < len(self.chunks) and self.acked[self.base]:
            self.base += 1                    # slide the window

        for seq, t in list(self.sent_at.items()):  # R4: per-packet timers
            if self.clock - t >= TIMEOUT:
                self._send(seq)
                self.retransmissions += 1
        while self.next_seq < min(self.base + WINDOW, len(self.chunks)):
            self._send(self.next_seq)
            self.next_seq += 1
        return self.base < len(self.chunks)


class Receiver:
    """Buffers out-of-order packets and releases bytes strictly in order.

    Every DATA packet is ACKed, including duplicates and packets it already
    delivered: the sender may have lost the first ACK and is waiting for one.
    A packet already seen is never stored twice, so a duplicate cannot add bytes.
    """

    def __init__(self, data_channel, ack_channel):
        self.inp, self.out = data_channel, ack_channel
        self.buffer = {}                      # seq -> payload, not yet in order
        self.expected = 0                     # next seq to append to the output
        self.chunks = []
        self.duplicates = self.out_of_order = 0

    def step(self):
        while (pkt := self.inp.receive()) is not None:
            kind, seq, payload = pkt
            if kind != "DATA":
                continue
            self.out.send(("ACK", seq))
            if seq < self.expected or seq in self.buffer:
                self.duplicates += 1          # R3: already have it
                continue
            if seq != self.expected:
                self.out_of_order += 1
            self.buffer[seq] = payload
            while self.expected in self.buffer:  # R2: release in order only
                self.chunks.append(self.buffer.pop(self.expected))
                self.expected += 1

    def data(self):
        """The bytes reassembled so far."""
        return b"".join(self.chunks)


# ------------------------------------------------------------------- harness
def verify(seed=246, size=2000, max_steps=200_000):
    original = bytes(random.Random(seed).getrandbits(8) for _ in range(size))
    up, down = UnreliableChannel(seed), UnreliableChannel(seed + 1)

    # Data goes out over `up`, ACKs come back over `down`. Both are unreliable.
    sender = Sender(up, down, original)
    receiver = Receiver(up, down)

    for _ in range(max_steps):
        alive = sender.step()
        receiver.step()
        if not alive and len(receiver.data() or b"") >= size:
            break

    got = receiver.data() or b""
    ok = hashlib.sha256(got).hexdigest() == hashlib.sha256(original).hexdigest()
    print(f"  bytes    sent {size}   received {len(got)}")
    print(f"  channel  {up.stats}")
    print(f"  result   {'IDENTICAL' if ok else 'CORRUPTED OR INCOMPLETE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--verify", action="store_true")
    p.add_argument("--seed", type=int, default=246)
    a = p.parse_args()
    raise SystemExit(verify(a.seed) if a.verify else p.print_help())
