import os
from datetime import date
from pathlib import Path

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
# 화면 3 입력 칸 6개에 대응하는 업무 기록 표의 열
RECORD_FIELDS = ("task", "status", "next_step", "due_date", "file_location", "revision_note")
# 화면 3 기존 기록 목록 상자의 높이(픽셀). 왼쪽 입력 칸 높이쯤으로 맞춘다
RECORD_LIST_HEIGHT = 680
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


def go(screen, client=None):
    st.session_state.screen = screen
    if client is not None:
        st.session_state.client = client


def task_row(row, label, key):
    left, right = st.columns([6, 1])
    left.markdown(f"**{label}** {row.client_name} · {row.next_step}")
    left.caption(f"마감 {row.due_date} · {row.status}")
    right.button(">", key=key, on_click=go, args=("detail", row.client_name))


def show_home(df):
    st.title("화면 1 · 첫 화면")

    open_tasks = df[df["status"] != "완료"].sort_values("due_date")

    # 왼쪽 좁은 열은 고객사 선택, 가운데 넓은 자리는 두 업무 목록을 좌우로 나란히 둔다
    select_col, due_col, star_col = st.columns([1, 1.5, 1.5])

    with due_col, st.container(border=True):
        st.subheader("마감일이 가까운 업무")
        for row in open_tasks.head(5).itertuples():
            task_row(row, d_day(row.due_date), f"due_{row.record_id}")

    with star_col, st.container(border=True):
        st.subheader("중요 표시한 업무")
        for row in df[df["important"]].sort_values("due_date").itertuples():
            task_row(row, "★", f"star_{row.record_id}")

    with select_col, st.container(border=True):
        st.subheader("확인할 고객사 선택")
        client = st.selectbox(
            "확인할 고객사 선택",
            options=list(df["client_name"].unique()),
            index=None,
            placeholder="고객사를 선택하세요",
            label_visibility="collapsed",
        )
        if st.button("확인", use_container_width=True):
            if client is None:
                st.warning("확인할 고객사를 먼저 선택해 주세요")
            else:
                go("detail", client)
                st.rerun()
        st.caption("선택 후 확인 → 화면 2로 이동")


def show_memos(client):
    with st.container(border=True):
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
    """CSV 기록과 화면 3에서 Supabase에 저장한 기록 중 더 최근 것 하나의 작업일·작업내용·진행상태를 돌려준다."""
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
        if saved_date >= latest["work_date"]:
            latest = {
                "work_date": saved_date,
                "task": saved["task"],
                # 진행상태를 비우고 저장했으면 "-"로 보여 준다
                "status": saved["status"] or "-",
            }
    return latest


def show_detail(df):
    st.title("화면 2 · 고객사 현황")

    client = st.session_state.client
    records = df[df["client_name"] == client].sort_values("work_date", ascending=False)
    latest = latest_work(client, records.iloc[0])
    open_tasks = records[records["status"] != "완료"].sort_values("due_date")

    # 맨 위 한 줄: 요약과 화면 이동 버튼
    summary_col, nav_col = st.columns([3, 1])

    with summary_col, st.container(border=True):
        summary = f"**고객사명** {client} · **진행상태** `{latest['status']}`"
        if not open_tasks.empty:
            due = open_tasks.iloc[0]["due_date"]
            summary += f" · **마감일** {due} ({d_day(due)})"
        st.markdown(summary)

    with nav_col:
        st.button(
            "업무 기록 작성·수정",
            use_container_width=True,
            on_click=go,
            args=("record", client),
        )
        st.caption("업무 기록 작성·수정 → 화면 3")

        st.button("목록으로", use_container_width=True, on_click=go, args=("home",))
        st.caption("목록으로 → 화면 1")

    # 가운데는 탭 두 개, 오른쪽 열은 한 줄 메모
    main_col, memo_col = st.columns([3, 1])

    with main_col:
        now_tab, history_tab = st.tabs(["지금 현황", "파일·수정 이력"])

        with now_tab:
            recent_col, next_col = st.columns(2)

            with recent_col, st.container(border=True):
                st.subheader("① 최근 작업")
                st.write(latest["task"])
                st.caption(f"작성일 {latest['work_date']}")

            with next_col, st.container(border=True):
                st.subheader("② 다음 할 일")
                for row in open_tasks.itertuples():
                    st.write(f"☐ {row.next_step} (마감 {row.due_date})")

        with history_tab:
            file_col, revision_col = st.columns(2)

            with file_col, st.container(border=True):
                st.subheader("③ 파일 위치")
                st.caption("오른쪽 위 복사 아이콘으로 경로를 복사합니다")
                for row in records.itertuples():
                    st.code(row.file_location, language=None)

            with revision_col, st.container(border=True):
                st.subheader("④ 수정내용")
                for row in records.itertuples():
                    st.write(f"{row.work_date} · {row.revision_note}")

    with memo_col:
        show_memos(client)


def pick_record(client, record):
    """기존 기록 목록에서 고른 기록을 어느 고객사 것인지와 함께 기억해 두고, 입력 칸 6개에 그 값을 채운다."""
    st.session_state.picked_record = {"client": client, **record}
    for field in RECORD_FIELDS:
        value = record[field]
        if field == "due_date":
            value = date.fromisoformat(value) if value else None
        else:
            # 비어 있는 칸은 빈 글자로 채운다
            value = value or ""
        st.session_state[f"rec_{field}"] = value


def clear_record_form():
    """고른 기록을 잊고 입력 칸 6개를 비운다."""
    st.session_state.pop("picked_record", None)
    for field in RECORD_FIELDS:
        st.session_state[f"rec_{field}"] = None if field == "due_date" else ""


def show_work_records(client):
    """화면 3에 이 고객사의 기존 업무 기록을 최근 것부터 보여 준다."""
    with st.container(border=True):
        st.subheader("기존 기록 목록")

        try:
            rows = (
                get_supabase()
                .table(WORK_TABLE)
                .select(
                    "id, work_date, task, status, next_step, due_date,"
                    " file_location, revision_note"
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

        if not rows:
            st.caption("아직 남긴 업무 기록이 없습니다")
        picked = st.session_state.get("picked_record")
        # 목록이 길어도 화면이 늘어나지 않게, 왼쪽 입력 칸 높이쯤 되는 상자 안에서만 굴려 본다
        with st.container(height=RECORD_LIST_HEIGHT, border=False):
            for raw in rows:
                # 비어 있는 칸은 None 대신 "-"로 보여 준다
                r = {k: "-" if v is None else v for k, v in raw.items()}
                with st.container(border=True):
                    left, right = st.columns([6, 1])
                    left.markdown(f"**{r['work_date']}** · {r['task']} `{r['status']}`")
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
                    # 고른 항목 자리에서 입력 칸에 불러왔다고 알려 준다
                    if picked and picked["client"] == client and picked["id"] == raw["id"]:
                        st.success("왼쪽 입력 칸에 불러왔어요. 고친 뒤 저장을 누르세요")


def show_record_form(client):
    """화면 3의 업무 기록 입력 칸 6개와 저장 버튼. 저장하면 고른 기록은 바꾸고, 아니면 Supabase 업무 기록 표에 새로 넣는다."""
    with st.container(border=True):
        st.subheader("업무 기록 입력")

        # 다른 고객사에서 골라 둔 기록은 보여 주지 않는다
        picked = st.session_state.get("picked_record")
        if picked and picked["client"] == client:
            # 다른 화면에 다녀오면 입력 칸 값은 지워지고 고른 기록만 남는다.
            # 그때는 입력 칸을 고른 기록으로 다시 채워, 안내와 입력 칸이 어긋나지 않게 한다
            if any(f"rec_{field}" not in st.session_state for field in RECORD_FIELDS):
                pick_record(client, picked)
            st.info(f"고른 기록: {picked['work_date']} · {picked['task']}")

        st.button("새로 쓰기", on_click=clear_record_form)

        # 마감일 칸은 처음에 비워 둔다
        st.session_state.setdefault("rec_due_date", None)

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
            submitted = st.form_submit_button("저장", use_container_width=True)

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
    name_col, nav_col = st.columns([3, 1])

    with name_col, st.container(border=True):
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
        .landing {
            max-width: 960px;
            margin: 48px auto 32px;
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
        .landing .jobs {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            text-align: left;
        }
        .landing .job {
            background: #FFFFFF;
            border-top: 4px solid #0284C7;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(30, 41, 59, 0.08);
        }
        .landing .job b {
            display: block;
            font-size: 18px;
            color: #0284C7;
            margin-bottom: 8px;
        }
        .landing .job p {
            margin: 0;
            line-height: 1.6;
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
        }
        </style>
        <div class="landing">
            <h1>📋 <span>개인용</span> 관리판</h1>
            <p class="intro">
                여러 고객사를 혼자 관리하는 컨설턴트가 고객사를 고르면
                최근 작업·다음 할 일·마감일·파일 위치를 한 화면에서 보고,
                폴더를 뒤지지 않고 업무를 바로 이어 가는 관리판입니다.
            </p>
            <div class="jobs">
                <div class="job">
                    <b>고객사 현황을 한 화면에</b>
                    <p>고객사를 고르면 최근 작업·진행상태·다음 할 일·마감일·파일 위치·주요 수정내용이 한 번에 나옵니다.</p>
                </div>
                <div class="job">
                    <b>업무 기록 남기고 고치기</b>
                    <p>오늘 한 일을 적어 저장하면, 관리판을 다시 열어도 그대로 남아 이어서 고칠 수 있습니다.</p>
                </div>
                <div class="job">
                    <b>급한 일과 중요한 일 먼저</b>
                    <p>마감일이 가까운 업무와 직접 중요 표시한 업무가 화면 1 위쪽에 먼저 보입니다.</p>
                </div>
            </div>
        </div>
        """
    )

    _, button_col, _ = st.columns([1, 1, 1])
    with button_col, st.container(key="start"):
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
