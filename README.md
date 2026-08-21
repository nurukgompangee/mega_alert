# 메가박스 송도 「오디세이」 Gmail 예매 알림

GitHub Actions가 5분 간격으로 메가박스 송도(트리플스트리트)의
아래 두 날짜를 동시에 확인합니다.

- **2026-08-27** — 실제 예매 오픈 감지 테스트용
- **2026-08-30** — 본래 목표 날짜

영화 제목에 아래 키워드 중 하나가 포함된 실제 상영 회차가 처음 나타나면:

- `오디세이`
- `The Odyssey`
- `Odyssey`

각 날짜별로 Gmail 알림을 **한 번씩만** 보냅니다.

즉, 8/27 예매가 먼저 열리면 8/27 알림을 보내고,
그 이후에도 8/30 감시는 계속됩니다.

---

## 1. GitHub Secrets

저장소에서:

`Settings → Secrets and variables → Actions → New repository secret`

아래 3개를 등록합니다.

| Secret | 값 |
|---|---|
| `GMAIL_USER` | 메일을 보내는 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | Google 16자리 앱 비밀번호 |
| `ALERT_TO` | 알림을 받을 Gmail 주소 |

`GMAIL_USER`와 `ALERT_TO`는 같은 주소여도 됩니다.

---

## 2. 테스트 메일

GitHub:

`Actions → Megabox Odyssey Alert → Run workflow`

`test_email`에 체크하고 실행합니다.

정상이면 아래 제목의 메일이 옵니다.

```text
[테스트] 메가박스 오디세이 예매 알림
```

---

## 3. 실제 감시 동작

기본 설정:

```yaml
TARGET_DATES: "20260827,20260830"
BRANCH_NO: "4062"
BRANCH_NAME: "송도(트리플스트리트)"
AREA_CD: "35"
MOVIE_KEYWORDS: "오디세이,The Odyssey,Odyssey"
```

확인 주기:

```yaml
- cron: "*/5 * * * *"
```

동작 예시:

```text
8/27 예매 오픈
    ↓
[예매 오픈] 오디세이 - 메가박스 송도 8/27
메일 1회 전송
    ↓
8/30 감시는 계속

8/30 예매 오픈
    ↓
[예매 오픈] 오디세이 - 메가박스 송도 8/30
메일 1회 전송
    ↓
두 날짜 모두 완료 → Workflow 자동 비활성화
```

중복 알림 여부는 `.alert_state.json`에 기록됩니다.

---

## 주의

이 프로그램은 메가박스 상영시간표 데이터에 실제 상영 회차가 나타나는 것을
"예매 오픈 감지" 신호로 사용합니다.

메가박스 측 API 또는 페이지 구조가 변경되면 수정이 필요할 수 있습니다.
실제 결제/좌석 선점은 하지 않고 **알림만 전송**합니다.
