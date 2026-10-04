# 구현과 검증 메모

## 구조

| 파일 | 책임 |
|---|---|
| `task1_resolve.py` | 직접 위임 탐색, CNAME, NS 주소 조회, 서버 재시도와 종료 제한 |
| `task2_steering.py` | 네트워크별 DNS 수집 원본 보존, 근거 기반 분류, 보고서 생성 |
| `task3_cache.py` | TTL을 지키는 `YourCache` |
| `cache_floor.py` | 고정 workload에서 필요한 최소 upstream 조회 수의 독립 계산 |
| `test_resolver.py`, `test_steering.py`, `test_cache.py` | 외부 네트워크 변화에 의존하지 않는 동작 테스트 |

## Task 1에서 중요한 판단

- DNS 메시지의 RD 플래그를 끄고 루트에서 시작한다. `dns.resolver`에 해석을 맡기는 방식은 Task 1에서 사용하지 않는다.
- NS의 glue는 응답한 **부모 권한 영역**을 기준으로 검사한다. 루트가 `.com`을 위임할 때 `a.gtld-servers.net` 주소를 함께 주는 경우가 실제 반례였다. 자식 `.com` 내부 이름만 허용하면 정상 부트스트랩을 막는다.
- 사용할 glue가 있으면 먼저 시도하고, 실패하거나 없을 때 필요한 NS 이름을 별도로 해석한다.
- 성공한 NS 주소는 한 번의 `resolve()` 안에서 재사용한다. CNAME 대상이 같은 NS를 쓰는 경우를 단순한 ‘이미 방문함’으로 막지 않는다.
- UDP TC 플래그가 켜지면 같은 서버에 TCP로 다시 질의한다. 경로에는 실제로 시도한 UDP/TCP 전송이 모두 포함된다.
- 구현 범위는 과제에서 요구한 IPv4 A 해석이다. DNSSEC 검증과 범용 운영용 resolver 전체 기능을 구현한 것은 아니다.

## Task 2의 원본과 집계

`out/chains.json`의 최상위는 `schema_version`, `sites`, `runs`이다. 사이트는 12개이며 run은 실제 네트워크별 실행 기록이다. run마다 시각, 네트워크 이름, resolver 설정과 모든 사이트의 CNAME/A 결과를 보존한다.

- CNAME은 system resolver로 수집하고 A 주소 집합은 system·Google·Quad9에 각각 질의한다.
- 응답 순서와 중복은 주소 집합 차이로 보지 않는다. 시간 초과·오류·빈 A 집합도 steering으로 세지 않는다.
- 같은 resolver를 비교할 때는 label뿐 아니라 endpoint 정보도 확인한다. 학교 DNS와 핫스팟 DNS를 둘 다 `system`이라고 부른다는 이유로 같은 서버로 취급하지 않는다.
- 최신 CNAME 조회가 실패해도 이전 network의 성공한 증거를 지우지 않는다. 표에 증거의 network를 표시하고 실패 내역을 별도로 유지한다.
- CDN 후보와 제3자 여부는 별개다. Netflix는 과제에서 자체 CDN으로 명시했으므로 CDN 후보 분모에는 포함하지만 제3자로 표시하지 않는다.
- 알려진 서비스 도메인·소유 관계로 확인되지 않은 경우는 ‘불명’이다. 따라서 7/9는 **이 규칙으로 확인한 비교 가능한 CDN 후보**에 대한 수치이며, 세상의 모든 CDN을 식별했다는 뜻이 아니다.

## 원본 검사기에서 수정한 부분

성능 평가용 **`bench.py`와 `BaselineCache`는 원본 그대로**다. `bench.py`의 SHA-256은 `B11CB974BADEC4504355B8E41708F5F16345A88AC4277622867C4CE7323E9ECB`로 원본과 일치한다.

`test_tasks.py`에는 다음 두 가지 호환·표시 보완만 적용했다.

1. 이 PC의 TShark 4.6.4는 DNS Boolean 필드를 `False/True`로 출력한다. 원본은 `0/1`만 세어 실제 질의 3개·응답 3개를 0개로 오인했다. 양쪽 표현을 허용하도록 바꾸었으며 **질의와 응답이 모두 있어야 통과하는 조건은 유지**했다. 수정 전 실제 실패 로그는 `out/capture-check-original.txt`에 있다.
2. `chains.json`의 메타데이터 키 3개를 ‘3 sites’라고 표시하던 부분은 `sites` 목록의 실제 길이 12개를 표시하도록 보완했다. 파일 파싱 통과 조건은 바꾸지 않았다.

[TShark 공식 문서](https://www.wireshark.org/docs/man-pages/tshark)는 필드 출력 옵션을 설명한다. 이 호환 문제를 피하려고 캡처 내용을 바꾸거나 질의·응답을 합성하지 않았다.

## 실험 환경과 한계

- 학교 인터넷에서 Task 1과 패킷 캡처를 수행했다. 캡처는 Windows PC의 WSL Ubuntu `eth0`에서 직접 수행했으며 Wireshark GUI 대신 tcpdump·tshark를 사용했다.
- Task 2 수집은 Windows Python에서 실행해 Windows의 실제 DNS 설정을 기록했다. 사용자가 학교 Wi-Fi에서 휴대폰 핫스팟으로 전환한 뒤 두 번째 run을 수집했다.
- 핫스팟에서는 CNAME 5건과 A 3건의 system DNS 질의가 시간 초과됐다. 원본에 실패를 보존했으며, 공용 DNS 두 개의 A 응답은 두 네트워크 모두 모든 사이트에서 확보했다.
- 주소 차이는 위치 외에도 조회 시간, 캐시 상태, 응답 회전, resolver 정책에 영향을 받을 수 있다. RTT나 실제 replica 위치를 측정하지 않았으므로 ‘더 가까움’까지 결론 내리지 않는다.
- `test_tasks.py`의 R2·R3·R5 수동 평가 항목은 `SKIP`으로 표시된다. 코드를 구현하고 관찰문을 써도 이 표시는 자동으로 바뀌지 않는다.

## 재현

`w03-dns/`에서 실행한다.

```bash
python3 -m unittest test_resolver test_steering test_cache
python3 task1_resolve.py --verify
python3 bench.py --yours
python3 cache_floor.py
python3 task2_steering.py --report
python3 test_tasks.py
python3 ../check.py w03
```

실제 DNS 값은 시간·환경에 따라 바뀔 수 있다. 새 측정은 `--collect --network 이름`으로 별도 run을 추가하며, 이미 저장된 결과를 현재의 결과로 덮어 쓰지 않는다.
