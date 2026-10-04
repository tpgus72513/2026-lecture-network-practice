# 3주차 DNS 과제 — 시작 안내

**현재 상태:** 코드·두 네트워크 측정·캡처·관찰문 작성 및 검증을 마쳤다. 단위 테스트 36개와 과제 검사 12개가 통과했다. 수동 평가 항목 3개는 `SKIP`이다.

[관찰문](w03-dns/out/observation.md) · [측정 보고서](w03-dns/out/report.md) · [구현 메모](w03-dns/IMPLEMENTATION.ko.md) · [제출 체크리스트](SUBMISSION-CHECKLIST.ko.md)

## 1. 교수님이 요구한 것

첨부 LMS 화면의 마감은 **10월 6일 23:59**, 배점은 1점이며, 제출 형식은 **본인 GitHub 저장소 URL**이다. 화면에는 시간대가 없으므로 실제 마감은 LMS 표시를 기준으로 확인한다.

세 Task 자체가 과제다. 코드와 `w03-dns/out/`의 실행 결과를 본인 저장소에 올리고, **`out/observation.md`에 Task별 2–3줄로 관찰과 이유를 설명**해야 한다.

| 과제 | 해야 할 일 | 남길 근거 |
|---|---|---|
| Task 1 | 루트 → TLD → 권한 DNS를 직접 따라가는 반복 질의 resolver 구현 | 주소·질의 경로, glue 누락 시 추가 조회, `--verify` 결과 |
| Task 2A | 본인 기기의 DNS 질의와 응답 캡처·분석 | `dns.pcapng`, 짝이 맞는 transaction ID, 위임·최종 응답의 패킷 번호, 가장 큰 DNS 응답의 바이트 수 |
| Task 2B | 지정된 12개 사이트 × 3 resolver를 두 네트워크에서 측정 | `chains.json`, 전체 CNAME 경로와 A 주소 집합, `report.md`의 분류·오분류·X/N |
| Task 3 | 레코드별 TTL을 지키는 캐시 구현 | 수정하지 않은 `bench.py --yours` 결과, 최소 upstream 질의 수와 논증 |

요구사항은 저장소의 상세 [Task 1](w03-dns/task1.md), [Task 2](w03-dns/task2.md), [Task 3](w03-dns/task3.md)를 기준으로 정리했다. 저장소 원본은 `0ee3e6622921e1ad049d82bfd7e390bf024ed6aa`이다.

## 2. 파일 읽는 순서

1. 이 문서: 과제 범위와 실행 순서.
2. `w03-dns/task1_resolve.py`: 위임을 직접 따라가는 방법과 예외 처리.
3. `w03-dns/task2_steering.py`: 두 네트워크 원본 자료를 보존하고 비교하는 방법.
4. `w03-dns/task3_cache.py`: TTL과 캐시 만료 시각의 관계.
5. `w03-dns/out/report.md`와 `observation.md`: 실제 결과와 해석.

## 3. 실행 환경

### Ubuntu / WSL

Ubuntu 터미널에서 저장소로 이동한다. 이 PC에서는 다음 경로다.

```bash
cd /mnt/c/Users/sunny/Documents/Codex/2026-09-15/dl/outputs/network-lab/w03-dns
```

필요한 도구는 Python 3, dnspython, `dig`, `tshark`이다. 캡처에는 Wireshark 또는 `tcpdump`/`dumpcap`을 사용한다.

```bash
sudo apt-get update
sudo apt-get install -y python3-dnspython dnsutils tshark tcpdump
```

### Docker

Docker Desktop을 실행한 뒤 저장소 루트에서 실행한다. 원본 Dockerfile의 dnspython 패키지 누락을 보완했다.

```bash
docker compose build
docker compose run --rm lab
cd w03-dns
```

컨테이너 내부와 호스트의 인터페이스는 다를 수 있다. 캡처를 시작한 후 실험 질의가 실제로 보이는지 확인한다.

### Windows Python

일반 Python이 설치된 PC에서는 다음 명령으로 Python 의존성을 설치한다.

```powershell
python -m pip install -r w03-dns/requirements.txt
```

Python 코드의 로직 테스트는 Windows에서도 실행된다. 교수님 `--verify`는 별도 실행 파일인 `dig`를 사용하므로 WSL/Docker에서 실행하는 편이 간단하다.

## 4. 실험 순서

### Task 1 — DNS 계층 따라가기

```bash
python3 task1_resolve.py www.korea.ac.kr
python3 task1_resolve.py --verify
```

루트는 모든 호스트 주소를 보관하는 서버가 아니다. 다음 단계에 물어볼 NS를 알려준다. NS 이름의 IP인 **glue**가 없으면, 그 NS 이름도 루트부터 별도로 조회해야 한다.

이 구현은 `dig +trace`나 시스템 resolver에 반복 질의를 맡기지 않는다. dnspython은 DNS 패킷을 만들고 보내는 역할을 하며, 다음 서버를 고르는 로직은 직접 작성한 코드에 있다.

### Task 2A — 실제 패킷 읽기

Wireshark를 사용할 경우 실제 통신이 보이는 인터페이스에서 capture filter를 `port 53`으로 설정하고 Task 1을 한 번 실행한다. 짧게 캡처하고 `out/dns.pcapng`로 저장한다.

확인할 항목:

- 질의와 응답의 `Transaction ID`가 같은가? IP·포트 방향과 질의 이름도 함께 확인한다.
- **위임 응답**: Answer는 0개이고 Authority에 NS가 있는가?
- **주소 응답**: Answer에 A 레코드가 있는가?
- 가장 큰 응답은 몇 바이트인가? DNS 메시지 크기와 Ethernet frame 크기를 구분한다.
- 파일에 실험과 무관한 개인정보나 다른 사람의 질의가 포함되지 않았는가?

WSL 인터페이스에서 직접 캡처했다면 보고서에 이를 명시한다. Windows 물리 Wi-Fi 인터페이스 캡처로 표현하지 않는다. 교수님이 Wireshark 화면 자체를 요구한다면 동일 파일을 Wireshark로 열어 확인한다.

### Task 2B — 학교와 핫스팟 비교

학교 인터넷에서 첫 결과를 저장하고, 핫스팟으로 연결을 바꾼 뒤 두 번째 결과를 저장한다. **이름만 바꾸어 같은 네트워크에서 두 번 실행하면 B3를 충족하지 않는다.**

```bash
python3 task2_steering.py --collect --network campus
# 실제로 휴대폰 핫스팟으로 전환한 뒤:
python3 task2_steering.py --collect --network phone-hotspot
python3 task2_steering.py --report
```

수집은 기존 자료를 지우지 않고, 실행 시간과 네트워크 이름을 함께 보존한다. 응답 실패와 빈 주소 집합을 구분하여 실패를 steering으로 세지 않는다.

주소 집합이 달라졌다는 사실은 DNS 응답이 달라졌다는 증거다. 그 자체로 더 가까운 서버, 짧은 지연 시간, 사용자 위치에 의한 선택을 증명하지 않는다. Google·Quad9는 anycast이므로 resolver IP가 다르다는 것만으로 지리적으로 먼 두 서버라고 할 수도 없다.

### Task 3 — 정확한 캐시

```bash
python3 bench.py --yours > out/bench.txt
python3 cache_floor.py
```

`YourCache`는 `name → (address, expires_at)`를 저장하며, `now < expires_at`일 때만 재사용한다. 만료 시각과 정확히 같아도 새로 조회한다. 캐시 hit로 TTL을 연장하지 않는다.

`cache_floor.py`는 실험의 질의 시각을 이름별로 나누어, 기존 TTL 구간으로 덮이지 않는 첫 질의마다 필요한 upstream 횟수를 계산한다. 이 값은 `YourCache`의 통계를 정답으로 복사한 것이 아니다.

## 5. 검증과 제출

`w03-dns/`에서 실행한다.

```bash
python3 -m unittest test_resolver test_steering test_cache
python3 test_tasks.py
python3 ../check.py w03
```

`SKIP`은 실행하지 못한 항목이다. `check.py`는 파일 존재·간단한 형식만 확인한다. 테스트 통과 외에도 두 네트워크 측정, 패킷 근거, 분류의 반례, 관찰문의 의미를 직접 점검한다.

원본 `.gitignore`는 모든 `out/`과 pcap 파일을 제외한다. 제출 전 캡처 내용을 검토한 뒤 **해당 주차 결과를 명시적으로 추가**한다.

```bash
# 저장소 루트에서 실행
git add Dockerfile START-HERE.ko.md SUBMISSION-CHECKLIST.ko.md w03-dns/*.py w03-dns/*.md w03-dns/requirements.txt
git add -f w03-dns/out/
git diff --cached --stat
```

본인 GitHub 저장소에 커밋·푸시한 후 웹에서 `w03-dns/out/observation.md`가 보이는지 확인한다. LMS에는 **교수님 원본 저장소가 아닌 본인 저장소 URL**을 제출한다.

### ZIP을 받아 직접 업로드하는 경우

ZIP에는 `.git` 이력과 설치한 의존성을 포함하지 않았다. 압축을 풀고 `network-lab` 폴더에서 새 저장소를 시작한다.

1. GitHub에서 본인 계정으로 빈 저장소를 만든다. 교수님이 열람 가능한 공개 설정을 사용하거나 수업에서 안내한 접근 권한을 설정한다.
2. 압축을 푼 `network-lab` 폴더에서 아래 명령을 실행한다.
3. 마지막 두 줄의 URL은 방금 만든 **본인 저장소 URL**로 바꾼다. GitHub 인증을 요청하면 본인 계정으로 로그인한다.

```bash
git init
git branch -M main
git add .
git add -f w03-dns/out/
git status --short
git commit -m "Complete Week 03 DNS lab with measurements and observations"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

위 과정은 ZIP을 새로 푼 폴더 기준이다. 이미 Git 저장소인 작업 폴더를 사용한다면 `git remote -v`로 기존 remote를 확인하고 본인 저장소에 연결한다. 이 작업에서는 사용자의 선택에 따라 GitHub 저장소 생성·업로드를 수행하지 않았다.

## 6. 측정이 막혔을 때

상세 `task2.md`의 경로 B는 공식 9판 DNS trace 사용을 허용한다. 이 경우 본인 트래픽이라고 쓰면 안 되며, [공식 trace 안내](traces/README.md)의 출처 문구와 한계를 적는다.

두 번째 네트워크가 없으면 지리적 위치가 확인된 서로 먼 resolver 비교가 대안이다. 공용 resolver 이름만으로 위치를 가정하지 않는다. 환경 때문에 수집하지 못한 결과를 임의의 수치로 채우지 않는다.

## 출처

- [교수님 실습 저장소](https://github.com/codingchild2424/2026-lecture-network-practice)
- [dnspython DNS 메시지 전송 API](https://dnspython.readthedocs.io/en/stable/query.html)
- [RFC 1035: DNS 메시지·리소스 레코드·TTL](https://www.rfc-editor.org/rfc/rfc1035)
