#!/usr/bin/env python3
import json
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# -----------------------------
# User configuration defaults
# -----------------------------
TARGET_DATES = [
    x.strip()
    for x in os.getenv("TARGET_DATES", "20260827,20260830").split(",")
    if x.strip()
]

BRANCH_NO = os.getenv("BRANCH_NO", "4062")
BRANCH_NAME = os.getenv("BRANCH_NAME", "송도(트리플스트리트)")
AREA_CD = os.getenv("AREA_CD", "35")

MOVIE_KEYWORDS = [
    x.strip()
    for x in os.getenv(
        "MOVIE_KEYWORDS",
        "오디세이,The Odyssey,Odyssey"
    ).split(",")
    if x.strip()
]

GMAIL_USER = os.getenv("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
ALERT_TO = os.getenv("ALERT_TO", "").strip() or GMAIL_USER
TEST_EMAIL = os.getenv("TEST_EMAIL", "false").lower() in {"1", "true", "yes"}

TIMEOUT = 20
STATE_FILE = Path(".alert_state.json")
RESULT_FILE = Path("result.json")
KST = ZoneInfo("Asia/Seoul")

MODERN_API = "https://www.megabox.co.kr/on/oh/ohb/SimpleBooking/selectBokdList.do"
LEGACY_API = "https://www.megabox.co.kr/on/oh/ohc/Brch/schedulePage.do"
BOOKING_URL = "https://www.megabox.co.kr/booking"
THEATER_URL = f"https://www.megabox.co.kr/theater?brchNo={BRANCH_NO}"


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", (text or "").casefold())


NORMALIZED_KEYWORDS = [normalize(x) for x in MOVIE_KEYWORDS]


def title_matches(title: str) -> bool:
    n = normalize(title)
    return bool(n) and any(k and k in n for k in NORMALIZED_KEYWORDS)


def write_result(status: str, **extra):
    payload = {
        "status": status,
        "checked_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        **extra,
    }
    RESULT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False))


def load_state():
    if not STATE_FILE.exists():
        return {"sent_dates": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"sent_dates": []}
        sent = data.get("sent_dates", [])
        if not isinstance(sent, list):
            sent = []
        return {"sent_dates": [str(x) for x in sent]}
    except Exception:
        return {"sent_dates": []}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def modern_payload(target_date):
    return {
        "areaCd1": AREA_CD,
        "areaCd2": "",
        "areaCd3": "",
        "arrMovieNo": "",
        "brchAll": "",
        "brchNo1": BRANCH_NO,
        "brchNo2": "",
        "brchNo3": "",
        "brchNoListCnt": 1,
        "brchSpcl": "",
        "movieNo1": "",
        "movieNo2": "",
        "movieNo3": "",
        "playDe": target_date,
        "sellChnlCd": "ONLINE",
        "spclbYn1": "N",
        "spclbYn2": "",
        "spclbYn3": "",
        "theabKindCd1": "",
        "theabKindCd2": "",
        "theabKindCd3": "",
    }


def headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 Chrome/130 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": BOOKING_URL,
        "Origin": "https://www.megabox.co.kr",
    }


def fetch_modern(target_date):
    r = requests.post(
        MODERN_API,
        json=modern_payload(target_date),
        headers={**headers(), "Content-Type": "application/json;charset=UTF-8"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("statCd") == -1:
        raise RuntimeError(
            f"Megabox API returned statCd=-1: {data.get('msg') or data}"
        )
    return data, "modern"


def fetch_legacy(target_date):
    form = {
        "brchNm": BRANCH_NAME,
        "brchNo": BRANCH_NO,
        "brchNo1": BRANCH_NO,
        "masterType": "brch",
        "playDe": target_date,
        "firstAt": "N",
    }
    r = requests.post(
        LEGACY_API,
        data=form,
        headers=headers(),
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json(), "legacy"


def get_schedule_rows(data):
    if not isinstance(data, dict):
        return []

    candidates = []

    mf = data.get("movieFormList")
    if isinstance(mf, list):
        candidates.extend(mf)

    mega = data.get("megaMap")
    if isinstance(mega, dict):
        mf2 = mega.get("movieFormList")
        if isinstance(mf2, list):
            candidates.extend(mf2)

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "movieFormList" and isinstance(v, list):
                    candidates.extend(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    out, seen = [], set()
    for row in candidates:
        if not isinstance(row, dict):
            continue
        key = str(
            row.get("playSchdlNo")
            or json.dumps(row, sort_keys=True, ensure_ascii=False)
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def row_title(row):
    for key in ("rpstMovieNm", "movieNm", "movieNmSearch", "movieNmKr"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def find_matches(data, target_date):
    matches = []
    for row in get_schedule_rows(data):
        title = row_title(row)
        if not title_matches(title):
            continue

        row_branch = str(row.get("brchNo") or "").strip()
        row_date = str(row.get("playDe") or "").strip()

        if row_branch and row_branch != BRANCH_NO:
            continue
        if row_date and row_date != target_date:
            continue

        if not (row.get("playSchdlNo") or row.get("playStartTime")):
            continue

        matches.append(row)
    return matches


def format_showtimes(matches):
    def key(row):
        return str(row.get("playStartTime") or "")

    lines = []
    for row in sorted(matches, key=key):
        start = row.get("playStartTime") or "시간 미상"
        end = row.get("playEndTime") or ""
        screen = row.get("theabExpoNm") or row.get("theabNm") or ""
        remain = row.get("restSeatCnt")
        total = row.get("totSeatCnt")
        title = row_title(row) or "오디세이"

        pieces = [f"{start}" + (f"–{end}" if end else "")]
        if screen:
            pieces.append(str(screen))
        if remain is not None:
            if total is not None:
                pieces.append(f"잔여 {remain}/{total}석")
            else:
                pieces.append(f"잔여 {remain}석")

        lines.append(f"- {title}: " + " | ".join(pieces))

    return "\n".join(lines)


def require_mail_secrets():
    missing = []
    if not GMAIL_USER:
        missing.append("GMAIL_USER")
    if not GMAIL_APP_PASSWORD:
        missing.append("GMAIL_APP_PASSWORD")
    if not ALERT_TO:
        missing.append("ALERT_TO")
    if missing:
        raise RuntimeError("Missing GitHub Secrets: " + ", ".join(missing))


def send_email(subject, body):
    require_mail_secrets()

    msg = EmailMessage()
    msg["From"] = GMAIL_USER
    msg["To"] = ALERT_TO
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, context=context, timeout=30
    ) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)


def pretty_date(target_date):
    dt = datetime.strptime(target_date, "%Y%m%d")
    return f"{dt.month}/{dt.day}"


def date_is_expired(target_date):
    target = datetime.strptime(target_date, "%Y%m%d").date()
    return datetime.now(KST).date() > target


def fetch_schedule(target_date):
    errors = []
    for fetcher in (fetch_modern, fetch_legacy):
        try:
            data, source = fetcher(target_date)
            return data, source, None
        except Exception as e:
            errors.append(
                f"{fetcher.__name__}: {type(e).__name__}: {e}"
            )
    return None, None, errors


def main():
    if TEST_EMAIL:
        send_email(
            "[테스트] 메가박스 오디세이 예매 알림",
            (
                "GitHub Actions → Gmail 알림 테스트가 정상 작동했습니다.\n\n"
                f"감시 대상: {BRANCH_NAME}\n"
                f"상영일: {', '.join(pretty_date(d) for d in TARGET_DATES)}\n"
                f"영화 키워드: {', '.join(MOVIE_KEYWORDS)}\n"
            ),
        )
        write_result("TEST_EMAIL_SENT")
        return 0

    state = load_state()
    sent_dates = set(state.get("sent_dates", []))

    found_dates = []
    checked_dates = []
    errors = []

    for target_date in TARGET_DATES:
        if target_date in sent_dates:
            continue
        if date_is_expired(target_date):
            continue

        data, source, fetch_errors = fetch_schedule(target_date)
        if fetch_errors:
            errors.append({
                "date": target_date,
                "errors": fetch_errors,
            })
            continue

        matches = find_matches(data, target_date)
        checked_dates.append({
            "date": target_date,
            "source": source,
            "match_count": len(matches),
        })

        if not matches:
            continue

        showtimes = format_showtimes(matches)
        date_label = pretty_date(target_date)

        subject = f"[예매 오픈] 오디세이 - 메가박스 송도 {date_label}"
        body = (
            f"메가박스 {BRANCH_NAME}의 2026년 {date_label} "
            "오디세이 상영 회차가 감지되었습니다.\n\n"
            f"{showtimes}\n\n"
            f"빠른예매: {BOOKING_URL}\n"
            f"극장 페이지: {THEATER_URL}\n\n"
            "※ 메가박스 상영시간표 데이터에 회차가 나타난 시점을 기준으로 한 "
            "자동 알림입니다. 실제 좌석/예매 가능 상태는 메가박스 화면에서 "
            "최종 확인하세요.\n"
        )

        send_email(subject, body)
        sent_dates.add(target_date)
        found_dates.append({
            "date": target_date,
            "source": source,
            "match_count": len(matches),
            "showtimes": showtimes,
        })

    state["sent_dates"] = sorted(sent_dates)
    save_state(state)

    all_finished = all(
        (d in sent_dates) or date_is_expired(d)
        for d in TARGET_DATES
    )

    if found_dates:
        status = "FOUND"
    elif errors and not checked_dates:
        status = "ERROR"
    elif all_finished:
        status = "DONE"
    else:
        status = "NOT_FOUND"

    write_result(
        status,
        found_dates=found_dates,
        checked_dates=checked_dates,
        errors=errors,
        all_finished=all_finished,
        sent_dates=sorted(sent_dates),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
