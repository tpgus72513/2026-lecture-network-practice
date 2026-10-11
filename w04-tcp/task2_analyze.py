#!/usr/bin/env python3
"""Week 4 · Task 2 Part A — read the handshakes and windows out of a capture.

    python3 task2_analyze.py out/tcp.pcapng > out/capture-analysis.txt

Needs tshark (on Windows: C:\\Program Files\\Wireshark\\tshark.exe is found
automatically). The capture is taken at the *receiver* (this laptop downloads),
so tshark's own bytes-in-flight for the server's packets is near zero: the
client ACKs each segment as it lands. What the sender actually kept in flight
is visible instead as the bytes that arrive within one RTT, and that is what
is compared with the advertised window here.
"""
import collections, os, shutil, statistics, subprocess, sys

TSHARK = shutil.which("tshark") or r"C:\Program Files\Wireshark\tshark.exe"


def fields(cap, flt, *names):
    cmd = [TSHARK, "-r", cap, "-T", "fields", "-E", "occurrence=f"]
    if flt:
        cmd += ["-Y", flt]
    for n in names:
        cmd += ["-e", n]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    rows = [dict(zip(names, l.split("\t"))) for l in out.splitlines() if l.strip()]
    for r in rows:                  # IPv4 or IPv6: the hotspot hands out native v6
        if "ipv6.src" in r:
            r["ip.src"] = r["ip.src"] or r.pop("ipv6.src")
    return rows


def endpoint(addr, port):
    return f"[{addr}]:{port}" if ":" in addr else f"{addr}:{port}"


def main(cap):
    syn = fields(cap, "tcp.flags.syn==1",
                 "frame.number", "tcp.stream", "ip.src", "ipv6.src", "tcp.srcport", "tcp.dstport",
                 "tcp.flags.ack", "tcp.seq_raw", "tcp.ack_raw", "tcp.window_size_value",
                 "tcp.options.mss_val", "tcp.options.wscale.shift",
                 "tcp.options.wscale.multiplier", "tcp.options.sack_perm")
    acks = fields(cap, "tcp.flags.syn==0 and tcp.flags.ack==1 and tcp.seq==1 and tcp.ack==1 "
                       "and tcp.len==0",
                  "frame.number", "tcp.stream", "tcp.seq_raw", "tcp.ack_raw",
                  "tcp.window_size_value", "tcp.window_size", "tcp.analysis.initial_rtt")
    third = {}
    for a in acks:
        third.setdefault(a["tcp.stream"], a)       # first pure ACK = handshake ACK

    streams = collections.defaultdict(dict)
    for p in syn:
        streams[p["tcp.stream"]]["synack" if p["tcp.flags.ack"] in ("1", "True") else "syn"] = p

    client = None
    print(f"== Handshakes in {os.path.basename(cap)}\n")
    for s in sorted(streams, key=int):
        h = streams[s]
        if "syn" not in h or "synack" not in h or s not in third:
            continue
        c, v, a = h["syn"], h["synack"], third[s]
        client = c["ip.src"]
        isn_c, isn_s = int(c["tcp.seq_raw"]), int(v["tcp.seq_raw"])
        ok = (int(v["tcp.ack_raw"]) == isn_c + 1 and int(a["tcp.seq_raw"]) == isn_c + 1
              and int(a["tcp.ack_raw"]) == isn_s + 1)
        print(f"  stream {s}: SYN #{c['frame.number']}  SYN-ACK #{v['frame.number']}  "
              f"ACK #{a['frame.number']}   {endpoint(c['ip.src'], c['tcp.srcport'])} -> "
              f"{endpoint(v['ip.src'], c['tcp.dstport'])}")
        print(f"    ISN client {isn_c:>10}   ISN server {isn_s:>10}   "
              f"(SYN-ACK acks ISN+1, ACK acks server ISN+1: {'yes' if ok else 'NO'})")
        for who, p in (("client SYN    ", c), ("server SYN-ACK", v)):
            print(f"    {who}  MSS {p['tcp.options.mss_val']:>5}   window scale "
                  f"shift {p['tcp.options.wscale.shift']:>2} (x{p['tcp.options.wscale.multiplier']:>5})"
                  f"   SACK permitted {'yes' if p['tcp.options.sack_perm'] else 'no'}"
                  f"   raw window {p['tcp.window_size_value']}")
        print(f"    handshake ACK: raw window {a['tcp.window_size_value']} -> scaled "
              f"{a['tcp.window_size']} bytes;  SYN->ACK RTT {float(a['tcp.analysis.initial_rtt']) * 1000:.1f} ms\n")

    rows = fields(cap, "tcp.len>0 or tcp.flags.syn==0",
                  "tcp.stream", "ip.src", "ipv6.src", "frame.time_relative", "tcp.len", "tcp.window_size",
                  "tcp.analysis.retransmission", "tcp.analysis.out_of_order")
    print("== Advertised window (client, after scaling) vs what the server kept in flight\n")
    print("   in flight per RTT = server payload bytes arriving within one handshake RTT\n")
    per = collections.defaultdict(lambda: {"rwnd": [], "data": [], "retx": 0})
    for r in rows:
        d = per[r["tcp.stream"]]
        if r["ip.src"] == client:
            if r["tcp.window_size"]:
                d["rwnd"].append(int(r["tcp.window_size"]))
        elif int(r["tcp.len"] or 0) > 0:
            d["data"].append((float(r["frame.time_relative"]), int(r["tcp.len"])))
            d["retx"] += bool(r["tcp.analysis.retransmission"] or r["tcp.analysis.out_of_order"])
    for s in sorted(per, key=int):
        d = per[s]
        if s not in third or not d["data"]:
            continue
        rtt = float(third[s]["tcp.analysis.initial_rtt"])
        t0, t1 = d["data"][0][0], d["data"][-1][0]
        bins = collections.Counter()
        for t, n in d["data"]:
            bins[int((t - t0) / rtt)] += n
        flight = [bins[i] for i in range(int((t1 - t0) / rtt) + 1)]
        total = sum(n for _, n in d["data"])
        rw = d["rwnd"]
        print(f"  stream {s}: {total:,} B in {t1 - t0:.2f} s ({total * 8 / (t1 - t0) / 1e6:.1f} Mbps), "
              f"RTT {rtt * 1000:.1f} ms")
        print(f"    advertised window  median {statistics.median(rw):>9,.0f}   max {max(rw):>9,} B")
        print(f"    in flight per RTT  median {statistics.median(flight):>9,.0f}   max {max(flight):>9,} B"
              f"   -> peak used {max(flight) / statistics.median(rw):.0%} of the median window")
        half = next(i for i, v in enumerate(flight) if v >= statistics.median(flight))
        print(f"    slow-start ramp: first RTT at the median flight = RTT #{half} "
              f"-> {half * rtt * 1000:.0f} ms after the first data byte")
        print(f"    server segments retransmitted or out of order: {d['retx']}\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "out", "tcp.pcapng"))
