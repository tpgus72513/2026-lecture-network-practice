## Part A — 실제 DNS 패킷 관찰

- 캡처 출처: **본인 PC의 WSL Ubuntu `eth0`**, 학교 인터넷. `tcpdump`로 실제 인터페이스 트래픽을 캡처하고 `editcap`으로 pcapng 변환, `tshark`로 분석했다. 공식 trace나 합성 패킷이 아니다. Windows 물리 Wi-Fi 인터페이스 캡처와는 구분한다.
- 첫 패킷 시각: 2026-09-15T04:28:40.528662+00:00. 로컬 클라이언트: `172.26.137.110`. DNS 질의 **3개**, 응답 **3개**. 질의의 RD 플래그가 모두 0인지: **True**.

| 항목 | 실제 패킷 근거 |
|---|---|
| A2 질의·응답 짝 | 질의 **#1**, 응답 **#2**; transaction ID 모두 **`0x460d`**, 이름 `www.korea.ac.kr`; IP·UDP 포트가 반대 방향으로 일치 |
| A3 위임 응답 | **#2**: Answer=0, Authority=6, NS=`c.dns.kr,e.dns.kr,d.dns.kr,g.dns.kr,f.dns.kr,b.dns.kr` |
| A3 주소 응답 | **#6**: Answer=1, AA=True, A=`163.152.6.10`, 이름 `www.korea.ac.kr` |
| A4 가장 큰 DNS 응답 | **#2**, **DNS 메시지 341바이트**, frame 전체 383바이트 |

위임은 Answer에 호스트 주소를 주지 않고 Authority에 다음 NS를 알려줬다. 최종 응답은 같은 DNS 형식의 Answer에 요청한 A 레코드를 넣었다.
최대 응답 #2에는 Answer 0개, Authority 6개, Additional 10개가 담겨 있었다. NS 목록과 함께 전달된 주소 레코드(A/AAAA glue)가 메시지 크기에 기여했다. UDP의 경우 `udp.length - 8`로 DNS 크기를 구했으며 Ethernet frame 크기로 바꿔 쓰지 않았다.

캡처의 질의 이름 목록은 `capture-facts.json`에 보존했다. 제출 전 이 목록과 파일을 확인하며, 공개할 수 없는 내용이 있으면 직접 새로 캡처한다. 이 실험에서는 Task 1에서 요청한 이름과 그 nameserver 조회 이름인지 대조한다.
