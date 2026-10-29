import base64
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client

DATA_FILE = Path(__file__).parent / "data" / "records.csv"
PRD_FILE = Path(__file__).parent / "PRD.md"
MEMO_TABLE = "client_memos"
# 화면 3에서 쓰고 읽는 업무 기록 표
WORK_TABLE = "work_records"
# 화면 1에서 추가한 고객사를 담는 표
CLIENT_TABLE = "clients"
# 기록이 하나도 없는 고객사(새로 추가한 고객사 등)의 화면 2 칸에 보여 줄 글
NO_RECORD_TEXT = "아직 기록이 없습니다"
# 화면 3 입력 칸 6개에 대응하는 업무 기록 표의 열
RECORD_FIELDS = ("task", "status", "next_step", "due_date", "file_location", "revision_note")
# 화면 3 기존 기록 목록 상자의 높이(픽셀). 왼쪽 입력 칸 높이쯤으로 맞춘다
RECORD_LIST_HEIGHT = 680
# 첫 화면 배경 사진 위에 덮는 연한 하늘색(#F0F9FF)의 진하기. 0이면 사진 그대로, 1이면 사진이 안 보인다
LANDING_BG_OVERLAY_OPACITY = 0.45
# 첫 화면 유리 판의 흰색 진하기. 0이면 투명, 1이면 꽉 찬 흰색
LANDING_PANEL_OPACITY = 0.25
# 화면 1·2·3 배경 사진 위에 덮는 연한 하늘색(#F0F9FF)의 진하기. 첫 화면 것과 따로 둔다
FEATURE_BG_OVERLAY_OPACITY = 0.55
# 화면 1 「마감일이 가까운 업무」에서 마감 지난 업무와 아직 남은 업무를 묶음마다 몇 개까지 보여 줄지
DUE_GROUP_LIMIT = 3
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

load_dotenv(Path(__file__).parent / ".env")


@st.cache_resource
def get_supabase():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


@st.cache_data
def load_records():
    df = pd.read_csv(DATA_FILE, dtype=str)
    df["work_date"] = pd.to_datetime(df["work_date"]).dt.date
    df["due_date"] = pd.to_datetime(df["due_date"]).dt.date
    df["important"] = df["important"] == "Y"
    return df


def d_day(due):
    days = (due - date.today()).days
    if days == 0:
        return "D-day"
    return f"D-{days}" if days > 0 else f"D+{-days}"


def due_mark(due):
    """화면 1 「마감일이 가까운 업무」에 붙일 표시와 날짜 글을 돌려준다.
    마감이 지났으면 빨간 「마감 지남」과 "19일 지남", 오늘이면 주황 「오늘 마감」, 아직 남았으면 "D-3"."""
    days = (due - date.today()).days
    if days < 0:
        return ":red-badge[마감 지남]", f"{-days}일 지남"
    if days == 0:
        return ":orange-badge[오늘 마감]", ""
    return "", f"D-{days}"


def go(screen, client=None):
    st.session_state.screen = screen
    if client is not None:
        st.session_state.client = client


def task_row(row, label, key, badge=""):
    left, right = st.columns([6, 1])
    # 표시(badge)가 있으면 맨 앞에 두고, 날짜 글(label)이 비었으면 굵은 글씨를 빼고 쓴다
    head = " ".join(part for part in (badge, f"**{label}**" if label else "") if part)
    left.markdown(f"{head} {row.client_name} · {row.next_step}")
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


def show_home(df):
    st.title("화면 1 · 오늘의 업무")

    open_tasks = df[df["status"] != "완료"].sort_values("due_date")

    # 왼쪽 좁은 열은 고객사 선택, 가운데 넓은 자리는 두 업무 목록을 좌우로 나란히 둔다
    select_col, due_col, star_col = st.columns([1, 1.5, 1.5])

    with due_col, st.container(border=True, key="card_due"):
        st.subheader("마감 챙길 업무")
        # 마감 지난 업무(오래된 순)를 위에, 아직 남은 업무(오늘 마감 포함, 가까운 순)를 아래에 묶음마다 몇 개씩 보여 준다.
        # open_tasks가 마감일 순이라 두 묶음 모두 이미 원하는 순서다. 빈 묶음은 소제목째 그리지 않는다
        is_overdue = open_tasks["due_date"] < date.today()
        groups = [
            (title, g)
            for title, g in (
                ("🔴 마감 지남", open_tasks[is_overdue]),
                ("⏳ 다가오는 마감", open_tasks[~is_overdue]),
            )
            if not g.empty
        ]
        for i, (title, group) in enumerate(groups):
            # 두 묶음이 한눈에 나뉘도록 사이에 가는 줄을 긋는다
            if i > 0:
                st.divider()
            st.markdown(f"**{title}**")
            for row in group.head(DUE_GROUP_LIMIT).itertuples():
                badge, label = due_mark(row.due_date)
                task_row(row, label, f"due_{row.record_id}", badge)
            hidden = len(group) - DUE_GROUP_LIMIT
            if hidden > 0:
                st.caption(f"외 {hidden}건 더")

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
        summary = f"**고객사명** {client} · **진행상태** {status}"
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
        st.markdown(summary)

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
        now_tab, history_tab = st.tabs(["지금 현황", "파일·수정 이력"])

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

    with memo_col:
        show_memos(client)


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
                    "work_date": date.today().isoformat(),
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


@st.cache_data
def image_data_url(path):
    """사진 파일을 꾸밈 설정에 바로 넣을 수 있는 data URL로 만든다. 한 번 만든 것은 다시 쓴다."""
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


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


def show_landing():
    """서비스를 소개하는 첫 화면. 「시작하기」를 누르면 화면 1로 간다.
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
        .landing .intro {
            font-size: 20px;
            line-height: 1.6;
            margin: 0 auto 40px;
            max-width: 720px;
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
        /* 첫 화면에서는 사이드바와 그 여닫는 단추를 감춘다 */
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none;
        }
        @media (max-width: 640px) {
            .landing h1 { font-size: 34px; }
            .landing .intro { font-size: 17px; }
            .landing .icons { gap: 24px; }
            .landing .icon { width: 90px; }
            .st-key-start { width: 318px; }
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
            """
        <div class="landing">
            <h1>📋 <span>개인용</span> 관리판</h1>
            <p class="intro">여러 고객사 업무를 한 화면에</p>
            <div class="icons">
                <div class="icon">
                    <div class="circle"><span class="glyph glyph-building"></span></div>
                    <p>고객사 현황</p>
                </div>
                <div class="icon">
                    <div class="circle"><span class="glyph glyph-pencil"></span></div>
                    <p>업무 기록</p>
                </div>
                <div class="icon">
                    <div class="circle"><span class="glyph glyph-clock"></span></div>
                    <p>마감 관리</p>
                </div>
            </div>
        </div>
        """
        )

        with st.container(key="start"):
            st.button("시작하기", use_container_width=True, on_click=go, args=("home",))


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
    """물은 말과 받은 답을 Supabase 대화 기록 표에 남긴다."""
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

    with st.container(height=320):
        if not messages:
            with st.chat_message("assistant", avatar="✨"):
                st.write("안녕하세요! 이 관리판에 대해 궁금한 점을 물어보세요.")
        for m in messages:
            role, avatar = ("user", None) if m["role"] == "user" else ("assistant", "✨")
            with st.chat_message(role, avatar=avatar):
                if m["role"] == "model":
                    st.caption("AI가 쓴 초안입니다 · 확인하고 쓰세요")
                    # 마크다운은 줄바꿈 하나를 공백으로 합치므로, 문장마다 줄이 보이게 바꾼다.
                    st.markdown(m["text"].strip().replace("\n", "  \n"))
                else:
                    st.write(m["text"])

    with st.form("chat_form", clear_on_submit=True, border=False):
        question = st.text_input(
            "질문",
            placeholder="예: 화면 2에서는 무엇을 볼 수 있나요?",
            label_visibility="collapsed",
        )
        sent = st.form_submit_button("보내기", use_container_width=True)

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
                    try:
                        save_chat_log(question.strip(), answer)
                        st.session_state.pop("chat_log_error", None)
                    except Exception as error:
                        # 다시 그린 뒤에도 보이도록 남겨 둔다. 대화 자체는 그대로 이어진다.
                        st.session_state.chat_log_error = str(error)
                    st.rerun(scope="fragment")

    if "chat_log_error" in st.session_state:
        st.warning(f"대화를 기록하지 못했습니다: {st.session_state.chat_log_error}")

    st.divider()
    show_chat_logs()


def show_chatbot():
    """오른쪽 아래에 떠 있는 동그란 챗봇 아이콘. 누르면 대화창이 열린다."""
    st.html(
        """
        <style>
        .st-key-chatbot {
            position: fixed;
            right: 24px;
            bottom: 24px;
            width: auto !important;
            z-index: 1000;
        }
        .st-key-chatbot button {
            width: 64px;
            height: 64px;
            border-radius: 50%;
            font-size: 32px;
            background: #ffd43b;
            border: none;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
        }
        .st-key-chatbot button:hover {
            transform: scale(1.08);
        }
        .st-key-chatbot button svg {
            display: none;
        }
        [data-testid="stPopoverBody"] {
            width: 360px;
            max-width: calc(100vw - 32px);
        }
        </style>
        """
    )
    with st.container(key="chatbot"):
        with st.popover("✨", help="관리판 안내 챗봇"):
            chat_panel()


# 열을 나란히 두려면 화면 너비를 넓게 쓴다. 브라우저 탭에는 이름과 📋 그림을 보여 준다
st.set_page_config(page_title="개인용 관리판", page_icon="📋", layout="wide")

records = load_records()
# 앱을 열면 서비스 소개 첫 화면이 먼저 뜬다
st.session_state.setdefault("screen", "landing")

if st.session_state.screen == "landing":
    show_landing()
else:
    # 화면 1·2·3 배경에도 첫 화면과 같은 사진을 깔고, 연한 하늘색을 FEATURE_BG_OVERLAY_OPACITY만큼 덮어 은은하게 보이게 한다.
    # 카드(이름표가 card_로 시작하는 칸)는 흰 바탕으로 두어 업무 글씨가 잘 읽히게 한다
    feature_overlay = f"rgba(240, 249, 255, {FEATURE_BG_OVERLAY_OPACITY})"
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
            background: #FFFFFF;
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
            border-radius: 6px;
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

    # 샘플 자료 안내는 기능 화면에서만 보여 준다
    st.caption("샘플 자료로 보여 드립니다")

    # 기능 화면에서만 사이드바에 첫 화면으로 돌아가는 버튼을 둔다
    st.sidebar.button("← 첫 화면으로", use_container_width=True, on_click=go, args=("landing",))

    if st.session_state.screen == "detail":
        show_detail(records)
    elif st.session_state.screen == "record":
        show_record()
    else:
        show_home(records)

show_chatbot()
