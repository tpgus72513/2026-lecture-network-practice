# Week 04 TCP — 근거 자료 안내

관찰 요약은 [`observation.md`](observation.md)에 있다. 이 문서는 관찰의 숫자가 어느 파일에서 나왔는지와 재현 방법을 정리한다.

## 재현

```bash
cd w04-tcp
python3 task1_rdt.py --verify && python3 task1_rdt.py --verify --seed 999   # -> out/task1-verify.txt
python3 task1_experiments.py > out/task1-experiments.txt
python3 task2_measure.py --label "<network>"                                 # 네트워크마다 1회
python3 task2_analyze.py out/tcp.pcapng > out/capture-analysis.txt
python3 task2_summary.py > out/throughput-summary.txt
python3 bench.py --yours > out/bench.txt
python3 task3_experiments.py > out/task3-experiments.txt
python3 test_tasks.py            # -> out/tests.txt  (8 passed, 0 failed, 1 skipped)
python3 ../check.py w04          # -> out/format-check.txt
```

`bench.py`, `UnreliableChannel`, `verify()`, `test_tasks.py`는 수정하지 않았다. 실험 스크립트는 채널 생성자 인자(loss/dup/reorder)와 메모리 안의 bench 상수만 바꿔 조건을 나눈다.

## Task 1 — `task1_rdt.py`

| 항목 | 값 | 출처 |
|---|---|---|
| 프로토콜 | Selective Repeat, window 16, 패킷별 timer 6 step, 패킷별 ACK | `task1_rdt.py` |
| seed 246 / 999 | IDENTICAL / IDENTICAL (111 / 128 step) | `task1-verify.txt`, `task1-experiments.txt` |
| DATA 전송 | 311 / 최소 250 = 1.24배, ACK 포함 597 / 500 = 1.19배 | `task1-experiments.txt` |
| 앞 번호 빈칸보다 먼저 온 DATA | 286개 중 140개 (seed 246) | `task1-experiments.txt` |
| 방어 하나씩 제거 | 재전송 없음·ACK 번호 미확인 → 손실 시 SHORT, 재배열 버퍼 없음 → WRONG ORDER, 중복 검사 없음 → loss-only에서도 EXTRA | `task1-experiments.txt` |

**하네스 관찰**: `verify()`는 `bytes(random.Random(seed).getrandbits(8) for _ in range(size))`로 데이터를 만든다. 생성기 안에서 매 바이트 `Random(seed)`를 새로 만들기 때문에 2,000바이트가 모두 같은 값이다. 그래서 순서를 지키지 않는 수신기도 `verify()`를 통과한다(`task1-experiments.txt`의 두 번째 표). 제출 구현은 실제 난수 바이트로도 따로 검증했다.

## Task 2 — 측정

### Part A: `tcp.pcapng`

- 캡처 조건: 본인 노트북 Wi-Fi 인터페이스, `dumpcap`, capture filter `tcp port 443 and host <speed.cloudflare.com의 주소>`, snaplen 128 B(헤더만 저장하고 payload는 저장하지 않음)
- 내용: 29,190 packets. 주소는 사설 IP `192.168.219.108`와 Cloudflare `172.66.0.218` 두 개뿐이다(개인정보 확인 완료).
- 연결 5개(측정 5회)의 SYN / SYN-ACK / ACK 번호, ISN, 옵션, scaled window, in-flight는 `capture-analysis.txt`에 정리했다.

| stream 0 | 값 |
|---|---|
| SYN / SYN-ACK / ACK | #1 / #2 / #3 |
| ISN client / server | 1144885328 / 996280187 |
| SYN 옵션 (client) | MSS 1460, wscale shift 8 (×256), SACK permitted |
| SYN-ACK 옵션 (server) | MSS 1400, wscale shift 13 (×8192), SACK permitted |
| scaled rwnd | 255×256 = 65,280 B → 중앙값 261,888 B, 최대 524,032 B |
| RTT당 in-flight | 중앙값 20,184 B, 최대 103,596 B (rwnd 중앙값의 40%) |

캡처는 수신측(다운로드하는 노트북)에서 했으므로 tshark의 `bytes_in_flight`는 송신측 값을 보여 주지 못한다. 클라이언트가 바로 ACK하기 때문이다. 대신 **한 RTT 동안 도착한 서버 payload**를 송신측 in-flight로 썼다.

테더링 연결(IPv6)도 같은 방법으로 분석해 `capture-analysis-tethering.txt`에 두었다. 폰 hotspot의 공인 IPv6 주소는 가렸고, 그 원본 pcap은 개인정보 때문에 올리지 않았다.

### Part B: `throughput.json`, `throughput-summary.txt`

| 네트워크 | 측정 시각 | 중앙값 | 범위 (spread) | handshake 중앙값 | 준비 시간(DNS+handshake+ttfb) 중앙값 |
|---|---|---|---|---|---|
| 집 Wi-Fi (U+, 5 GHz) | 2026-10-10 23:33 | 28.23 Mbps | 23.17–46.84 (84%) | 17.3 ms | 151 ms |
| 폰 테더링 (Galaxy S25) | 2026-10-11 22:52 | 30.76 Mbps | 27.84–33.26 (18%) | 36.2 ms | 225 ms |

대상은 기본값 `https://speed.cloudflare.com/__down?bytes=5000000`을 그대로 썼다.

## Task 3 — `task3_congestion.py`

| 송신자 | goodput (baseline 대비) | loss | avg queue |
|---|---|---|---|
| FixedWindow 64 | 986.8 (100%) | 37.4% | 8.76 |
| 고정 window 20 (참고) | 986.8 (100%) | 0.28% | 0.05 |
| textbook Reno | 811.0 (82.2%) | 1.93% | 2.93 |
| **YourControl** | **973.8 (98.7%)** | **2.00%** | **1.91** → strong |

window 변화, β·hold sweep, 다른 링크에서의 결과는 `task3-experiments.txt`에 있다.
