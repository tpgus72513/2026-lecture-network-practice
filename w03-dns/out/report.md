# DNS steering 측정 보고서

## 측정 범위

- 비교에 사용한 최신 network run: campus, phone-hotspot
- 보존된 전체 run 수: 2
- 주소는 성공한 A 응답의 중복 없는 집합으로 비교했다. timeout·차단·빈 A 집합은 비교 분모에서 제외했다.
- CNAME chain은 system resolver로 한 번 수집했고, A 주소 집합은 system·Google·Quad9 각각에 질의했다.

| network | run ID | 수집 시각(UTC) | system resolver endpoints |
|---|---|---|---|
| campus | 20260915T042757.665274Z--campus--2ce73723 | 2026-09-15T04:27:57.665274Z | 163.152.213.9, 168.126.63.1, 168.126.63.2, 192.168.0.1 |
| phone-hotspot | 20260915T043251.757916Z--phone-hotspot--7d9828fc | 2026-09-15T04:32:51.757916Z | 10.218.249.104, 192.168.0.1 |

## CNAME chain과 third-party 판정

판정 규칙: 관측 chain에 알려진 CDN 서비스 suffix가 있으면 third-party CDN으로 본다. 과제에 명시된 Netflix 자체 CDN과 Korea University 비-CDN은 별도 근거로 처리한다. Wikipedia/Wikimedia의 동일 조직 관계는 [Wikimedia Foundation 공식 프로젝트 목록](https://wikimediafoundation.org/what-we-do/wikimedia-projects/)을 근거로 한다. 그 밖은 CNAME만으로 단정하지 않고 ‘불명’으로 남긴다.

비교용 약식 규칙(rule verdict)은 원래 이름과 최종 이름의 마지막 두 label이 다르면 ‘예’로 본다. 이 규칙은 `co.uk` 같은 public suffix, 같은 조직의 다른 도메인, no-CNAME anycast를 제대로 다루지 못한다.

| site | chain length | final zone | chain source network | third-party? | rule verdict | 판정 근거 |
|---|---:|---|---|---|---|---|
| www.microsoft.com | 2 | akamaiedge.net | campus | 예 | 예 | 관측 chain의 edgekey.net suffix → Akamai CDN |
| www.netflix.com | 1 | netflix.com | campus | 아니오 | 아니오 | 과제 설명에 명시된 Netflix 자체 CDN |
| www.adobe.com | 2 | akamai.net | campus | 예 | 예 | 관측 chain의 edgesuite.net suffix → Akamai CDN |
| www.cnn.com | 1 | fastly.net | phone-hotspot | 예 | 예 | 관측 chain의 fastly.net suffix → Fastly CDN |
| www.apple.com | 3 | akamaiedge.net | phone-hotspot | 예 | 예 | 관측 chain의 edgekey.net suffix → Akamai CDN |
| www.korea.ac.kr | 0 | korea.ac.kr | phone-hotspot | 아니오 | 아니오 | 과제 설명에 명시된 비-CDN 사이트 |
| www.stanford.edu | 1 | netlifyglobalcdn.com | phone-hotspot | 예 | 예 | 관측 chain의 netlifyglobalcdn.com suffix → Netlify CDN ([서비스 문서](https://answers.netlify.com/t/how-can-i-change-which-netlify-site-my-hostname-is-pointing-to/3259)) |
| www.bbc.co.uk | 2 | fastly.net | campus | 예 | 예 | 관측 chain의 fastly.net suffix → Fastly CDN |
| www.spotify.com | 1 | fastly.net | phone-hotspot | 예 | 예 | 관측 chain의 fastly.net suffix → Fastly CDN |
| www.github.com | 1 | github.com | phone-hotspot | 불명 | 아니오 | CNAME 문자열만으로 CDN/소유 관계를 확정할 근거 없음 |
| www.wikipedia.org | 1 | wikimedia.org | phone-hotspot | 아니오 | 예 | 관측 final `dyna.wikimedia.org`; Wikimedia Foundation이 Wikipedia와 Wikimedia 프로젝트를 함께 운영 ([공식 출처](https://wikimediafoundation.org/what-we-do/wikimedia-projects/)) |
| www.nytimes.com | 3 | fastly.net | campus | 예 | 예 | 관측 chain의 fastly.net suffix → Fastly CDN |

### 약식 규칙이 틀린 관측 사례

- `www.wikipedia.org`: 약식 규칙은 예, 근거 기반 판정은 아니오였다. 관측 final `dyna.wikimedia.org`; Wikimedia Foundation이 Wikipedia와 Wikimedia 프로젝트를 함께 운영 ([공식 출처](https://wikimediafoundation.org/what-we-do/wikimedia-projects/))

### network별 CNAME 수집 오류

아래에는 오류 종류만 요약했다. 전문과 run ID는 [원시 chains.json](chains.json)에 그대로 남아 있다. 이전 network의 성공한 chain을 오류가 난 network의 성공처럼 표시하지 않는다.

- `phone-hotspot` / `www.microsoft.com`: timeout
- `phone-hotspot` / `www.netflix.com`: timeout
- `phone-hotspot` / `www.adobe.com`: timeout
- `phone-hotspot` / `www.bbc.co.uk`: timeout
- `phone-hotspot` / `www.nytimes.com`: timeout

## resolver·network steering 결과

- **B5 통합: 7/9** 측정 가능한 CDN 후보 사이트가 resolver 또는 network 변경 때 다른 주소 집합을 반환했다.
- 같은 network에서 resolver만 변경: 7/9
- 동일 endpoint로 확인된 같은 resolver를 network 사이에서 비교: 2/9
- resolver label 기준의 넓은 network 환경 비교: 2/9 (system endpoint가 바뀐 경우를 포함하므로 ‘같은 resolver’ 결과로 해석하지 않음)
- 관측 chain/과제 근거로 정한 CDN 후보는 9개였고, 이 중 비교 가능한 후보는 9개였다.

주소 집합 차이는 DNS 응답 선택이 달랐다는 증거다. replica가 물리적으로 더 가까웠다는 직접 증거는 아니다. Google·Quad9도 anycast이므로 resolver IP만 보고 실제 질의 지점을 멀다고 단정할 수 없다.

## Part A 패킷 분석

원문: [capture-analysis.md](capture-analysis.md)

## Part A — 실제 DNS 패킷 관찰

- 캡처 출처: **본인 PC의 WSL Ubuntu `eth0`**, 학교 인터넷. `tcpdump`로 실제 인터페이스 트래픽을 캡처하고 `editcap`으로 pcapng 변환, `tshark`로 분석했다. 공식 trace나 합성 패킷이 아니다. Windows 물리 Wi-Fi 인터페이스 캡처와는 구분한다.
- 첫 패킷 시각: 2026-09-15T04:28:40.528662+00:00. 로컬 클라이언트: `172.26.137.110`. DNS 질의 **3개**, 응답 **3개**. 질의의 RD 플래그가 모두 0인지: **True**.

| 항목 | 실제 패킷 근거 |
|---|---|
| A2 질의·응답 짝 | 질의 **#1**, 응답 **#2**; transaction ID 모두 **`0x460d`**, 이름 `www.korea.ac.kr`; IP·UDP 포트가 반대 방향으로 일치 |
| A3 위임 응답 | **#2**: Answer=0, Authority=6, NS=`c.dns.kr,e.dns.kr,d.dns.kr,g.dns.kr,f.dns.kr,b.dns.kr` |
| A3 주소 응답 | **#6**: Answer=1, AA=True, A=`163.152.6.10`, 이름 `www.korea.ac.kr` |
| A4 가장 큰 DNS 응답 | **#2**, **DNS 메시지 341바이트**, frame 전체 383바이트 |

> 참고: 원본 `test_tasks.py`는 tshark 4.2 이상이 출력하는 `True/False`를 세지 못해 같은 캡처를 질의 0개·응답 0개로 표시한다. 그 부분만 `0/1`과 `True/False`를 모두 허용하도록 고쳤고, 캡처는 질의 3개·응답 3개(#1~#6)다. `bench.py`는 수정하지 않았다.

위임은 Answer에 호스트 주소를 주지 않고 Authority에 다음 NS를 알려줬다. 최종 응답은 같은 DNS 형식의 Answer에 요청한 A 레코드를 넣었다.
최대 응답 #2에는 Answer 0개, Authority 6개, Additional 10개가 담겨 있었다. NS 목록과 함께 전달된 주소 레코드(A/AAAA glue)가 메시지 크기에 기여했다. UDP의 경우 `udp.length - 8`로 DNS 크기를 구했으며 Ethernet frame 크기로 바꿔 쓰지 않았다.

캡처의 질의 이름 목록은 `capture-facts.json`에 보존했다. 제출 전 이 목록과 파일을 확인하며, 공개할 수 없는 내용이 있으면 직접 새로 캡처한다. 이 실험에서는 Task 1에서 요청한 이름과 그 nameserver 조회 이름인지 대조한다.
