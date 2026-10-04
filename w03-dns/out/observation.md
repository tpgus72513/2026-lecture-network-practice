# Week 03 관찰

## Task 1 — DNS 계층을 직접 따라가기
- 루트 서버는 `.kr`을 누가 맡는지만 아는 계층의 꼭대기이고 재귀 질의를 해 주지 않아서, 호스트 주소 대신 `.kr`의 NS와 glue를 위임으로 돌려줬다. `www.korea.ac.kr`은 `198.41.0.4 -> 210.101.61.1 -> 163.152.1.1`의 3회 질의로 `163.152.6.10`에 도달했다.
- glue가 없는 위임이 오면 그 NS 이름을 루트부터 따로 해석하고 결과를 재사용한다. 고려대 실측은 glue가 모두 있어 추가 조회 0회였고, glue를 뺀 모의 테스트에서는 추가 NS 조회 1회가 경로에 들어갔다.
- 지정된 5개 이름은 모두 `dig`의 A 주소 집합과 일치했다(`out/verify.txt`, 5/5 ok).

## Task 2 — 패킷과 DNS steering
- 위임과 최종 응답은 같은 DNS 메시지 형식에서 채워진 칸만 달랐다. 위임 #2는 Answer 0개·Authority NS 6개(Additional glue 10개, DNS 메시지 341바이트로 최대), 최종 응답 #6은 AA=1이고 Answer에 A `163.152.6.10`이 있었다. 질의 #1과 응답 #2의 transaction ID는 모두 `0x460d`였다.
- "마지막 두 label이 다르면 제3자" 규칙은 `www.wikipedia.org -> dyna.wikimedia.org`를 잘못 분류했다(같은 Wikimedia 재단). 내가 쓴 CDN 도메인 목록 규칙도 CNAME 없이 anycast로 서비스하는 CDN이나 목록 밖 CDN은 놓칠 수 있다.
- 학교 인터넷과 휴대폰 핫스팟에서 CDN 후보 9개 중 7개가 resolver나 network에 따라 다른 주소를 줬다(같은 resolver로 network만 바꾸면 2/9). 다만 응답이 달랐다는 것이지 더 가까운 replica라는 증거는 아니며, 실패·빈 응답은 분모에서 제외했다.

## Task 3 — TTL 캐시의 정확성과 하한
- Baseline은 TTL을 무시하고 60초로 일괄 저장해, TTL이 짧은 레코드는 만료 후에도 내주고(stale 266) 긴 레코드는 너무 일찍 다시 조회했다. 레코드별 만료 시각을 지키자 upstream 325->275, stale 266->0, hit rate 67.5->72.5%가 됐다.
- 올바른 캐시의 하한은 275회다. 이름마다 첫 요청과 직전 응답의 TTL이 끝난 뒤 첫 요청에는 반드시 새 조회가 필요하고, 미리 조회해도 TTL이 그만큼 빨리 끝나므로 줄일 수 없다(`out/cache-floor.json`). 이 하한을 정하는 것은 구현이 아니라 TTL이다.
- 가장 불리한 레코드는 TTL 20초에 1,000개 중 322개를 차지한 `www.microsoft.com`이다. 