# 제출 체크리스트

## 완료한 작업

- [x] Task 1 반복 DNS resolver 구현 및 지정 도메인 5/5 실측 비교
- [x] glue 누락·서버 실패·CNAME·순환·TCP 재시도 테스트
- [x] 본인 PC WSL 인터페이스의 실제 DNS 캡처: 3개 질의와 3개 응답
- [x] 위임 #2, A 응답 #6, transaction ID `0x460d`, 최대 DNS 응답 341바이트 기록
- [x] 12개 사이트 × 3 resolver × 학교/핫스팟 두 네트워크 수집 시도 및 원본 보존
- [x] 핫스팟 기본 DNS의 실패와 성공을 구분하고 실패 원본 보존
- [x] CDN 판정 규칙, 실제 Wikipedia/Wikimedia 오분류, steering 7/9와 2/9 분석
- [x] Task 3 캐시 개선: upstream 275, stale 0, hit rate 72.5%
- [x] 최소 upstream 275회의 독립 계산과 논증
- [x] Task별 3줄의 `w03-dns/out/observation.md`
- [x] 단위 테스트 36개 통과 (`w03-dns/out/unit-tests.txt`)
- [x] 과제 검사 12 passed, 0 failed, 3 skipped (`w03-dns/out/tests.txt`)
- [x] 제출 형식 검사 통과 (`w03-dns/out/format-check.txt`)

검사기의 tshark Boolean 호환·사이트 수 표시 보완 내용은 `w03-dns/IMPLEMENTATION.ko.md`에 공개했다. 성능 하네스 `bench.py`와 `BaselineCache`는 그대로다.

## 제출 전에 읽을 것

1. [관찰문](w03-dns/out/observation.md): 각 문장이 실제 결과를 어떻게 설명하는지 확인한다.
2. [측정 보고서](w03-dns/out/report.md): 두 network, 실패 처리, 분류 근거와 한계를 확인한다.
3. [구현 메모](w03-dns/IMPLEMENTATION.ko.md): 주요 설계 판단과 검사기 호환 수정을 확인한다.

## 남은 외부 단계

- [ ] 본인 GitHub 저장소에 코드와 `w03-dns/out/` 업로드
- [ ] GitHub 웹에서 `out/observation.md`와 캡처 파일이 보이는지 확인
- [ ] LMS에 본인 저장소 URL 제출

첨부 LMS 화면의 마감은 **10월 6일 23:59**다. 실제 적용 시간대는 LMS 표시를 확인한다. 이 작업에서 LMS 제출 버튼을 누르지는 않았다.
