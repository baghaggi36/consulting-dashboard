import base64
import html
import io
import os
import re
import zlib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitAuthError
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image
from supabase import create_client

DATA_FILE = Path(__file__).parent / "data" / "records.csv"
PRD_FILE = Path(__file__).parent / "PRD.md"
MEMO_TABLE = "client_memos"
# 화면 3에서 쓰고 읽는 업무 기록 표
WORK_TABLE = "work_records"
# 관리 화면 업무 기록 표와 CSV의 한글 열 제목. 여기에 없는 열은 표에서 읽은 이름 그대로 둔다
WORK_COLUMN_NAMES = {
    "client_name": "고객사",
    "work_date": "업무일",
    "task": "업무",
    "status": "상태",
    "next_step": "다음 할 일",
    "due_date": "마감일",
    "file_location": "파일 위치",
    "revision_note": "수정 메모",
    "important": "중요",
}
# 관리 화면 업무 기록 표에서만 숨기는 열. CSV에는 남긴다
WORK_HIDDEN_COLUMNS = ["id", "created_at"]
# 관리 화면 업무 기록 표의 은은한 칸 색. 글자는 어둡게 두어 읽히게 한다
ADMIN_TABLE_TEXT = "color: #1E293B"
ADMIN_CLIENT_BG = "#EAF4FB"
ADMIN_STATUS_BG = {"진행중": "#FFF1E0", "완료": "#E8F6EC"}
ADMIN_DUE_BG = "#FDE8EC"
# 마감일이 오늘부터 이 날수 이내이거나 지났으면 마감일 칸을 칠한다
ADMIN_DUE_ALERT_DAYS = 3
# 관리 화면 「← 돌아가기」가 돌아갈 수 있는 화면(화면 1·2·3). 그 밖이면 화면 1로 간다
ADMIN_RETURN_SCREENS = ("home", "detail", "record")
# 화면 1에서 추가한 고객사를 담는 표
CLIENT_TABLE = "clients"
# 사이드바 「연습용 기록장」에서 쓰고 읽는 표. owner(로그인한 사람의 메일)·note(글 한 줄)·created_at(남긴 시각) 열을 쓴다.
# 메일로 바꾸기 전에 쌓인 줄의 owner에는 손으로 넣은 이름이 그대로 남아 있다
PRACTICE_TABLE = "practice_notes"
# 표 전체를 읽을 때 한 번에 받는 줄 수
TABLE_PAGE_ROWS = 1000
# 화면 2 「인증 만료」 탭에서 쓰고 읽는 고객사별 인증 표
CERT_TABLE = "client_certifications"
# 인증 이름 고르는 칸의 목록. 맨 끝 「직접 입력」을 고르면 글 칸이 열린다
CERT_TYPES = ("벤처기업", "이노비즈", "메인비즈", "ISO 9001", "ISO 14001", "기업부설연구소")
CERT_CUSTOM = "직접 입력"
# 인증 D-day 색 기준(남은 날). 이 날수 이내면 노랑, CERT_ALERT_DAYS 이내면 주황, 지났으면 빨강
CERT_WARN_DAYS = 90
CERT_ALERT_DAYS = 30
# 인증 D-day 뱃지의 (바탕색, 글자색). 색이 없는 단계(91일 이상)는 회색 글자만 쓴다
CERT_DDAY_COLORS = {
    "yellow": ("#FEF9C3", "#854D0E"),
    "orange": ("#FFEDD5", "#C2410C"),
    "red": ("#FDE2E2", "#DC2626"),
    None: ("transparent", "#64748B"),
}
# 기록이 하나도 없는 고객사(새로 추가한 고객사 등)의 화면 2 칸에 보여 줄 글
NO_RECORD_TEXT = "아직 기록이 없습니다"
# 화면 3 입력 칸 6개에 대응하는 업무 기록 표의 열
RECORD_FIELDS = ("task", "status", "next_step", "due_date", "file_location", "revision_note")
# 화면 3 기존 기록 목록 상자의 높이(픽셀). 왼쪽 입력 칸 높이쯤으로 맞춘다
RECORD_LIST_HEIGHT = 680
# 첫 화면 배경 사진 위에 덮는 연한 하늘색(#F0F9FF)의 진하기. 0이면 사진 그대로, 1이면 사진이 안 보인다
LANDING_BG_OVERLAY_OPACITY = 0.45
# 첫 화면 유리 판의 흰색 진하기. 0이면 투명, 1이면 꽉 찬 흰색. 화면 1·2·3 카드와 제목 띠도 이 값을 같이 쓴다
LANDING_PANEL_OPACITY = 0.25
# 화면 1·2·3 배경 사진 위에 덮는 연한 하늘색(#F0F9FF)의 진하기. 첫 화면 것과 따로 둔다
FEATURE_BG_OVERLAY_OPACITY = 0.55
# 화면 1 「마감 챙길 업무」에서 8일 이상 남은 업무를 몇 개까지 보여 줄지
DUE_GROUP_LIMIT = 3
# 마감까지 이 날수 이내(D-7~D-day)면 「마감 임박」으로 맨 위에 주황으로 크게 보여 준다
DUE_SOON_DAYS = 7
# 마감 임박 가운데 이 날수 이내(D-3~D-day)는 조금 더 진한 주황으로 보여 준다
DUE_URGENT_DAYS = 3
# 마감 표시 뱃지의 (바탕색, 글자색). urgent=D-3 이내, soon=D-4~D-7, later=8일 이상, past=마감 지남
DUE_BADGE_COLORS = {
    "urgent": ("#FDBA74", "#9A3412"),
    "soon": ("#FFEDD5", "#C2410C"),
    "later": ("#DBEAFE", "#1D4ED8"),
    "past": ("#FDE2E2", "#B91C1C"),
}
# 고객사 표시(색 동그라미 안 첫 글자)에 돌려 쓰는 색. 흰 굵은 글씨가 잘 읽히는 진하기로 고르고,
# 「마감 지남」 표시와 헷갈리지 않도록 빨간 계열은 넣지 않는다
CLIENT_MARK_COLORS = (
    "#0284C7",  # 하늘색
    "#2563EB",  # 파랑
    "#4F46E5",  # 남보라
    "#7C3AED",  # 보라
    "#0891B2",  # 청록
    "#0D9488",  # 틸
    "#059669",  # 초록
    "#65A30D",  # 연두
    "#CA8A04",  # 노랑
    "#EA580C",  # 주황
)
# 고객사 이름 앞에 붙어 있으면 첫 글자를 고를 때 건너뛰는 말
CLIENT_NAME_PREFIX = re.compile(
    r"^\s*(\(주\)|㈜|주식회사|\(유\)|유한회사|농업회사법인|영농조합법인|\(사\)|사단법인|재단법인)\s*"
)
# 화면 2 ① 최근 작업과 ② 다음 할 일에 Supabase 기록을 몇 줄까지 보여 줄지
DETAIL_LIST_LIMIT = 4
# 오른쪽 아래 대화창에서 물은 말과 받은 답을 한 줄씩 남기는 표
CHAT_LOG_TABLE = "chat_logs"
CHAT_LOG_LIMIT = 20
# 부르는 방법(generate_content)은 공식 문서 기준
# https://ai.google.dev/gemini-api/docs/generate-content/get-started
# 모델은 공식 모델 목록의 안정판 중 가장 가벼운 flash-lite 계열
# https://ai.google.dev/gemini-api/docs/models
CHAT_MODEL = "gemini-3.5-flash-lite"
# 챗봇은 PRD.md만 읽고 사용법을 안내한다. 업무 기록은 넘기지 않는다(.claude/rules/scope.md 예외 항목).
# AI에게 주는 고정 지시문은 이 글 파일에 있다.
CHAT_RULES_FILE = Path(__file__).parent / "chatbot_rules.txt"
# 화면에 보여 주기 전 답 점검: 정확히 세 줄, 300자 이하. 벗어나면 한 번 더 묻는다.
CHAT_ANSWER_LINES = 3
CHAT_ANSWER_MAX_CHARS = 300
# 이 말로 시작하는 답은 세 줄 이하·300자 이하이면 통과시킨다.
CHAT_NO_INFO_PREFIX = "PRD에는 그 내용이 없습니다"
# 두 번 다 점검을 통과하지 못하면 답 대신 띄우는 글
CHAT_RETRY_TEXT = "다시 시도해 주세요"
# 둘러보기(보기만)로 들어온 사람이 한 번 들어와 챗봇에 물을 수 있는 횟수
GUEST_CHAT_LIMIT = 5
# 둘러보기에서 쓰기 칸·버튼 자리에 대신 보여 주는 안내
GUEST_NOTE = "둘러보기에서는 보기만 할 수 있습니다"

load_dotenv(Path(__file__).parent / ".env")


@st.cache_resource
def supabase_client(url, key):
    return create_client(url, key)


def use_demo_data():
    """둘러보기(로그인 안 함)는 가상 자료 창고, 허락된 구글 계정은 실제 자료 창고를 쓴다."""
    return is_guest()


def get_supabase():
    """둘러보기면 가상 자료 창고(SUPABASE_URL·SUPABASE_KEY, 프로젝트 my-service),
    로그인한 미카엘이면 실제 자료 창고(SUPABASE_REAL_URL·SUPABASE_REAL_KEY, 프로젝트 my-service-real)에 연결한다.
    두 창고는 완전히 따로라서 실제 자료가 둘러보기 화면에 섞여 나올 수 없다."""
    if use_demo_data():
        return supabase_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return supabase_client(os.environ["SUPABASE_REAL_URL"], os.environ["SUPABASE_REAL_KEY"])


# 가상 예시 CSV(data/records.csv)의 열. 실제 관리판에서는 이 열만 있는 빈 표를 쓴다
RECORD_COLUMNS = [
    "record_id", "client_name", "work_date", "task", "status",
    "next_step", "due_date", "file_location", "revision_note", "important",
]


def load_records():
    """가상 예시 CSV는 둘러보기에서만 읽는다. 실제 관리판에서는 빈 표를 돌려 Supabase 기록만 보이게 한다."""
    return _load_records(use_demo_data())


@st.cache_data
def _load_records(demo):
    if not demo:
        df = pd.DataFrame(columns=RECORD_COLUMNS, dtype=object)
        df["important"] = df["important"].astype(bool)
        return df
    df = pd.read_csv(DATA_FILE, dtype=str)
    df["work_date"] = pd.to_datetime(df["work_date"]).dt.date
    df["due_date"] = pd.to_datetime(df["due_date"]).dt.date
    df["important"] = df["important"] == "Y"
    return df


def is_guest():
    """로그인 화면에서 「👀 둘러보기 (보기만)」로 들어왔는지. 구글 계정으로 들어왔으면 둘러보기가 아니다.
    둘러보기에서는 쓰기 칸·버튼을 숨기고, Supabase에 쓰는 함수도 맨 앞에서 그냥 돌아간다."""
    return bool(st.session_state.get("guest")) and not st.user.is_logged_in


def admin_emails():
    """.streamlit/secrets.toml 맨 위 ADMIN_EMAILS의 메일 목록을 소문자로 돌려준다.
    파일이나 항목을 찾지 못하면 오류로 멈추지 않고 빈 목록(관리자 없음)을 돌려준다."""
    try:
        emails = st.secrets.get("ADMIN_EMAILS", [])
    except Exception:
        return []
    # 메일을 목록이 아니라 쉼표로 이은 글 한 줄로 적어 두었어도 같은 목록으로 읽는다
    if isinstance(emails, str):
        emails = emails.split(",")
    if not isinstance(emails, (list, tuple)):
        return []
    return [email.strip().lower() for email in emails if isinstance(email, str) and email.strip()]


def login_email():
    """구글 계정으로 들어온 사람의 메일을 소문자로 돌려준다. 들어오지 않았거나 메일이 없으면 빈 글이다."""
    if not st.user.is_logged_in:
        return ""
    email = st.user.get("email")
    return email.strip().lower() if isinstance(email, str) else ""


def allowed_emails():
    """관리판(실제 자료)에 들어올 수 있는 메일 목록. ADMIN_EMAILS와 ALLOWED_EMAILS(있으면)를 합친다.
    둘 다 찾지 못하면 빈 목록이라 아무도 들어오지 못한다."""
    emails = set(admin_emails())
    try:
        extra = st.secrets.get("ALLOWED_EMAILS", [])
    except Exception:
        extra = []
    if isinstance(extra, str):
        extra = extra.split(",")
    if isinstance(extra, (list, tuple)):
        emails.update(e.strip().lower() for e in extra if isinstance(e, str) and e.strip())
    return emails


def is_allowed():
    """구글 계정으로 들어온 사람의 메일이 허락된 목록에 있는지."""
    email = login_email()
    return bool(email) and email in allowed_emails()


def show_no_access():
    """허락되지 않은 구글 계정으로 들어오면 안내와 「나가기」만 보여 주고 아무 자료도 읽지 않는다."""
    with st.container(border=True):
        st.subheader("사용 권한이 없습니다")
        st.write("이 관리판은 허락된 계정만 사용할 수 있습니다. 「나가기」를 누른 뒤 둘러보기(보기만)를 이용해 주세요.")
        st.button("나가기", type="primary", on_click=st.logout)


def is_admin():
    """구글 계정으로 들어온 사람의 메일이 ADMIN_EMAILS에 있으면 관리자다.
    둘러보기 손님은 구글 계정으로 들어온 사람이 아니므로 관리자가 아니다."""
    return login_email() in admin_emails()


def seoul_today():
    """한국 시간(Asia/Seoul) 기준 오늘 날짜. 인터넷 서버의 시간대와 상관없이 한국 날짜를 돌려준다.
    아침 브리핑과 화면 1·2의 마감 계산이 모두 이 '오늘'을 함께 쓴다."""
    return pd.Timestamp.now(tz="Asia/Seoul").date()


def d_day(due):
    days = (due - seoul_today()).days
    if days == 0:
        return "D-day"
    return f"D-{days}" if days > 0 else f"D+{-days}"


def cert_d_day(expires_on):
    """인증 만료일까지 남은 날의 (D-day 글, 색 단계)를 돌려준다. 날짜는 seoul_today() 기준이다.
    31~90일 남았으면 "yellow", 0~30일이면 "orange", 지났으면 "red", 91일 이상이면 None(색 없음)."""
    days = (expires_on - seoul_today()).days
    if days < 0:
        level = "red"
    elif days <= CERT_ALERT_DAYS:
        level = "orange"
    elif days <= CERT_WARN_DAYS:
        level = "yellow"
    else:
        level = None
    return d_day(expires_on), level


def cert_d_day_badge(expires_on):
    """인증 목록에 붙일 D-day 뱃지를 HTML로 돌려준다. st.markdown(..., unsafe_allow_html=True)로 그린다."""
    label, level = cert_d_day(expires_on)
    background, color = CERT_DDAY_COLORS[level]
    return (
        f'<span style="display:inline-block;padding:1px 8px;border-radius:999px;'
        f'background:{background};color:{color};font-weight:700;">{label}</span>'
    )


def due_level(due):
    """마감일까지 남은 날로 묶음을 정한다. 날짜는 seoul_today() 기준이다.
    지났으면 "past", D-3~D-day면 "urgent", D-4~D-7이면 "soon", 8일 이상이면 "later"."""
    days = (due - seoul_today()).days
    if days < 0:
        return "past"
    if days <= DUE_URGENT_DAYS:
        return "urgent"
    if days <= DUE_SOON_DAYS:
        return "soon"
    return "later"


def due_badge(due):
    """화면 1 「마감 챙길 업무」 줄 맨 앞에 붙일 둥근 뱃지를 HTML로 돌려준다. 색은 due_level()로 정한다.
    예: 「19일 지남」, 「오늘 마감」, 「D-3」."""
    days = (due - seoul_today()).days
    if days < 0:
        label = f"{-days}일 지남"
    elif days == 0:
        label = "오늘 마감"
    else:
        label = f"D-{days}"
    background, color = DUE_BADGE_COLORS[due_level(due)]
    return (
        f'<span style="display:inline-block;padding:1px 8px;border-radius:999px;'
        f'background:{background};color:{color};font-weight:700;">{label}</span>'
    )


def morning_briefing():
    """첫 화면 「아침 브리핑」 한 줄을 HTML로 돌려준다. 예: 10월 31일 토요일 · 마감 임박 2건 · 마감 지난 일 3건.
    날짜는 화면 1과 같은 seoul_today()로 정한다.
    화면 1 「마감 챙길 업무」와 같은 Supabase 업무 기록(due_rows)으로 센다. '완료'와 마감일 없는 업무는 이미 빠져 있다.
    마감 임박은 오늘부터 DUE_SOON_DAYS일 뒤까지(D-7~D-day) 마감인 업무로, 화면 1 맨 위 주황 묶음과 같다.
    마감 임박 숫자는 둥근 주황 뱃지, 마감 지난 일 숫자는 둥근 빨간 뱃지로 보여 준다."""
    today = seoul_today()
    levels = [due_level(row.due_date) for row in due_rows()]
    overdue = levels.count("past")
    soon = levels.count("urgent") + levels.count("soon")

    weekday = "월화수목금토일"[today.weekday()]
    day_text = f"{today.month}월 {today.day}일 {weekday}요일"
    soon_text = f'마감 임박 <span class="soon">{soon}</span>건' if soon else "마감 임박 없음"
    overdue_text = (
        f'마감 지난 일 <span class="overdue">{overdue}</span>건' if overdue else "마감 지난 일 없음"
    )
    return f'<p class="briefing">{day_text} · {soon_text} · {overdue_text}</p>'


def toggle_sidebar():
    """화면 1·2·3 왼쪽 위 「☰ 메뉴」 단추: 사이드바를 보이거나 감춘다."""
    st.session_state.sidebar_open = not st.session_state.get("sidebar_open", False)


def go(screen, client=None):
    st.session_state.screen = screen
    if client is not None:
        st.session_state.client = client


def client_mark(name):
    """고객사 표시의 (색, 첫 글자)를 정한다. 색과 첫 글자 규칙은 모두 여기에만 둔다.
    색과 첫 글자 모두 '(주)'·'주식회사'·'농업회사법인' 같은 앞말과 띄어쓰기를 뺀 남은 이름으로 정한다.
    그래서 "(주)그린팜푸드"·"주식회사 그린팜푸드"·"그린팜푸드"는 같은 색, 같은 글자다.
    남은 이름 글자로만 정하므로 고객사를 새로 추가해도 다른 회사 색은 그대로다."""
    rest = name
    while (m := CLIENT_NAME_PREFIX.match(rest)) and m.end() < len(rest):
        rest = rest[m.end():]
    core = re.sub(r"\s+", "", rest)
    color = CLIENT_MARK_COLORS[zlib.crc32(core.encode("utf-8")) % len(CLIENT_MARK_COLORS)]
    return color, (core[:1].upper() if core else "?")


def client_badge(name):
    """고객사 이름 앞에 붙일 색 동그라미(흰 굵은 첫 글자)를 HTML로 돌려준다. st.markdown(..., unsafe_allow_html=True)로 그린다."""
    color, letter = client_mark(name)
    return (
        f'<span style="display:inline-flex;align-items:center;justify-content:center;'
        f"width:1.6em;height:1.6em;border-radius:50%;background:{color};"
        f"color:#FFFFFF;font-weight:800;font-size:0.8em;line-height:1;"
        f'vertical-align:middle;margin-right:0.3em;">{html.escape(letter)}</span>'
    )


def task_row(row, label, key, badge="", size=None):
    left, right = st.columns([6, 1])
    # 표시(badge)가 있으면 맨 앞에 두고, 날짜 글(label)이 비었으면 굵은 글씨를 빼고 쓴다
    head = " ".join(part for part in (badge, f"**{label}**" if label else "") if part)
    # 고객사 표시를 그리려고 HTML을 허용하므로, 입력받은 글은 그대로 글자로 보이게 바꿔 넣는다
    name = html.escape(row.client_name)
    text = f"{head} {client_badge(row.client_name)}{name} · {html.escape(str(row.next_step))}"
    # size를 주면(예: "1.15em") 그 줄 글자 크기만 바꾼다
    if size:
        text = f'<span style="font-size:{size};">{text}</span>'
    left.markdown(text, unsafe_allow_html=True)
    # 마감일이 없는 줄(None)은 「마감일 없음」으로 보여 준다
    due = "마감일 없음" if row.due_date is None else f"마감 {row.due_date}"
    left.caption(f"{due} · {row.status}")
    right.button(">", key=key, on_click=go, args=("detail", row.client_name))


def important_rows(df):
    """화면 1 「중요 표시한 업무」에 보일 업무와 버튼 이름표를 마감일 순으로 돌려준다.
    화면 2와 같은 규칙: Supabase 기록이 있는 고객사는 Supabase에서 중요 표시한 기록만,
    Supabase 기록이 없는 고객사만 CSV 중요 업무를 쓴다."""
    try:
        saved = (
            get_supabase()
            .table(WORK_TABLE)
            .select("id, client_name, next_step, due_date, status, important")
            .execute()
            .data
        )
    except Exception as e:
        st.error(f"화면 3에서 저장한 기록을 불러오지 못했습니다: {e}")
        saved = []

    saved_clients = {r["client_name"] for r in saved}
    # (정렬에 쓸 마감일, 줄, 버튼 이름표). 마감일이 없는 업무는 맨 아래로 보낸다
    items = []
    for r in saved:
        if not r["important"]:
            continue
        due = date.fromisoformat(r["due_date"]) if r["due_date"] else None
        # task_row가 CSV 줄과 같은 이름으로 읽을 수 있게 맞추고, 비어 있는 칸은 "-"로 보여 준다.
        # 마감일만은 None으로 두어 task_row가 「마감일 없음」으로 보여 주게 한다
        row = SimpleNamespace(
            client_name=r["client_name"],
            next_step=r["next_step"] or "-",
            due_date=due,
            status=r["status"] or "-",
        )
        items.append((due or date.max, row, f"star_saved_{r['id']}"))
    csv_important = df[df["important"] & ~df["client_name"].isin(saved_clients)]
    for row in csv_important.itertuples():
        items.append((row.due_date, row, f"star_{row.record_id}"))

    items.sort(key=lambda item: item[0])
    return [(row, key) for _, row, key in items]


def due_rows():
    """화면 1 「마감 챙길 업무」에 보일 업무를 Supabase 업무 기록(work_records)에서 마감일 순으로 돌려준다.
    '완료'인 업무와 마감일이 없는 업무는 뺀다. 샘플 자료(CSV)는 쓰지 않는다."""
    try:
        saved = (
            get_supabase()
            .table(WORK_TABLE)
            .select("id, client_name, next_step, due_date, status")
            .execute()
            .data
        )
    except Exception as e:
        st.error(f"화면 3에서 저장한 기록을 불러오지 못했습니다: {e}")
        return []

    # task_row가 CSV 줄과 같은 이름으로 읽을 수 있게 맞추고, 비어 있는 칸은 "-"로 보여 준다
    rows = [
        SimpleNamespace(
            id=r["id"],
            client_name=r["client_name"],
            next_step=r["next_step"] or "-",
            due_date=date.fromisoformat(r["due_date"]),
            status=r["status"] or "-",
        )
        for r in saved
        if r["due_date"] and r["status"] != "완료"
    ]
    rows.sort(key=lambda row: row.due_date)
    return rows


def show_home(df):
    st.title("화면 1 · 오늘의 업무")

    # 왼쪽 좁은 열은 고객사 선택, 가운데 넓은 자리는 두 업무 목록을 좌우로 나란히 둔다
    select_col, due_col, star_col = st.columns([1, 1.5, 1.5])

    with due_col, st.container(border=True, key="card_due"):
        st.subheader("마감 챙길 업무")
        # 맨 위: 마감 임박(D-7~D-day)을 가까운 순으로 모두 주황 뱃지와 큰 글씨로 보여 준다(D-3 이내는 더 진한 주황).
        # 그 아래: 8일 이상 남은 업무를 파란 뱃지로 평소 크기로 몇 개까지.
        # 맨 아래: 마감 지난 업무를 「지난 업무 ○건」 접는 상자에 작은 글씨로 넣는다.
        # due_rows()가 마감일 순이라 세 묶음 모두 이미 가까운(오래된) 순이다
        rows = due_rows()
        soon = [r for r in rows if due_level(r.due_date) in ("urgent", "soon")]
        later = [r for r in rows if due_level(r.due_date) == "later"]
        past = [r for r in rows if due_level(r.due_date) == "past"]

        st.markdown(
            f'<span style="color:{DUE_BADGE_COLORS["soon"][1]};font-weight:800;font-size:1.1em;">'
            f"🔥 마감 임박 (7일 이내)</span>",
            unsafe_allow_html=True,
        )
        with st.container(key="due_soon"):
            if not soon:
                st.caption("7일 안에 마감인 업무가 없습니다")
            for row in soon:
                task_row(row, "", f"due_saved_{row.id}", due_badge(row.due_date), size="1.15em")

        if later:
            st.divider()
            st.markdown("**⏳ 다가오는 마감**")
            for row in later[:DUE_GROUP_LIMIT]:
                task_row(row, "", f"due_saved_{row.id}", due_badge(row.due_date))
            hidden = len(later) - DUE_GROUP_LIMIT
            if hidden > 0:
                st.caption(f"외 {hidden}건 더")

        if past:
            st.divider()
            with st.expander(f"지난 업무 {len(past)}건"):
                for row in past:
                    task_row(row, "", f"due_saved_{row.id}", due_badge(row.due_date), size="0.85em")

    with star_col, st.container(border=True, key="card_star"):
        st.subheader("중요 표시한 업무")
        for row, key in important_rows(df):
            task_row(row, "★", key)

    with select_col, st.container(border=True, key="card_select"):
        st.subheader("확인할 고객사 선택")
        names = client_names(df)
        # 처음에는 아무 고객사도 고르지 않은 상태로 두고, 고객사를 추가하면 그 고객사를 골라 둔다
        st.session_state.setdefault("home_client", None)
        client = st.selectbox(
            "확인할 고객사 선택",
            options=names,
            key="home_client",
            placeholder="고객사를 선택하세요",
            label_visibility="collapsed",
        )
        if st.button("확인", type="primary", use_container_width=True):
            if client is None:
                st.warning("확인할 고객사를 먼저 선택해 주세요")
            else:
                go("detail", client)
                st.rerun()
        st.caption("선택 후 확인 → 화면 2로 이동")

        if is_guest():
            st.caption(GUEST_NOTE)
            return
        st.text_input("새 고객사 이름", key="new_client_name", placeholder="예: 하늘상사")
        st.button("고객사 추가", use_container_width=True, on_click=add_client, args=(names,))
        # 바로 앞에서 추가한 결과를 한 번만 보여 준다
        message = st.session_state.pop("client_add_message", None)
        if message:
            kind, text = message
            {"success": st.success, "warning": st.warning}.get(kind, st.error)(text)


def client_names(df):
    """화면 1 선택 목록에 보일 고객사 이름. CSV 고객사 뒤에 clients 표에 추가한 고객사를 겹치지 않게 붙인다."""
    names = list(df["client_name"].unique())
    try:
        rows = (
            get_supabase()
            .table(CLIENT_TABLE)
            .select("client_name")
            .order("created_at")
            .execute()
            .data
        )
    except Exception as e:
        st.error(f"추가한 고객사를 불러오지 못했습니다: {e}")
        return names
    for r in rows:
        if r["client_name"] not in names:
            names.append(r["client_name"])
    return names


def add_client(existing):
    """「새 고객사 이름」 칸의 이름을 clients 표에 넣고, 선택 칸에서 그 고객사를 골라 둔다.
    비어 있거나 이미 있는 이름이면 넣지 않는다. 결과 안내는 다시 그린 화면 1에 보여 주도록 남겨 둔다."""
    if is_guest():
        return
    name = st.session_state.get("new_client_name", "").strip()
    if not name:
        st.session_state.client_add_message = ("warning", "추가할 고객사 이름을 먼저 입력해 주세요")
        return
    if name in existing:
        st.session_state.client_add_message = ("warning", f"이미 있는 고객사입니다: {name}")
        return
    try:
        get_supabase().table(CLIENT_TABLE).insert({"client_name": name}).execute()
    except Exception as e:
        # 그사이 같은 이름이 들어갔으면, 이름이 겹치지 않게 만든 표가 거절한다
        if "23505" in str(e) or "duplicate" in str(e).lower():
            st.session_state.client_add_message = ("warning", f"이미 있는 고객사입니다: {name}")
        else:
            st.session_state.client_add_message = ("error", f"고객사를 추가하지 못했습니다: {e}")
        return
    st.session_state.new_client_name = ""
    st.session_state.home_client = name
    st.session_state.client_add_message = ("success", "고객사를 추가했습니다")


def show_memos(client):
    with st.container(border=True, key="card_memo"):
        st.subheader("⑤ 한 줄 메모")

        # 둘러보기에서는 메모 입력 칸 대신 안내만 두고, 아래 메모 목록은 그대로 보여 준다
        submitted = False
        if is_guest():
            st.caption(GUEST_NOTE)
        else:
            with st.form("memo_form", clear_on_submit=True):
                memo = st.text_input(
                    "한 줄 메모",
                    max_chars=300,
                    placeholder="이 고객사에 대해 남길 메모를 한 줄로 적어 주세요",
                    label_visibility="collapsed",
                )
                submitted = st.form_submit_button("남기기", use_container_width=True)

        if submitted:
            if not memo.strip():
                st.warning("남길 메모를 먼저 입력해 주세요")
            else:
                try:
                    get_supabase().table(MEMO_TABLE).insert(
                        {"client_name": client, "memo": memo.strip()}
                    ).execute()
                    st.success("메모를 남겼습니다")
                except Exception as e:
                    st.error(f"메모를 저장하지 못했습니다: {e}")

        try:
            memos = (
                get_supabase()
                .table(MEMO_TABLE)
                .select("memo, created_at")
                .eq("client_name", client)
                .order("created_at", desc=True)
                .execute()
                .data
            )
        except Exception as e:
            st.error(f"지난 메모를 불러오지 못했습니다: {e}")
            return

        if not memos:
            st.caption("아직 남긴 메모가 없습니다")
        for m in memos:
            written = pd.to_datetime(m["created_at"]).tz_convert("Asia/Seoul")
            st.write(f"{written:%Y-%m-%d %H:%M} · {m['memo']}")


def latest_work(client, csv_latest):
    """CSV 기록과 화면 3에서 Supabase에 저장한 기록 중 더 최근 것 하나의 작업일·작업내용·진행상태를 돌려준다.
    CSV 기록이 없으면 csv_latest는 None이고, 둘 다 없으면 None을 돌려준다."""
    latest = None
    if csv_latest is not None:
        latest = {
            "work_date": csv_latest.work_date,
            "task": csv_latest.task,
            "status": csv_latest.status,
        }
    try:
        rows = (
            get_supabase()
            .table(WORK_TABLE)
            .select("work_date, task, status")
            .eq("client_name", client)
            .order("work_date", desc=True)
            # 같은 날 두 번 저장했으면 나중에 넣은 것을 고른다
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
    except Exception as e:
        st.error(f"화면 3에서 저장한 기록을 불러오지 못했습니다: {e}")
        return latest

    if rows:
        saved = rows[0]
        saved_date = date.fromisoformat(saved["work_date"])
        # 작업일이 같으면 화면 3에서 저장한 기록을 더 최근 것으로 본다
        if latest is None or saved_date >= latest["work_date"]:
            latest = {
                "work_date": saved_date,
                "task": saved["task"],
                # 진행상태를 비우고 저장했으면 "-"로 보여 준다
                "status": saved["status"] or "-",
            }
    return latest


def saved_detail(client):
    """화면 3에서 Supabase에 저장한 이 고객사의 기록에서 화면 2의 최근 작업·다음 할 일 목록과 마감일을 고른다.
    최근 작업은 기록을 최근 순으로, 다음 할 일은 다음 할 일이 적힌 기록을 최근 순으로 DETAIL_LIST_LIMIT개까지 담는다.
    마감일은 마감일이 적힌 기록 중 가장 최근 것이고, 없으면 None이다.
    저장한 기록이 하나도 없거나 불러오지 못하면 None을 돌려주어 CSV를 쓰게 한다."""
    try:
        rows = (
            get_supabase()
            .table(WORK_TABLE)
            .select("work_date, task, status, next_step, due_date")
            .eq("client_name", client)
            .order("work_date", desc=True)
            # 같은 날 두 번 저장했으면 나중에 넣은 것을 더 최근으로 본다
            .order("created_at", desc=True)
            .execute()
            .data
        )
    except Exception as e:
        st.error(f"화면 3에서 저장한 기록을 불러오지 못했습니다: {e}")
        return None

    if not rows:
        return None
    next_rows = [r for r in rows if (r["next_step"] or "").strip()]
    due_row = next((r for r in rows if r["due_date"]), None)
    return {
        "recent": rows[:DETAIL_LIST_LIMIT],
        "next": next_rows[:DETAIL_LIST_LIMIT],
        "due_date": date.fromisoformat(due_row["due_date"]) if due_row else None,
    }


def show_detail(df):
    st.title("화면 2 · 고객사 현황")

    client = st.session_state.client
    records = df[df["client_name"] == client].sort_values("work_date", ascending=False)
    # 화면 1에서 새로 추가한 고객사는 CSV 기록이 없다
    latest = latest_work(client, None if records.empty else records.iloc[0])
    # Supabase 기록이 하나라도 있으면 다음 할 일·마감일은 거기서만 고르고, 하나도 없으면 None이라 CSV를 쓴다
    saved = saved_detail(client)
    open_tasks = records[records["status"] != "완료"].sort_values("due_date")

    # 맨 위 한 줄: 요약과 화면 이동 버튼.
    # 버튼 두 개를 나란히 두어 이 줄이 높아지지 않게 하고, 요약과 가운데를 맞춘다
    summary_col, nav_col = st.columns([2, 1], vertical_alignment="center")

    with summary_col, st.container(border=True, key="card_summary"):
        status = f"`{latest['status']}`" if latest else NO_RECORD_TEXT
        summary = f"**고객사명** {client_badge(client)}{html.escape(client)} · **진행상태** {status}"
        if saved is not None:
            # 마감일이 적힌 Supabase 기록 중 가장 최근 것, 없으면 "없음"
            due = saved["due_date"]
            summary += f" · **마감일** {f'{due} ({d_day(due)})' if due else '없음'}"
        elif not open_tasks.empty:
            # Supabase 기록이 하나도 없는 고객사만 지금처럼 CSV에서 가장 가까운 마감일을 쓴다
            due = open_tasks.iloc[0]["due_date"]
            summary += f" · **마감일** {due} ({d_day(due)})"
        elif records.empty:
            summary += f" · **마감일** {NO_RECORD_TEXT}"
        st.markdown(summary, unsafe_allow_html=True)

    with nav_col:
        record_btn_col, home_btn_col = st.columns(2)

        with record_btn_col:
            st.button(
                "업무 기록 작성·수정",
                type="primary",
                use_container_width=True,
                on_click=go,
                args=("record", client),
            )
            st.caption("업무 기록 작성·수정 → 화면 3")

        with home_btn_col:
            st.button("목록으로", use_container_width=True, on_click=go, args=("home",))
            st.caption("목록으로 → 화면 1")

    # 가운데는 탭 두 개, 오른쪽 열은 한 줄 메모
    main_col, memo_col = st.columns([3, 1])

    with main_col:
        now_tab, history_tab, cert_tab = st.tabs(["지금 현황", "파일·수정 이력", "인증 만료"])

        with now_tab:
            recent_col, next_col = st.columns(2)

            with recent_col, st.container(border=True, key="card_recent"):
                st.subheader("① 최근 작업")
                if saved is not None:
                    # Supabase 기록을 최근 순으로 몇 개까지, 한 줄에 "날짜 · 작업내용 · 진행상태"
                    for r in saved["recent"]:
                        st.write(f"{r['work_date']} · {r['task']} · {r['status'] or '-'}")
                elif latest:
                    # Supabase 기록이 하나도 없는 고객사만 지금처럼 CSV의 가장 최근 작업을 보여 준다
                    st.write(latest["task"])
                    st.caption(f"작성일 {latest['work_date']}")
                else:
                    st.write(NO_RECORD_TEXT)

            with next_col, st.container(border=True, key="card_next"):
                st.subheader("② 다음 할 일")
                if saved is not None:
                    # 다음 할 일이 적힌 Supabase 기록을 최근 순으로 몇 개까지, 없으면 "없음"
                    for r in saved["next"]:
                        # 그 기록에 마감일이 없으면 괄호는 뺀다
                        due = f" (마감 {r['due_date']})" if r["due_date"] else ""
                        st.write(f"☐ {r['next_step']}{due}")
                    if not saved["next"]:
                        st.write("없음")
                elif records.empty:
                    st.write(NO_RECORD_TEXT)
                else:
                    # Supabase 기록이 하나도 없는 고객사만 지금처럼 CSV의 남은 할 일을 모두 보여 준다
                    for row in open_tasks.itertuples():
                        st.write(f"☐ {row.next_step} (마감 {row.due_date})")

        with history_tab:
            file_col, revision_col = st.columns(2)

            with file_col, st.container(border=True, key="card_file"):
                st.subheader("③ 파일 위치")
                st.caption("오른쪽 위 복사 아이콘으로 경로를 복사합니다")
                for row in records.itertuples():
                    st.code(row.file_location, language=None)
                if records.empty:
                    st.write(NO_RECORD_TEXT)

            with revision_col, st.container(border=True, key="card_revision"):
                st.subheader("④ 수정내용")
                for row in records.itertuples():
                    st.write(f"{row.work_date} · {row.revision_note}")
                if records.empty:
                    st.write(NO_RECORD_TEXT)

        with cert_tab:
            show_certs(client)

    with memo_col:
        show_memos(client)

    show_client_settings(client)


# 고객사 이름을 바꾸거나 지울 때 함께 고치는 표(모두 client_name 열로 고객사를 가리킨다)
CLIENT_LINKED_TABLES = (WORK_TABLE, MEMO_TABLE, CERT_TABLE)


def client_exists(name):
    """clients 표에 같은 이름의 고객사가 있는지."""
    rows = get_supabase().table(CLIENT_TABLE).select("id").eq("client_name", name).execute().data
    return bool(rows)


def linked_counts(client):
    """이 고객사에 딸린 업무 기록·메모·인증 수."""
    counts = {}
    for table in CLIENT_LINKED_TABLES:
        counts[table] = (
            get_supabase().table(table).select("id", count="exact", head=True)
            .eq("client_name", client).execute().count or 0
        )
    return counts


def rename_client(client):
    """고객사 이름을 바꾼다. 업무 기록·메모·인증에 적힌 이름도 함께 바꾼다.
    새 이름이 비었거나, 같거나, 이미 있는 고객사면 바꾸지 않는다."""
    if is_guest():
        return
    new = st.session_state.get("rename_client_to", "").strip()
    if not new or new == client:
        st.session_state.client_setting_message = ("warning", "바꿀 새 이름을 입력해 주세요")
        return
    try:
        if client_exists(new):
            st.session_state.client_setting_message = ("warning", f"이미 있는 고객사 이름입니다: {new}")
            return
        for table in CLIENT_LINKED_TABLES:
            get_supabase().table(table).update({"client_name": new}).eq("client_name", client).execute()
        if client_exists(client):
            get_supabase().table(CLIENT_TABLE).update({"client_name": new}).eq("client_name", client).execute()
        else:
            get_supabase().table(CLIENT_TABLE).insert({"client_name": new}).execute()
    except Exception as e:
        st.session_state.client_setting_message = ("error", f"이름을 바꾸지 못했습니다: {e}")
        return
    st.session_state.client = new
    st.session_state.home_client = new
    st.session_state.rename_client_to = ""
    st.session_state.client_setting_message = ("success", f"「{client}」을(를) 「{new}」(으)로 바꿨습니다")


def delete_client(client):
    """고객사와 그 고객사의 업무 기록·메모·인증을 모두 지우고 화면 1로 돌아간다.
    「함께 지워짐을 확인했습니다」에 체크해야만 지운다."""
    if is_guest():
        return
    if not st.session_state.get("delete_client_confirm"):
        st.session_state.client_setting_message = ("warning", "지우려면 먼저 확인 칸에 체크해 주세요")
        return
    try:
        for table in CLIENT_LINKED_TABLES:
            get_supabase().table(table).delete().eq("client_name", client).execute()
        get_supabase().table(CLIENT_TABLE).delete().eq("client_name", client).execute()
    except Exception as e:
        st.session_state.client_setting_message = ("error", f"고객사를 지우지 못했습니다: {e}")
        return
    st.session_state.delete_client_confirm = False
    st.session_state.pop("home_client", None)
    st.session_state.client_add_message = ("success", f"고객사 「{client}」와 딸린 기록을 지웠습니다")
    go("home")


def show_client_settings(client):
    """화면 2 맨 아래: 고객사 이름 고치기·지우기. 둘러보기에서는 보이지 않는다."""
    if is_guest():
        return
    message = st.session_state.pop("client_setting_message", None)
    with st.expander("⚙️ 고객사 이름 고치기·지우기", expanded=message is not None):
        if message:
            kind, text = message
            {"success": st.success, "warning": st.warning}.get(kind, st.error)(text)
        rename_col, delete_col = st.columns(2)
        with rename_col:
            st.markdown("**이름 고치기**")
            st.text_input("새 고객사 이름", key="rename_client_to", placeholder=client)
            st.caption("업무 기록·메모·인증에 적힌 이름도 함께 바뀝니다")
            st.button("이름 바꾸기", key="rename_client_btn", on_click=rename_client, args=(client,))
        with delete_col:
            st.markdown("**고객사 지우기**")
            try:
                counts = linked_counts(client)
                st.write(
                    f"업무 기록 {counts[WORK_TABLE]}건 · 메모 {counts[MEMO_TABLE]}건 · "
                    f"인증 {counts[CERT_TABLE]}건이 함께 지워집니다. 되돌릴 수 없습니다."
                )
            except Exception as e:
                st.error(f"딸린 기록 수를 세지 못했습니다: {e}")
            st.checkbox("함께 지워짐을 확인했습니다", key="delete_client_confirm")
            st.button("고객사 지우기", key="delete_client_btn", on_click=delete_client, args=(client,))


def pick_cert(client, cert):
    """인증 목록에서 고른 인증을 어느 고객사 것인지와 함께 기억해 두고, 입력 칸에 그 값을 채운다."""
    st.session_state.picked_cert = {"client": client, **cert}
    if cert["cert_name"] in CERT_TYPES:
        st.session_state.cert_type = cert["cert_name"]
        st.session_state.cert_custom = ""
    else:
        st.session_state.cert_type = CERT_CUSTOM
        st.session_state.cert_custom = cert["cert_name"]
    st.session_state.cert_expires = date.fromisoformat(cert["expires_on"])


def clear_cert_form():
    """고른 인증을 잊고 인증 입력 칸을 비운다."""
    st.session_state.pop("picked_cert", None)
    st.session_state.cert_type = None
    st.session_state.cert_custom = ""
    st.session_state.cert_expires = None


def save_cert(client):
    """인증 입력 칸의 값을 저장한다. 고른 인증이 있으면 그 인증을 고치고, 없으면 지금 보고 있는 고객사의 인증으로 새로 넣는다.
    인증 이름은 앞뒤 빈칸을 지워 저장한다. 결과 안내는 다시 그린 탭에 보여 주도록 남겨 둔다."""
    if is_guest():
        return
    cert_type = st.session_state.get("cert_type")
    if cert_type == CERT_CUSTOM:
        name = st.session_state.get("cert_custom", "").strip()
    else:
        name = (cert_type or "").strip()
    expires = st.session_state.get("cert_expires")
    if not name:
        st.session_state.cert_message = ("warning", "인증 이름을 먼저 고르거나 입력해 주세요")
        return
    if expires is None:
        st.session_state.cert_message = ("warning", "만료일을 먼저 넣어 주세요")
        return

    values = {"cert_name": name, "expires_on": expires.isoformat()}
    picked = st.session_state.get("picked_cert")
    try:
        if picked and picked["client"] == client:
            changed = (
                get_supabase().table(CERT_TABLE).update(values).eq("id", picked["id"]).execute().data
            )
            # 고치기 허용이 없으면 오류 없이 아무 줄도 바뀌지 않는다
            if not changed:
                st.session_state.cert_message = (
                    "error",
                    "인증을 고치지 못했습니다: 바뀐 인증이 없습니다."
                    f" Supabase {CERT_TABLE} 표의 고치기(UPDATE) 허용을 확인해 주세요",
                )
                return
            done = "인증을 고쳤습니다"
        else:
            get_supabase().table(CERT_TABLE).insert({"client_name": client, **values}).execute()
            done = "인증을 저장했습니다"
    except Exception as e:
        # 한 고객사에 같은 이름의 인증은 하나만 두도록 만든 표가 거절한다
        if "23505" in str(e) or "duplicate" in str(e).lower():
            st.session_state.cert_message = (
                "warning",
                f"이미 있는 인증입니다: {name}. 목록에서 고르기로 고쳐 주세요",
            )
        else:
            st.session_state.cert_message = ("error", f"인증을 저장하지 못했습니다: {e}")
        return
    clear_cert_form()
    st.session_state.cert_message = ("success", done)


def ask_delete_cert(cert_id):
    """「삭제」를 누른 인증을 기억해 두어, 그 자리에서 한 번 더 묻게 한다."""
    st.session_state.deleting_cert_id = cert_id
    st.session_state.pop("cert_message", None)


def cancel_delete_cert():
    """지우기를 그만두고 묻는 글을 감춘다."""
    st.session_state.pop("deleting_cert_id", None)


def delete_cert(cert_id):
    """인증 하나를 Supabase 인증 표에서 지운다. 고른 인증이었다면 입력 칸도 비운다."""
    st.session_state.pop("deleting_cert_id", None)
    if is_guest():
        return
    try:
        deleted = get_supabase().table(CERT_TABLE).delete().eq("id", cert_id).execute().data
    except Exception as e:
        st.session_state.cert_message = ("error", f"인증을 지우지 못했습니다: {e}")
        return
    # 지우기 허용이 없으면 오류 없이 아무 줄도 지워지지 않는다
    if not deleted:
        st.session_state.cert_message = (
            "error",
            "인증을 지우지 못했습니다: 지워진 인증이 없습니다."
            f" Supabase {CERT_TABLE} 표의 지우기(DELETE) 허용을 확인해 주세요",
        )
        return
    picked = st.session_state.get("picked_cert")
    if picked and picked["id"] == cert_id:
        clear_cert_form()
    st.session_state.cert_message = ("success", "인증을 지웠습니다")


def show_certs(client):
    """화면 2 「인증 만료」 탭. 지금 보고 있는 고객사의 인증을 만료일이 가까운 순으로 D-day와 함께 보여 주고,
    아래 입력 칸에서 넣고 고친다. 인증은 언제나 지금 보고 있는 고객사의 것으로 저장된다."""
    picked = st.session_state.get("picked_cert")
    # 다른 고객사에서 골라 둔 인증은 잊고 입력 칸을 비운다
    if picked and picked["client"] != client:
        clear_cert_form()
        picked = None
    # 다른 화면에 다녀오면 입력 칸 값은 지워지고 고른 인증만 남는다. 그때는 입력 칸을 고른 인증으로 다시 채운다
    elif picked and "cert_type" not in st.session_state:
        pick_cert(client, picked)
    st.session_state.setdefault("cert_type", None)
    st.session_state.setdefault("cert_custom", "")
    st.session_state.setdefault("cert_expires", None)

    with st.container(border=True, key="card_cert"):
        st.subheader("인증 만료")
        st.markdown(f"{client_badge(client)}{html.escape(client)}의 인증", unsafe_allow_html=True)

        # 바로 앞에서 저장하거나 지운 결과를 한 번만 보여 준다
        message = st.session_state.pop("cert_message", None)
        if message:
            kind, text = message
            {"success": st.success, "warning": st.warning}.get(kind, st.error)(text)

        try:
            rows = (
                get_supabase()
                .table(CERT_TABLE)
                .select("id, cert_name, expires_on")
                .eq("client_name", client)
                .order("expires_on")
                .execute()
                .data
            )
        except Exception as e:
            st.error(f"인증을 불러오지 못했습니다: {e}")
            rows = []

        if not rows:
            st.caption("아직 넣은 인증이 없습니다")
        deleting_id = st.session_state.get("deleting_cert_id")
        for cert in rows:
            expires = date.fromisoformat(cert["expires_on"])
            with st.container(border=True):
                left, right = st.columns([6, 1])
                left.markdown(
                    f"**{html.escape(cert['cert_name'])}** · 만료 {expires} {cert_d_day_badge(expires)}",
                    unsafe_allow_html=True,
                )
                # 둘러보기에서는 목록만 보여 주고 「고르기」·「삭제」는 두지 않는다
                if is_guest():
                    continue
                right.button("고르기", key=f"cert_pick_{cert['id']}", on_click=pick_cert, args=(client, cert))
                right.button("삭제", key=f"cert_delete_{cert['id']}", on_click=ask_delete_cert, args=(cert["id"],))
                if picked and picked["id"] == cert["id"]:
                    st.success("아래 입력 칸에 불러왔어요. 고친 뒤 저장을 누르세요")
                # 「삭제」를 누른 인증이면 바로 지우지 않고 한 번 더 묻는다
                if deleting_id == cert["id"]:
                    st.warning("이 인증을 지울까요? 지우면 되돌릴 수 없어요")
                    confirm_col, cancel_col = st.columns(2)
                    confirm_col.button(
                        "지우기",
                        key=f"cert_confirm_delete_{cert['id']}",
                        use_container_width=True,
                        on_click=delete_cert,
                        args=(cert["id"],),
                    )
                    cancel_col.button(
                        "취소",
                        key=f"cert_cancel_delete_{cert['id']}",
                        use_container_width=True,
                        on_click=cancel_delete_cert,
                    )

        st.divider()
        if is_guest():
            st.caption(GUEST_NOTE)
            return
        if picked:
            st.info(f"고른 인증: {picked['cert_name']} · 만료 {picked['expires_on']}")
        type_col, custom_col, expires_col = st.columns(3)
        type_col.selectbox(
            "인증 이름",
            options=(*CERT_TYPES, CERT_CUSTOM),
            key="cert_type",
            placeholder="인증을 고르세요",
        )
        # 「직접 입력」을 고른 때만 글 칸을 연다
        if st.session_state.cert_type == CERT_CUSTOM:
            custom_col.text_input("직접 입력", key="cert_custom", placeholder="예: 녹색인증")
        expires_col.date_input("만료일", key="cert_expires")
        save_col, new_col = st.columns(2)
        save_col.button(
            "저장", type="primary", use_container_width=True, on_click=save_cert, args=(client,)
        )
        new_col.button("새로 쓰기", use_container_width=True, on_click=clear_cert_form)


def pick_record(client, record):
    """기존 기록 목록에서 고른 기록을 어느 고객사 것인지와 함께 기억해 두고, 입력 칸 6개와 중요 표시에 그 값을 채운다."""
    st.session_state.picked_record = {"client": client, **record}
    for field in RECORD_FIELDS:
        value = record[field]
        if field == "due_date":
            value = date.fromisoformat(value) if value else None
        else:
            # 비어 있는 칸은 빈 글자로 채운다
            value = value or ""
        st.session_state[f"rec_{field}"] = value
    st.session_state.rec_important = bool(record.get("important"))


def clear_record_form():
    """고른 기록을 잊고 입력 칸 6개를 비우고 중요 표시를 끈다."""
    st.session_state.pop("picked_record", None)
    for field in RECORD_FIELDS:
        st.session_state[f"rec_{field}"] = None if field == "due_date" else ""
    st.session_state.rec_important = False


def ask_delete_record(record_id):
    """「삭제」를 누른 기록을 기억해 두어, 그 자리에서 한 번 더 묻게 한다."""
    st.session_state.deleting_record_id = record_id
    st.session_state.pop("delete_message", None)


def cancel_delete_record():
    """지우기를 그만두고 묻는 글을 감춘다."""
    st.session_state.pop("deleting_record_id", None)


def delete_record(record_id):
    """기존 기록 하나를 Supabase 업무 기록 표에서 지운다. 고른 기록이었다면 입력 칸도 비운다.
    결과는 다시 그린 목록 위에 보여 주도록 남겨 둔다."""
    st.session_state.pop("deleting_record_id", None)
    if is_guest():
        return
    try:
        deleted = (
            get_supabase().table(WORK_TABLE).delete().eq("id", record_id).execute().data
        )
    except Exception as e:
        st.session_state.delete_message = ("error", f"기록을 지우지 못했습니다: {e}")
        return
    # 지우기 허용이 없으면 오류 없이 아무 줄도 지워지지 않는다
    if not deleted:
        st.session_state.delete_message = (
            "error",
            "기록을 지우지 못했습니다: 지워진 기록이 없습니다."
            " Supabase work_records 표의 지우기(DELETE) 허용을 확인해 주세요",
        )
        return
    picked = st.session_state.get("picked_record")
    if picked and picked["id"] == record_id:
        clear_record_form()
    st.session_state.delete_message = ("success", "기록을 지웠습니다")


def show_work_records(client):
    """화면 3에 이 고객사의 기존 업무 기록을 최근 것부터 보여 준다."""
    with st.container(border=True, key="card_records"):
        st.subheader("기존 기록 목록")
        # 어느 고객사의 기록인지 고객사 표시와 이름으로 알려 준다
        st.markdown(f"{client_badge(client)}{html.escape(client)}의 기록", unsafe_allow_html=True)

        try:
            rows = (
                get_supabase()
                .table(WORK_TABLE)
                .select(
                    "id, work_date, task, status, next_step, due_date,"
                    " file_location, revision_note, important"
                )
                .eq("client_name", client)
                .order("work_date", desc=True)
                # 같은 날 기록은 나중에 넣은 것이 위로 오게 한다
                .order("created_at", desc=True)
                .execute()
                .data
            )
        except Exception as e:
            st.error(f"기존 기록을 불러오지 못했습니다: {e}")
            return

        # 바로 앞에서 지운 결과를 한 번만 보여 준다
        message = st.session_state.pop("delete_message", None)
        if message:
            kind, text = message
            (st.success if kind == "success" else st.error)(text)

        if not rows:
            st.caption("아직 남긴 업무 기록이 없습니다")
        picked = st.session_state.get("picked_record")
        deleting_id = st.session_state.get("deleting_record_id")
        # 목록이 길어도 화면이 늘어나지 않게, 왼쪽 입력 칸 높이쯤 되는 상자 안에서만 굴려 본다
        with st.container(height=RECORD_LIST_HEIGHT, border=False):
            for raw in rows:
                # 비어 있는 칸은 None 대신 "-"로 보여 준다
                r = {k: "-" if v is None else v for k, v in raw.items()}
                with st.container(border=True):
                    left, right = st.columns([6, 1])
                    # 중요 표시한 기록은 앞에 ★을 붙인다
                    star = "★ " if raw.get("important") else ""
                    left.markdown(f"{star}**{r['work_date']}** · {r['task']} `{r['status']}`")
                    left.caption(f"다음 할 일 {r['next_step']} · 마감 {r['due_date']}")
                    left.caption(f"파일 위치 {r['file_location']}")
                    left.caption(f"수정내용 {r['revision_note']}")
                    # 둘러보기에서는 목록만 보여 주고 「고르기」·「삭제」는 두지 않는다
                    if is_guest():
                        continue
                    right.button(
                        "고르기",
                        key=f"pick_{r['id']}",
                        on_click=pick_record,
                        # 입력 칸에는 "-"가 아니라 원래 값을 채운다
                        args=(client, raw),
                    )
                    # 이 목록은 화면 3에서 저장한 Supabase 기록만 보여 주므로, CSV 샘플 기록에는 삭제 버튼이 붙지 않는다
                    right.button(
                        "삭제",
                        key=f"delete_{r['id']}",
                        on_click=ask_delete_record,
                        args=(raw["id"],),
                    )
                    # 고른 항목 자리에서 입력 칸에 불러왔다고 알려 준다
                    if picked and picked["client"] == client and picked["id"] == raw["id"]:
                        st.success("왼쪽 입력 칸에 불러왔어요. 고친 뒤 저장을 누르세요")
                    # 「삭제」를 누른 기록이면 바로 지우지 않고 한 번 더 묻는다
                    if deleting_id == raw["id"]:
                        st.warning("이 기록을 지울까요? 지우면 되돌릴 수 없어요")
                        confirm_col, cancel_col = st.columns(2)
                        confirm_col.button(
                            "지우기",
                            key=f"confirm_delete_{r['id']}",
                            use_container_width=True,
                            on_click=delete_record,
                            args=(raw["id"],),
                        )
                        cancel_col.button(
                            "취소",
                            key=f"cancel_delete_{r['id']}",
                            use_container_width=True,
                            on_click=cancel_delete_record,
                        )


def show_record_form(client):
    """화면 3의 업무 기록 입력 칸 6개와 저장 버튼. 저장하면 고른 기록은 바꾸고, 아니면 Supabase 업무 기록 표에 새로 넣는다."""
    with st.container(border=True, key="card_record_form"):
        st.subheader("업무 기록 입력")

        # 둘러보기에서는 입력 칸·「새로 쓰기」·「저장」을 두지 않는다
        if is_guest():
            st.caption(GUEST_NOTE)
            return

        # 다른 고객사에서 골라 둔 기록은 보여 주지 않는다
        picked = st.session_state.get("picked_record")
        if picked and picked["client"] == client:
            # 다른 화면에 다녀오면 입력 칸 값은 지워지고 고른 기록만 남는다.
            # 그때는 입력 칸을 고른 기록으로 다시 채워, 안내와 입력 칸이 어긋나지 않게 한다
            if any(
                f"rec_{field}" not in st.session_state
                for field in (*RECORD_FIELDS, "important")
            ):
                pick_record(client, picked)
            st.info(f"고른 기록: {picked['work_date']} · {picked['task']}")

        st.button("새로 쓰기", on_click=clear_record_form)

        # 마감일 칸은 처음에 비워 둔다
        st.session_state.setdefault("rec_due_date", None)
        # 중요 표시는 처음에 꺼 둔다
        st.session_state.setdefault("rec_important", False)

        with st.form("record_form"):
            task = st.text_area(
                "작업내용", placeholder="오늘 처리한 작업을 적어 주세요", key="rec_task"
            )
            status = st.text_input(
                "진행상태", placeholder="예: 진행중, 완료", key="rec_status"
            )
            next_step = st.text_input("다음 할 일", key="rec_next_step")
            due_date = st.date_input("마감일", key="rec_due_date")
            file_location = st.text_input(
                "파일 위치",
                placeholder="예: D:\\고객사\\고객사명\\...",
                key="rec_file_location",
            )
            revision_note = st.text_area("수정내용", key="rec_revision_note")
            important = st.checkbox("⭐ 중요 표시", key="rec_important")
            submitted = st.form_submit_button("저장", type="primary", use_container_width=True)

        if not submitted:
            return
        if not task.strip():
            st.warning("작업내용을 먼저 입력해 주세요")
            return

        # 비운 칸은 빈 글자 대신 비어 있음(None)으로 넣는다
        values = {
            "task": task.strip(),
            "status": status.strip() or None,
            "next_step": next_step.strip() or None,
            "due_date": due_date.isoformat() if due_date else None,
            "file_location": file_location.strip() or None,
            "revision_note": revision_note.strip() or None,
            "important": important,
        }

        # 이 고객사의 기록을 골라 두었으면 그 기록을 바꾸고, 아니면 새로 넣는다
        if picked and picked["client"] == client:
            try:
                changed = (
                    get_supabase()
                    .table(WORK_TABLE)
                    .update(values)
                    .eq("id", picked["id"])
                    .execute()
                    .data
                )
            except Exception as e:
                st.error(f"업무 기록을 고치지 못했습니다: {e}")
                return
            # 고치기 허용이 없으면 오류 없이 아무 줄도 바뀌지 않는다
            if not changed:
                st.error(
                    "업무 기록을 고치지 못했습니다: 바뀐 기록이 없습니다."
                    " Supabase work_records 표의 고치기(UPDATE) 허용을 확인해 주세요"
                )
                return
            # 다시 그릴 때 「고른 기록」 줄에도 고친 값이 보이게 한다
            st.session_state.picked_record = {"client": client, **changed[0]}
            st.success("업무 기록을 고쳤습니다")
            return

        try:
            get_supabase().table(WORK_TABLE).insert(
                {
                    "client_name": client,
                    "work_date": seoul_today().isoformat(),
                    **values,
                }
            ).execute()
            st.success("업무 기록을 저장했습니다")
        except Exception as e:
            st.error(f"업무 기록을 저장하지 못했습니다: {e}")


def show_record():
    st.title("화면 3 · 업무 기록 작성·수정")

    client = st.session_state.client

    # 맨 위: 고객사명과 화면 이동 버튼
    name_col, nav_col = st.columns([3, 1], vertical_alignment="center")

    with name_col, st.container(border=True, key="card_client_name"):
        st.markdown(f"**고객사명** {client}")

    with nav_col:
        st.button(
            "고객사 현황으로", use_container_width=True, on_click=go, args=("detail", client)
        )
        st.caption("고객사 현황으로 → 화면 2")

    # 왼쪽 열은 입력 칸, 가운데 열은 기존 기록 목록
    form_col, list_col = st.columns([2, 3])

    with form_col:
        show_record_form(client)

    with list_col:
        show_work_records(client)


# 첫 화면 아이콘 세 개의 선 그림(24×24 칸 기준). 바깥 글꼴이나 인터넷에서 불러오지 않는다
LANDING_ICONS = {
    # 고객사 현황: 건물
    "building": (
        '<rect x="4" y="3" width="16" height="18" rx="2"/>'
        '<path d="M10 21v-4h4v4"/>'
        '<path d="M8 7h2M14 7h2M8 11h2M14 11h2"/>'
    ),
    # 업무 기록: 연필
    "pencil": (
        '<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>'
        '<path d="M14.5 5.5l3 3"/>'
    ),
    # 마감 관리: 시계
    "clock": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 7v5l3 2"/>'
    ),
}


# 첫 화면 배경 사진. 원본(autumn_sky.jpg.jpg)을 가로 1920픽셀로 줄인 복사본을 쓴다
LANDING_BG_FILE = Path(__file__).parent / "assets" / "autumn_sky.jpg"
# 첫 화면 카드 맨 아래 「시작하기」 밑에 두는 로고와 서명 한 줄
LANDING_LOGO_FILE = Path(__file__).parent / "assets" / "logo_gonggam_mark_only.png"
# 제목 앞과 브라우저 탭에 쓰는 共感 & TSG 한자 로고(원본: 미카엘이 준 PSD를 PNG로 바꾼 것)
TITLE_LOGO_FILE = Path(__file__).parent / "assets" / "logo_gonggam_hanja.png"
LANDING_SIGNATURE = "(주)공감경영컨설팅 박학기 본부장"
# 서명 바로 아래 작은 회색 글씨로 보여 주는 마지막 고친 날과 고친 내용
LANDING_UPDATED_NOTE = "마지막으로 고친 날 2026-11-11 · 이름을 미카엘 DESK로 바꾸고 실제 관리판으로 전환"
# 오른쪽 아래 챗봇 단추에 넣는 로봇 그림. 파일이 없거나 못 읽으면 원래 ✨ 마크를 보여 준다
CHATBOT_FACE_FILE = Path(__file__).parent / "assets" / "bot_robot.png"
# 오른쪽 위 「이름 님」 앞에 두는 내 사진. 파일이 없거나 못 읽으면 👤를 보여 준다
USER_PHOTO_FILE = Path(__file__).parent / "assets" / "me.jpg"
# 동그란 단추 안에서 그림을 얼마나 키우고(배경 크기) 어디를 가운데에 둘지(가로 세로 위치).
# 로봇 그림은 동그라미가 그림 폭의 약 96%이고 바깥은 투명하다. 동그라미가 단추를 꽉 채워 바깥 틈이 보이지 않도록 105%로 키운다
CHATBOT_FACE_ZOOM = "105%"
CHATBOT_FACE_POSITION = "center"


@st.cache_data
def image_data_url(path):
    """사진 파일을 꾸밈 설정이나 <img>에 바로 넣을 수 있는 data URL로 만든다. 한 번 만든 것은 다시 쓴다.
    .png는 PNG로, 나머지는 JPEG로 알린다."""
    kind = "png" if Path(path).suffix.lower() == ".png" else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(Path(path).read_bytes()).decode()


@st.cache_data
def small_photo_url(path, size=256):
    """그림을 가로세로 size픽셀 안으로 줄여 data URL로 만든다. 못 읽으면 None. 한 번 만든 것은 다시 쓴다.
    투명한 부분이 있는 그림(PNG 등)은 투명함을 살려 PNG로, 나머지는 JPEG로 만든다."""
    try:
        with Image.open(path) as img:
            img.thumbnail((size, size))
            buffer = io.BytesIO()
            if img.mode in ("RGBA", "LA") or "transparency" in img.info:
                img.convert("RGBA").save(buffer, "PNG", optimize=True)
                kind = "png"
            else:
                img.convert("RGB").save(buffer, "JPEG", quality=85)
                kind = "jpeg"
    except OSError:
        return None
    return f"data:image/{kind};base64," + base64.b64encode(buffer.getvalue()).decode()


def line_icon_url(shapes):
    """선 그림을 강조색 SVG로 감싸, 꾸밈 설정에 바로 넣을 수 있는 data URL로 만든다.
    st.html은 <svg> 태그를 지우므로 그림을 이렇게 넣는다."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="#0284C7" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        + shapes
        + "</svg>"
    )
    return "data:image/svg+xml," + quote(svg)


def show_landing(df):
    """서비스를 소개하는 첫 화면. 「시작하기」를 누르면 화면 1로 간다.
    한 줄 소개 아래에 화면 1 「마감 챙길 업무」와 같은 Supabase 업무 기록으로 센 「아침 브리핑」을 보여 준다.
    색은 이 화면을 그릴 때만 넣으므로 기능 화면에는 퍼지지 않는다."""
    st.html(
        """
        <style>
        [data-testid="stApp"] {
            background: #F0F9FF;
            color: #1E293B;
        }
        /* 배경 사진의 하늘이 위에서부터 보이도록 맨 위 머리줄을 투명하게 한다 */
        [data-testid="stHeader"] {
            background: transparent;
        }
        /* 제목·한 줄 소개·아이콘·「시작하기」를 올리는 유리 판.
           흰색 진하기는 아래 배경 사진 꾸밈에서 LANDING_PANEL_OPACITY로 넣는다 */
        .st-key-landing_panel {
            max-width: 760px;
            margin: 40px auto;
            padding: 40px 32px;
            border: 1px solid rgba(255, 255, 255, 0.6);
            border-radius: 20px;
            box-shadow: 0 8px 32px rgba(30, 41, 59, 0.15);
            -webkit-backdrop-filter: blur(10px);
            backdrop-filter: blur(10px);
        }
        .landing {
            max-width: 960px;
            margin: 0 auto 32px;
            text-align: center;
            color: #1E293B;
        }
        .landing h1 {
            font-size: 48px;
            font-weight: 800;
            color: #1E293B;
            margin: 0 0 16px;
        }
        .landing h1 span {
            color: #0284C7;
        }
        /* 제목 앞 공감 로고: 글자 높이에 맞추고 글자와 가운데를 맞춘다 */
        .landing h1 .title-logo {
            height: 1.5em;
            width: auto;
            vertical-align: middle;
            margin-right: 14px;
        }
        .landing .intro {
            font-size: 20px;
            line-height: 1.6;
            margin: 0 auto 12px;
            max-width: 720px;
        }
        /* 아침 브리핑 한 줄. 마감 임박 숫자는 연한 주황, 마감 지난 일 숫자는 연한 빨간 바탕의 작은 둥근 뱃지로 보인다 */
        .landing .briefing {
            font-size: 18px;
            font-weight: 600;
            color: #1E293B;
            margin: 0 auto 32px;
        }
        .landing .briefing .soon {
            display: inline-block;
            min-width: 1.6em;
            padding: 1px 8px;
            margin: 0 2px;
            border-radius: 999px;
            background: #FFEDD5;
            color: #C2410C;
            font-weight: 800;
            line-height: 1.4;
        }
        .landing .briefing .overdue {
            display: inline-block;
            min-width: 1.6em;
            padding: 1px 8px;
            margin: 0 2px;
            border-radius: 999px;
            background: #FDE2E2;
            color: #DC2626;
            font-weight: 800;
            line-height: 1.4;
        }
        /* 하는 일 세 가지: 선 모양 아이콘을 가로로 나란히 두고 아래에 이름만 쓴다 */
        .landing .icons {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 48px;
        }
        .landing .icon {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 12px;
            width: 120px;
        }
        .landing .icon .circle {
            width: 88px;
            height: 88px;
            border-radius: 50%;
            background: #FFFFFF;
            border: 1px solid #BAE6FD;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .landing .glyph {
            display: block;
            width: 40px;
            height: 40px;
            background-position: center;
            background-size: contain;
            background-repeat: no-repeat;
        }
        .landing .icon p {
            margin: 0;
            font-size: 16px;
            font-weight: 600;
            color: #1E293B;
        }
        /* 「시작하기」 버튼은 아이콘 세 개가 놓인 폭(120px × 3 + 간격 48px × 2)에 맞춰 가운데 둔다 */
        .st-key-start {
            width: 456px;
            max-width: 100%;
            margin: 0 auto;
        }
        .st-key-start button {
            background: #0284C7;
            border-color: #0284C7;
            color: #FFFFFF;
            font-size: 18px;
            font-weight: 700;
            padding: 12px 0;
        }
        .st-key-start button:hover {
            background: #0369A1;
            border-color: #0369A1;
            color: #FFFFFF;
        }
        /* 「시작하기」 밑 로고와 서명 한 줄: 가운데에 나란히 두고, 문구는 작은 회색 글씨 */
        .landing-sign {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            margin: 20px auto 0;
            text-align: center;
        }
        .landing-sign img {
            height: 36px;
            width: auto;
        }
        /* 서명 바로 아래 마지막 고친 날 한 줄: 서명보다 작은 회색 글씨 */
        .landing-updated {
            margin: 6px auto 0;
            text-align: center;
            font-size: 13px;
            color: #64748B;
        }
        .landing-sign p {
            margin: 0;
            font-size: 17px;
            color: #475569;
        }
        /* 첫 화면에서는 사이드바와 그 여닫는 단추를 감춘다 */
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none;
        }
        @media (max-width: 640px) {
            .landing h1 { font-size: 34px; }
            .landing .intro { font-size: 17px; }
            .landing .briefing { font-size: 17px; }
            .landing .icons { gap: 24px; }
            .landing .icon { width: 90px; }
            .st-key-start { width: 318px; }
            /* 좁은 화면에서는 로고를 위, 문구를 아래 두 줄로 둔다 */
            .landing-sign { flex-direction: column; gap: 6px; }
            .landing-sign img { height: 32px; }
            .landing-sign p { font-size: 16px; }
            .landing-updated { font-size: 12px; }
            .st-key-landing_panel { margin: 16px auto; padding: 24px 16px; }
        }
        </style>
        """
    )

    # 배경 사진은 이 저장소의 파일을 꾸밈 설정에 직접 넣는다(바깥 인터넷에서 불러오지 않는다).
    # 화면 전체를 덮고, 하늘이 보이도록 위쪽에 맞춘다.
    # 그 위에 연한 하늘색을 반투명하게 덮어 사진이 은은하게 비치게 한다
    overlay = f"rgba(240, 249, 255, {LANDING_BG_OVERLAY_OPACITY})"
    st.html(
        f"""
        <style>
        [data-testid="stApp"] {{
            background-image:
                linear-gradient({overlay}, {overlay}),
                url("{image_data_url(str(LANDING_BG_FILE))}");
            background-size: cover;
            background-position: center top;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        .st-key-landing_panel {{
            background: rgba(255, 255, 255, {LANDING_PANEL_OPACITY});
        }}
        </style>
        """
    )

    # 아이콘 그림은 꾸밈 설정의 배경 그림으로 넣는다
    icon_css = "".join(
        f'.landing .glyph-{name} {{ background-image: url("{line_icon_url(shapes)}"); }}'
        for name, shapes in LANDING_ICONS.items()
    )
    st.html(f"<style>{icon_css}</style>")

    with st.container(key="landing_panel"):
        st.html(
            f"""
        <div class="landing">
            <h1><img class="title-logo" src="{image_data_url(str(TITLE_LOGO_FILE))}" alt="共感 로고"><span>미카엘</span> DESK</h1>
            <p class="intro">대표의 입장에서 생각하고, 실행까지 함께합니다</p>
            {morning_briefing()}
            <div class="icons">
                <div class="icon">
                    <div class="circle"><span class="glyph glyph-building"></span></div>
                    <p>Clients</p>
                </div>
                <div class="icon">
                    <div class="circle"><span class="glyph glyph-pencil"></span></div>
                    <p>Work Log</p>
                </div>
                <div class="icon">
                    <div class="circle"><span class="glyph glyph-clock"></span></div>
                    <p>Deadlines</p>
                </div>
            </div>
        </div>
        """
        )

        with st.container(key="start"):
            st.button("Start", use_container_width=True, on_click=go, args=("home",))

        st.html(
            f"""
        <div class="landing-sign">
            <img src="{image_data_url(str(LANDING_LOGO_FILE))}" alt="공감 로고">
            <p>{html.escape(LANDING_SIGNATURE)}</p>
        </div>
        <p class="landing-updated">{html.escape(LANDING_UPDATED_NOTE)}</p>
        """
        )


def ask_chatbot(api_key, messages):
    """고정 지시문과 PRD.md를 규칙으로 붙이고, 지금까지의 대화를 Gemini에 보내 받은 답 글을 돌려준다."""
    rules = CHAT_RULES_FILE.read_text(encoding="utf-8").strip()
    client = genai.Client(api_key=api_key)
    contents = [
        types.Content(role=m["role"], parts=[types.Part(text=m["text"])])
        for m in messages
    ]
    config = types.GenerateContentConfig(
        system_instruction=rules
        + "\n\n--- PRD.md ---\n"
        + PRD_FILE.read_text(encoding="utf-8")
    )
    response = client.models.generate_content(
        model=CHAT_MODEL, contents=contents, config=config
    )
    return response.text


def answer_passes_check(answer):
    """답이 정확히 세 줄이고 300자(줄바꿈 제외) 이하인지 본다. 빈 줄은 세지 않는다.
    "PRD에는 그 내용이 없습니다"로 시작하는 답은 세 줄 이하이면 된다."""
    text = (answer or "").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    if len(text.replace("\n", "")) > CHAT_ANSWER_MAX_CHARS:
        return False
    if text.startswith(CHAT_NO_INFO_PREFIX):
        return len(lines) <= CHAT_ANSWER_LINES
    return len(lines) == CHAT_ANSWER_LINES


def ask_chatbot_checked(api_key, messages):
    """답을 점검해 벗어나면 한 번 더 묻고, 두 번 다 벗어나면 「다시 시도해 주세요」를 돌려준다."""
    for _ in range(2):
        answer = ask_chatbot(api_key, messages)
        if answer_passes_check(answer):
            return answer
    return CHAT_RETRY_TEXT


def save_chat_log(question, answer):
    """물은 말과 받은 답을 Supabase 대화 기록 표에 남긴다. 둘러보기의 질문은 남기지 않는다."""
    if is_guest():
        return
    get_supabase().table(CHAT_LOG_TABLE).insert(
        {"question": question, "answer": answer}
    ).execute()


def show_chat_logs():
    """대화창 아래에 지난 대화 목록을 최근 것부터 보여 준다."""
    st.markdown("**지난 대화**")
    try:
        logs = (
            get_supabase()
            .table(CHAT_LOG_TABLE)
            .select("question, answer, created_at")
            .order("created_at", desc=True)
            .limit(CHAT_LOG_LIMIT)
            .execute()
            .data
        )
    except Exception as e:
        st.error(f"지난 대화를 불러오지 못했습니다: {e}")
        return

    if not logs:
        st.caption("아직 남은 대화가 없습니다")
        return

    with st.container(height=240):
        for log in logs:
            asked = pd.to_datetime(log["created_at"]).tz_convert("Asia/Seoul")
            with st.expander(f"{asked:%m-%d %H:%M} · {log['question']}"):
                st.markdown(log["answer"].strip().replace("\n", "  \n"))


@st.fragment
def chat_panel():
    """대화창 안쪽. 이 부분만 다시 그려서 화면 1·2는 그대로 둔다."""
    st.markdown("**관리판 안내 챗봇**")
    st.caption("PRD.md를 읽고 서비스에 대해 답해 드려요")

    messages = st.session_state.setdefault("chat_messages", [])
    # 챗봇 말풍선 아이콘은 오른쪽 아래 챗봇 단추와 같은 로봇 그림. 파일이 없거나 못 읽으면 원래 ✨를 쓴다
    bot_face = small_photo_url(str(CHATBOT_FACE_FILE), 96) if CHATBOT_FACE_FILE.is_file() else None
    bot_avatar = bot_face or "✨"

    with st.container(height=320):
        if not messages:
            with st.chat_message("assistant", avatar=bot_avatar):
                st.write("안녕하세요! 이 관리판에 대해 궁금한 점을 물어보세요.")
        for m in messages:
            role, avatar = ("user", None) if m["role"] == "user" else ("assistant", bot_avatar)
            with st.chat_message(role, avatar=avatar):
                if m["role"] == "model":
                    st.caption("AI가 쓴 초안입니다 · 확인하고 쓰세요")
                    # 마크다운은 줄바꿈 하나를 공백으로 합치므로, 문장마다 줄이 보이게 바꾼다.
                    st.markdown(m["text"].strip().replace("\n", "  \n"))
                else:
                    st.write(m["text"])

    # 둘러보기에서는 한 번 들어와 GUEST_CHAT_LIMIT번까지만 묻는다. 다 쓰면 입력 칸 대신 안내만 둔다
    guest = is_guest()
    asked = st.session_state.get("guest_chat_count", 0)
    if guest and asked >= GUEST_CHAT_LIMIT:
        st.info(f"둘러보기에서는 {GUEST_CHAT_LIMIT}번까지 물어볼 수 있어요")
        return

    with st.form("chat_form", clear_on_submit=True, border=False):
        question = st.text_input(
            "질문",
            placeholder="예: 화면 2에서는 무엇을 볼 수 있나요?",
            label_visibility="collapsed",
        )
        sent = st.form_submit_button("보내기", use_container_width=True)
    if guest:
        st.caption(f"둘러보기 질문은 저장하지 않아요 · 남은 횟수 {GUEST_CHAT_LIMIT - asked}번")

    if sent:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            st.error(".env에 GEMINI_API_KEY를 먼저 채워 주세요.")
        elif not question.strip():
            st.warning("물어볼 말을 먼저 적어 주세요.")
        else:
            messages.append({"role": "user", "text": question.strip()})
            with st.spinner("답을 쓰는 중입니다..."):
                try:
                    answer = ask_chatbot_checked(api_key, messages)
                except Exception as error:
                    messages.pop()
                    st.error(f"Gemini를 부르다 문제가 생겼습니다: {error}")
                else:
                    answer = answer or "(받은 답이 비어 있습니다.)"
                    messages.append({"role": "model", "text": answer})
                    if guest:
                        st.session_state.guest_chat_count = asked + 1
                        st.rerun(scope="fragment")
                    try:
                        save_chat_log(question.strip(), answer)
                        st.session_state.pop("chat_log_error", None)
                    except Exception as error:
                        # 다시 그린 뒤에도 보이도록 남겨 둔다. 대화 자체는 그대로 이어진다.
                        st.session_state.chat_log_error = str(error)
                    st.rerun(scope="fragment")

    if "chat_log_error" in st.session_state:
        st.warning(f"대화를 기록하지 못했습니다: {st.session_state.chat_log_error}")

    # 지난 대화 목록은 미카엘의 질문이라 둘러보기에서는 숨긴다
    if guest:
        return
    st.divider()
    show_chat_logs()


def save_practice_note():
    """연습용 기록장의 글 한 줄을 로그인한 메일과 함께 practice_notes 표에 넣는다. 메일이나 글이 비어 있으면 넣지 않는다.
    결과 안내는 다시 그린 기록장에 보여 주도록 남겨 둔다."""
    if is_guest():
        return
    owner = login_email()
    note = st.session_state.get("practice_note", "").strip()
    if not owner:
        st.session_state.practice_message = ("warning", "구글 계정 메일을 찾지 못해 글을 남길 수 없습니다")
        return
    if not note:
        st.session_state.practice_message = ("warning", "남길 글을 한 줄 적어 주세요")
        return
    try:
        get_supabase().table(PRACTICE_TABLE).insert({"owner": owner, "note": note}).execute()
    except Exception as e:
        st.session_state.practice_message = ("error", f"글을 저장하지 못했습니다: {e}")
        return
    st.session_state.practice_note = ""
    st.session_state.practice_message = ("success", "글을 남겼습니다")


def read_all_rows(make_query):
    """make_query가 만든 조회의 줄을 모두 돌려준다.
    표가 한 번에 주는 줄 수에 제한이 있어, 더 받을 줄이 없을 때까지 이어서 받는다."""
    rows = []
    while True:
        page = make_query().range(len(rows), len(rows) + TABLE_PAGE_ROWS - 1).execute().data
        if not page:
            return rows
        rows.extend(page)


def read_practice_notes():
    """연습용 기록장 글을 최근 것부터 돌려준다. 관리자는 전체를, 일반 사용자는 owner가 내 메일인 줄만 표에서 받는다."""
    admin = is_admin()

    def make_query():
        query = get_supabase().table(PRACTICE_TABLE).select("owner, note, created_at")
        if not admin:
            query = query.eq("owner", login_email())
        return query.order("created_at", desc=True)

    return read_all_rows(make_query)


def show_practice_notes():
    """화면 1·2·3 사이드바의 접었다 펴는 「연습용 기록장」. 글 한 줄을 로그인한 메일로 남긴다.
    아래 목록은 최근 것부터 보여 준다. 관리자는 전체 줄과 owner를, 일반 사용자는 내 줄과 구글 계정 이름을 본다."""
    with st.sidebar.expander("📝 연습용 기록장"):
        st.text_input("글 한 줄", key="practice_note", max_chars=300)
        st.button("남기기", key="practice_save", use_container_width=True, on_click=save_practice_note)

        # 바로 앞에서 남긴 결과를 한 번만 보여 준다
        message = st.session_state.pop("practice_message", None)
        if message:
            kind, text = message
            {"success": st.success, "warning": st.warning}.get(kind, st.error)(text)

        try:
            notes = read_practice_notes()
        except Exception as e:
            st.error(f"지난 글을 불러오지 못했습니다: {e}")
            return

        if not notes:
            st.caption("남긴 글이 아직 없습니다")
        admin = is_admin()
        name = st.user.get("name") or "사용자"
        for n in notes:
            # 일반 사용자 목록에는 메일을 쓰지 않는다. 관리자 목록의 owner는 메일이거나 전에 쌓인 이름이다
            who = n["owner"] if admin else name
            if n["created_at"]:
                # 시간대가 없는 시각이 와도 세계 표준시로 보고 한국 시간으로 바꾼다
                written = pd.to_datetime(n["created_at"], utc=True).tz_convert("Asia/Seoul")
                st.write(f"{written:%Y-%m-%d %H:%M} · {who} · {n['note']}")
            else:
                st.write(f"{who} · {n['note']}")


def show_chatbot():
    """오른쪽 아래에 떠 있는 동그란 챗봇 아이콘. 누르면 대화창이 열린다."""
    st.html(
        """
        <style>
        .st-key-chatbot {
            position: fixed;
            right: 32px;
            /* 오른쪽 아래 검정 「Manage app」 단추(약 44px 높이) 위로 올라오게 띄운다 */
            bottom: 84px;
            width: auto !important;
            z-index: 1000;
        }
        /* 챗봇 단추: 이전 크기(96px)의 70%. 안의 ✨ 그림도 같은 비율로 줄인다 */
        .st-key-chatbot button {
            width: 67px;
            height: 67px;
            padding: 0;
            border-radius: 50%;
            font-size: 34px;
            background: #ffd43b;
            border: none;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
        }
        .st-key-chatbot button p {
            font-size: 34px;
            line-height: 1;
            margin: 0;
        }
        /* 큰 단추가 화면 맨 아래 글과 버튼을 가리지 않도록, 끝까지 내리면 단추 높이만큼 빈자리가 남게 한다 */
        [data-testid="stMainBlockContainer"] {
            padding-bottom: 168px;
        }
        /* 휴대폰처럼 좁은 화면에서는 처음 크기의 1.2배로 줄이고, 가장자리 여백도 줄인다 */
        @media (max-width: 640px) {
            .st-key-chatbot {
                right: 20px;
                bottom: 72px;
            }
            .st-key-chatbot button {
                width: 54px;
                height: 54px;
                font-size: 27px;
            }
            .st-key-chatbot button p {
                font-size: 27px;
            }
            [data-testid="stMainBlockContainer"] {
                padding-bottom: 140px;
            }
        }
        .st-key-chatbot button:hover {
            transform: scale(1.08);
        }
        /* 단추 오른쪽 작은 ⌄ 화살표를 감춘다. 지금 Streamlit은 화살표를 글자 아이콘으로 aria-hidden 칸에 넣는다.
           예전 판처럼 svg 그림으로 넣는 경우도 함께 감춘다 */
        .st-key-chatbot button svg,
        .st-key-chatbot button [aria-hidden="true"],
        .st-key-chatbot button [data-testid="stIconMaterial"] {
            display: none;
        }
        /* 챗봇 대화창: 화면 1·2·3 카드와 같은 간유리 */
        [data-testid="stPopoverBody"] {
            width: 360px;
            max-width: calc(100vw - 32px);
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(255, 255, 255, 0.7);
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(30, 41, 59, 0.18);
            -webkit-backdrop-filter: blur(12px);
            backdrop-filter: blur(12px);
            color: #1E293B;
        }
        </style>
        """
    )
    # 그림이 있으면 단추를 그림으로 꽉 채우고 ✨ 글자는 감춘다. 없으면 위 꾸밈 그대로 노란 ✨ 마크가 보인다.
    # 파일이 없을 때는 기억해 두지 않아, 나중에 파일을 넣으면 바로 사진이 나온다
    face = small_photo_url(str(CHATBOT_FACE_FILE)) if CHATBOT_FACE_FILE.is_file() else None
    if face:
        st.html(
            f"""
            <style>
            .st-key-chatbot button {{
                /* 그림 뒤에 아무 색도 깔지 않아, 그림 가장자리로 흰 테나 노란 테가 비치지 않게 한다 */
                background-color: transparent;
                background-image: url("{face}");
                background-size: {CHATBOT_FACE_ZOOM};
                background-position: {CHATBOT_FACE_POSITION};
                background-repeat: no-repeat;
                /* 그림 자체에 가는 흰 선이 있어 단추 테두리는 따로 두지 않는다 */
                border: none;
                box-shadow: 0 4px 14px rgba(30, 41, 59, 0.25);
            }}
            .st-key-chatbot button p {{
                opacity: 0;
            }}
            /* 대화창 안 챗봇 말풍선 아이콘: 그림 전체를 잘라 내지 않고 칸에 맞춰 넣고, 동그랗게 보이게 한다 */
            [data-testid="stPopoverBody"] img[alt="assistant avatar"] {{
                object-fit: contain;
                border-radius: 50%;
            }}
            </style>
            """
        )
    with st.container(key="chatbot"):
        with st.popover("✨", help="관리판 안내 챗봇"):
            chat_panel()


def start_google_login():
    """구글 로그인 창으로 보낸다. 로그인 설정(.streamlit/secrets.toml의 [auth])이 아직 없으면 안내만 남긴다."""
    try:
        st.login("google")
    except StreamlitAuthError as error:
        st.session_state.login_error = hide_auth_secrets(str(error))


def hide_auth_secrets(message):
    """로그인 오류 문장에 [auth] 아래 값(client_secret, cookie_secret 등)이 섞여 있으면 ***로 가린다."""
    values = []

    def collect(section):
        for value in section.values():
            if isinstance(value, Mapping):
                collect(value)
            elif isinstance(value, str) and value:
                values.append(value)

    try:
        collect(st.secrets.get("auth", {}))
    except Exception:
        pass
    for value in sorted(values, key=len, reverse=True):
        message = message.replace(value, "***")
    return " ".join(message.split())


def start_guest():
    """로그인 없이 보기만 하는 둘러보기로 들어간다. 첫 화면부터 보여 준다."""
    st.session_state.guest = True
    st.session_state.screen = "landing"


def end_guest():
    """둘러보기를 마치고 로그인 화면으로 돌아간다. 다음 사람이 처음부터 보도록 화면 위치와 챗봇 대화도 지운다."""
    for key in ("guest", "screen", "client", "chat_messages", "guest_chat_count"):
        st.session_state.pop(key, None)


def show_login_gate():
    """구글 계정으로 들어오기 전에는 이 안내 화면만 보여 주고, 아래 화면들은 그리지 않는다."""
    st.html(
        """
        <style>
        [data-testid="stApp"] {
            background: #F0F9FF;
            color: #1E293B;
        }
        .st-key-login_panel {
            max-width: 480px;
            margin: 80px auto;
            padding: 40px 32px;
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 20px;
            box-shadow: 0 8px 32px rgba(30, 41, 59, 0.12);
            text-align: center;
        }
        .st-key-login_panel h2 {
            color: #1E293B;
            margin: 0 0 8px;
        }
        .st-key-login_panel p {
            color: #475569;
        }
        </style>
        """
    )
    with st.container(key="login_panel"):
        st.html("<h2>미카엘 DESK</h2><p>구글 계정으로 들어오면 관리판이 열립니다</p>")
        st.button("구글 계정으로 들어가기", type="primary", use_container_width=True, on_click=start_google_login)
        st.button("👀 둘러보기 (보기만)", use_container_width=True, on_click=start_guest)
        login_error = st.session_state.pop("login_error", None)
        if login_error:
            st.error("구글 로그인 설정이 아직 없습니다. .streamlit/secrets.toml의 [auth] 칸을 채운 뒤 다시 눌러 주세요")
            # Streamlit이 알려 준 실제 원인 문장. 키 값은 hide_auth_secrets로 가린 뒤 보여 준다
            st.caption(f"Streamlit 오류 문장: {login_error}")


def show_admin_record_count():
    """관리 화면의 업무 기록 수. 관리자가 아니면 맨 앞에서 그냥 돌아가 표를 읽지 않는다."""
    if not is_admin():
        return
    # 줄을 받아 세면 한 번에 받는 줄 수 제한에 걸릴 수 있어, 표가 직접 센 수만 받는다
    try:
        count = get_supabase().table(WORK_TABLE).select("id", count="exact", head=True).execute().count
    except Exception as e:
        st.error(f"저장된 업무 기록 수를 불러오지 못했습니다: {e}")
        return
    # 표가 수를 돌려주지 않으면 숫자를 지어내지 않고 안내만 남긴다
    if count is None:
        st.error("저장된 업무 기록 수를 불러오지 못했습니다")
        return
    st.metric("저장된 업무 기록", f"{count:,}")


def admin_record_styles(table):
    """관리 화면 업무 기록 표(한글 열 제목)의 칸마다 입힐 CSS를 같은 모양의 표로 돌려준다. 색을 입히는 칸만 글자색도 정한다."""
    styles = pd.DataFrame("", index=table.index, columns=table.columns)
    if "고객사" in table:
        styles["고객사"] = f"background-color: {ADMIN_CLIENT_BG}; {ADMIN_TABLE_TEXT}"
    if "상태" in table:
        styles["상태"] = [
            f"background-color: {ADMIN_STATUS_BG[s]}; {ADMIN_TABLE_TEXT}" if s in ADMIN_STATUS_BG else ""
            for s in table["상태"]
        ]
    if "마감일" in table:
        # 마감일이 비어 있거나 날짜가 아니거나, 상태가 「완료」인 업무는 칠하지 않는다
        days_left = (pd.to_datetime(table["마감일"], errors="coerce") - pd.Timestamp(seoul_today())).dt.days
        statuses = table["상태"] if "상태" in table else [""] * len(table)
        styles["마감일"] = [
            f"background-color: {ADMIN_DUE_BG}; {ADMIN_TABLE_TEXT}"
            if days <= ADMIN_DUE_ALERT_DAYS and status != "완료"
            else ""
            for days, status in zip(days_left, statuses)
        ]
    return styles


def show_admin_records():
    """관리 화면의 업무 기록 전체 표와 CSV 내려받기. 관리자가 아니면 맨 앞에서 그냥 돌아가 표를 읽지 않는다.
    화면의 표와 CSV는 표에서 읽은 같은 값이고, 읽지 못하면 둘 다 보여 주지 않는다."""
    if not is_admin():
        return

    # 이어 받는 동안 줄이 겹치거나 빠지지 않게 id까지 넣어 순서를 하나로 정한다
    def make_query():
        return (
            get_supabase()
            .table(WORK_TABLE)
            .select("*")
            .order("work_date", desc=True)
            .order("created_at", desc=True)
            .order("id", desc=True)
        )

    try:
        rows = read_all_rows(make_query)
    except Exception as e:
        st.error(f"업무 기록 전체를 불러오지 못했습니다: {e}")
        return
    if not rows:
        st.caption("저장된 업무 기록이 없습니다")
        return

    # 빈 칸이 있는 숫자 열이 소수로 바뀌지 않도록 표에서 읽은 값을 그대로 둔다
    records = pd.DataFrame(rows, dtype=object)
    # 화면 표에서는 id·created_at을 숨기고, 비어 있는 값(None)은 빈칸으로 보여 준다.
    # important 열은 빈칸 글자를 섞으면 체크 상자가 글자로 바뀌므로 그대로 둔다
    shown = records.drop(columns=WORK_HIDDEN_COLUMNS, errors="ignore")
    text_columns = shown.columns.drop("important", errors="ignore")
    shown[text_columns] = shown[text_columns].where(shown[text_columns].notna(), "")
    shown = shown.rename(columns=WORK_COLUMN_NAMES)
    st.dataframe(shown.style.apply(admin_record_styles, axis=None), use_container_width=True, hide_index=True)
    # CSV는 모든 열을 한글 열 제목으로 남기고, 엑셀이 한글을 알아보도록 utf-8-sig로 저장한다
    st.download_button(
        "CSV 내려받기",
        records.rename(columns=WORK_COLUMN_NAMES).to_csv(index=False).encode("utf-8-sig"),
        file_name=f"업무기록_전체_{seoul_today()}.csv",
        mime="text/csv",
        key="admin_records_csv",
    )


def open_admin():
    """사이드바 「관리」를 누르면 지금 보던 화면을 기억해 두고 관리 화면으로 간다. 관리 화면에서 다시 눌러도 기억은 바꾸지 않는다."""
    if st.session_state.get("screen") != "admin":
        st.session_state.before_admin = st.session_state.get("screen")
    go("admin")


def leave_admin():
    """관리 화면 「← 돌아가기」: 「관리」를 누르기 직전에 보던 화면 1·2·3으로 돌아간다. 알 수 없으면 화면 1로 간다."""
    before = st.session_state.pop("before_admin", None)
    go(before if before in ADMIN_RETURN_SCREENS else "home")


def show_admin():
    """관리자만 보는 관리 화면. 관리자가 아니면 맨 앞에서 그냥 돌아가 아무것도 그리지 않는다."""
    if not is_admin():
        return
    st.title("관리")
    st.button("← 돌아가기", key="admin_back", on_click=leave_admin)
    with st.container(border=True, key="card_admin"):
        st.write("관리자만 보는 화면입니다")
        show_admin_record_count()
        show_admin_records()


def show_user_bar():
    """모든 화면 맨 위 오른쪽에 들어온 사람의 이름과 「나가기」를 보여 준다.
    둘러보기면 「👀 둘러보는 중」과 「나가기」를 보여 주고, 나가기를 누르면 로그인 화면으로 돌아간다."""
    st.html(
        """
        <style>
        .st-key-user_bar {
            display: flex;
            flex-direction: row;
            justify-content: flex-end;
            align-items: center;
            gap: 8px;
        }
        .st-key-user_bar > div {
            width: auto !important;
        }
        .st-key-user_bar .user-name {
            display: flex;
            align-items: center;
            gap: 6px;
            margin: 0;
            font-size: 15px;
            font-weight: 600;
            color: #1E293B;
        }
        .st-key-user_bar .user-name img {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            object-fit: cover;
        }
        </style>
        """
    )
    if is_guest():
        with st.container(key="user_bar"):
            st.html('<p class="user-name">👀 둘러보는 중 · 가상 예시 자료</p>')
            st.button("나가기", key="logout", on_click=end_guest)
        return
    name = st.user.get("name") or st.user.get("email") or "사용자"
    photo = small_photo_url(str(USER_PHOTO_FILE), 96) if USER_PHOTO_FILE.exists() else None
    mark = f'<img src="{photo}" alt="">' if photo else "👤"
    with st.container(key="user_bar"):
        st.html(f'<p class="user-name">{mark} {html.escape(name)} 님</p>')
        st.button("나가기", key="logout", on_click=st.logout)


# 열을 나란히 두려면 화면 너비를 넓게 쓴다. 브라우저 탭에는 이름과 📋 그림을 보여 준다
st.set_page_config(page_title="미카엘 DESK", page_icon=str(TITLE_LOGO_FILE), layout="wide")

# 구글 계정으로 들어온 사람과 「둘러보기 (보기만)」로 들어온 사람만 화면을 본다.
# 둘 다 아니면 안내 화면만 그리고 멈춘다
if not st.user.is_logged_in and not is_guest():
    show_login_gate()
    st.stop()
# 구글 계정으로 들어왔어도 허락된 메일(ADMIN_EMAILS·ALLOWED_EMAILS)이 아니면 실제 자료를 열지 않고 멈춘다
if st.user.is_logged_in and not is_allowed():
    show_no_access()
    st.stop()
show_user_bar()

records = load_records()
# 앱을 열면 서비스 소개 첫 화면이 먼저 뜬다
st.session_state.setdefault("screen", "landing")
# 관리자가 아니면 화면 위치가 관리 화면으로 남아 있어도 첫 화면으로 돌려, 관리 화면 코드가 돌지 않게 한다
if st.session_state.screen == "admin" and not is_admin():
    st.session_state.screen = "landing"

if st.session_state.screen == "landing":
    show_landing(records)
else:
    # 화면 1·2·3 배경에도 첫 화면과 같은 사진을 깔고, 연한 하늘색을 FEATURE_BG_OVERLAY_OPACITY만큼 덮어 은은하게 보이게 한다.
    # 카드(이름표가 card_로 시작하는 칸)와 제목 띠는 첫 화면 유리 판과 똑같은 간유리(흰색 LANDING_PANEL_OPACITY, 흐림 10px,
    # 테두리, 둥근 모서리 20px, 그림자)로 맞춘다. 탭 줄·사이드바도 어울리는 간유리로 둔다
    feature_overlay = f"rgba(240, 249, 255, {FEATURE_BG_OVERLAY_OPACITY})"
    card_glass = f"rgba(255, 255, 255, {LANDING_PANEL_OPACITY})"
    st.html(
        f"""
        <style>
        [data-testid="stApp"] {{
            background-color: #F0F9FF;
            background-image:
                linear-gradient({feature_overlay}, {feature_overlay}),
                url("{image_data_url(str(LANDING_BG_FILE))}");
            background-size: cover;
            background-position: center top;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        [data-testid="stHeader"] {{
            background: transparent;
        }}
        [data-testid="stMain"] [class*="st-key-card_"] {{
            background: {card_glass};
            border: 1px solid rgba(255, 255, 255, 0.6);
            border-radius: 20px;
            box-shadow: 0 8px 32px rgba(30, 41, 59, 0.15);
            -webkit-backdrop-filter: blur(10px);
            backdrop-filter: blur(10px);
        }}
        /* 맨 위 제목 띠: 왼쪽 강조 줄은 두고 나머지는 카드와 같은 간유리로 */
        [data-testid="stHeading"] h1 {{
            background: {card_glass} !important;
            border: 1px solid rgba(255, 255, 255, 0.6);
            border-left: 4px solid #0284C7 !important;
            border-radius: 20px !important;
            box-shadow: 0 8px 32px rgba(30, 41, 59, 0.15);
            -webkit-backdrop-filter: blur(10px);
            backdrop-filter: blur(10px);
        }}
        /* 카드 안 작은 회색 글씨(마감일·진행상태 줄, 안내 문구)는 간유리 위에서도 읽히게 한 단계 진하게 */
        [data-testid="stMain"] [class*="st-key-card_"] [data-testid="stCaptionContainer"],
        [data-testid="stMain"] [class*="st-key-card_"] [data-testid="stCaptionContainer"] * {{
            color: #475569;
        }}
        /* 화면 1 「마감 챙길 업무」 맨 위 마감 임박 묶음: 연한 주황 바탕과 왼쪽 주황 줄로 먼저 눈에 띄게 */
        [data-testid="stMain"] .st-key-due_soon {{
            background: rgba(255, 237, 213, 0.75);
            border-left: 4px solid #F97316;
            border-radius: 12px;
            padding: 10px 12px;
        }}
        /* 화면 2 탭 이름 줄과 카드 밖 작은 안내 글은 배경 사진 위에 바로 놓이므로, 옅은 간유리를 깔아 읽히게 한다 */
        [data-testid="stMain"] [data-baseweb="tab-list"] {{
            background: rgba(255, 255, 255, 0.75);
            border-radius: 12px;
            padding: 0 8px;
            -webkit-backdrop-filter: blur(8px);
            backdrop-filter: blur(8px);
        }}
        [data-testid="stMain"] [data-baseweb="tab-list"] button p {{
            color: #1E293B;
            font-weight: 600;
        }}
        [data-testid="stMain"] [data-testid="stCaptionContainer"] {{
            color: #334155;
        }}
        /* 사이드바: 같은 간유리 */
        [data-testid="stSidebar"] {{
            background: rgba(255, 255, 255, 0.78) !important;
            border-right: 1px solid rgba(255, 255, 255, 0.7);
            box-shadow: 4px 0 24px rgba(30, 41, 59, 0.10);
            -webkit-backdrop-filter: blur(12px);
            backdrop-filter: blur(12px);
        }}
        [data-testid="stSidebarContent"] {{
            background: transparent;
        }}
        [data-testid="stSidebar"] :is(p, span, label) {{
            color: #1E293B;
        }}
        /* 휴대폰이 다크 모드여도 흰 카드 위 글자가 보이도록, 카드 안 글자는 진한 색으로 정한다 */
        [data-testid="stMain"] [class*="st-key-card_"] :is(p, li, span, label, h1, h2, h3, h4, h5, h6, div[data-testid="stMarkdownContainer"], div[data-testid="stMetricValue"]) {{
            color: #1E293B;
        }}
        /* 입력칸(글 칸·날짜 칸·고르기 칸)은 흰 바탕에 진한 글자로 정한다. 챗봇 대화창 안도 같다 */
        :is([data-testid="stMain"], [data-testid="stSidebar"], [data-testid="stPopoverBody"])
            :is(input, textarea, [data-baseweb="select"] > div) {{
            background: #FFFFFF;
            color: #1E293B;
            -webkit-text-fill-color: #1E293B;
        }}
        :is([data-testid="stMain"], [data-testid="stSidebar"], [data-testid="stPopoverBody"])
            :is(input, textarea)::placeholder {{
            color: #64748B;
            -webkit-text-fill-color: #64748B;
        }}
        /* 챗봇 대화창 안 버튼 글자도 진한 색으로 정한다 */
        [data-testid="stPopoverBody"] button {{
            background: #FFFFFF;
            color: #1E293B;
        }}
        </style>
        """
    )

    # 기능 화면 제목(화면 1·2·3)을 왼쪽에 작고 단정하게 보이게 한다. 글자는 그대로 둔다
    st.html(
        """
        <style>
        [data-testid="stHeading"] h1 {
            font-size: 22px !important;
            font-weight: 700 !important;
            color: #1E293B !important;
            background: #F0F9FF;
            border-left: 4px solid #0284C7;
            border-radius: 12px;
            padding: 8px 14px !important;
            margin: 0 0 8px !important;
            text-align: left;
        }
        /* 주로 누르는 버튼(확인·업무 기록 작성·수정·저장)은 강조색으로 꽉 채운다.
           오른쪽 아래 챗봇 아이콘과 대화창 안 버튼은 건드리지 않는다 */
        :is([data-testid="stMain"], [data-testid="stSidebar"])
            button[data-testid^="stBaseButton-primary"]:not([data-testid="stPopoverBody"] *) {
            background: #0284C7;
            border: 1px solid #0284C7;
            color: #FFFFFF;
        }
        :is([data-testid="stMain"], [data-testid="stSidebar"])
            button[data-testid^="stBaseButton-primary"]:not([data-testid="stPopoverBody"] *):is(:hover, :active, :focus) {
            background: #0369A1;
            border-color: #0369A1;
            color: #FFFFFF;
        }
        /* 나머지 버튼은 흰 바탕에 얇은 테두리 */
        :is([data-testid="stMain"], [data-testid="stSidebar"])
            button[data-testid^="stBaseButton-secondary"]:not([data-testid="stPopoverBody"] *):not(.st-key-chatbot *) {
            background: #FFFFFF;
            border: 1px solid #CBD5E1;
            color: #1E293B;
        }
        :is([data-testid="stMain"], [data-testid="stSidebar"])
            button[data-testid^="stBaseButton-secondary"]:not([data-testid="stPopoverBody"] *):not(.st-key-chatbot *):is(:hover, :active, :focus) {
            background: #FFFFFF;
            border-color: #0284C7;
            color: #0284C7;
        }
        </style>
        """
    )

    # 샘플 자료 안내는 기능 화면에서만 보여 준다.
    # 화면 1 「마감 챙길 업무」는 Supabase 업무 기록을 보므로 화면 1에서는 띄우지 않는다. 관리 화면에는 샘플 자료가 없다
    # 실제 관리판(로그인)에서는 샘플 안내를 띄우지 않고, 둘러보기에서만 보여 준다
    if use_demo_data() and st.session_state.screen not in ("home", "admin"):
        st.caption("샘플 자료로 보여 드립니다")

    # 사이드바는 처음에 감춰 두고, 왼쪽 위 「☰ 메뉴」 단추로 열고 닫는다.
    # Streamlit 자체의 « 접기 단추는 감춰 이 단추 하나로만 여닫게 한다
    sidebar_open = st.session_state.get("sidebar_open", False)
    # 여닫는 단추는 글자 없이 그림(☰·✕)만 보이는 작은 네모 단추로 꾸민다
    st.html(
        """
        <style>
        .st-key-menu_open {
            position: fixed;
            top: 14px;
            left: 16px;
            z-index: 1000001;
            width: auto !important;
        }
        .st-key-menu_open button, .st-key-menu_close button {
            width: 44px;
            min-height: 40px;
            padding: 0;
            font-size: 22px;
            line-height: 1;
        }
        .st-key-menu_open button p, .st-key-menu_close button p {
            font-size: 22px;
            line-height: 1;
            margin: 0;
        }
        [data-testid="stSidebarCollapseButton"] { display: none !important; }
        </style>
        """
    )
    if sidebar_open:
        # 열려 있으면 사이드바 맨 위(「← 첫 화면으로」 위)에 ❤️ 단추만 둔다(누르면 닫힘)
        st.sidebar.button("❤️", key="menu_close", help="메뉴 닫기", on_click=toggle_sidebar)
    else:
        # 닫혀 있으면 화면 왼쪽 위 구석에 ☰ 단추만 두고 사이드바는 감춘다
        st.button("☰", key="menu_open", help="메뉴 열기", on_click=toggle_sidebar)
        st.html(
            "<style>"
            '[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],'
            ' [data-testid="stExpandSidebarButton"] { display: none !important; }'
            "</style>"
        )

    # 기능 화면에서만 사이드바에 첫 화면으로 돌아가는 버튼을 둔다
    st.sidebar.button("← 첫 화면으로", use_container_width=True, on_click=go, args=("landing",))
    # 관리자에게만 관리 화면으로 가는 버튼을 둔다
    if is_admin():
        st.sidebar.button("관리", use_container_width=True, on_click=open_admin)
    # 사이드바 아래에 연습용 기록장을 접어 둔다. 둘러보기에서는 기록장을 두지 않는다
    if not is_guest():
        show_practice_notes()
    # 화면 1 사이드바 맨 아래(연습용 기록장 아래)에 共感 & TSG 한자 로고를 크게 둔다
    if st.session_state.screen == "home":
        st.sidebar.html(
            f'<div style="text-align:center; margin-top:64px;">'
            f'<img src="{image_data_url(str(TITLE_LOGO_FILE))}" alt="共感 로고" '
            f'style="width:68%; max-width:192px; height:auto;"></div>'
        )

    if st.session_state.screen == "detail":
        show_detail(records)
    elif st.session_state.screen == "record":
        show_record()
    elif st.session_state.screen == "admin":
        show_admin()
    else:
        show_home(records)

show_chatbot()
