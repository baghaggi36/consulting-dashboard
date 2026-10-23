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

    with st.container(border=True):
        st.subheader("마감일이 가까운 업무")
        for row in open_tasks.head(5).itertuples():
            task_row(row, d_day(row.due_date), f"due_{row.record_id}")

    with st.container(border=True):
        st.subheader("중요 표시한 업무")
        for row in df[df["important"]].sort_values("due_date").itertuples():
            task_row(row, "★", f"star_{row.record_id}")

    with st.container(border=True):
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

    with st.container(border=True):
        st.markdown(f"**고객사명** {client}")
        st.markdown(f"**진행상태** `{latest['status']}`")
        if not open_tasks.empty:
            due = open_tasks.iloc[0]["due_date"]
            st.markdown(f"**마감일** {due} ({d_day(due)})")

    with st.container(border=True):
        st.subheader("① 최근 작업")
        st.write(latest["task"])
        st.caption(f"작성일 {latest['work_date']}")

    with st.container(border=True):
        st.subheader("② 다음 할 일")
        for row in open_tasks.itertuples():
            st.write(f"☐ {row.next_step} (마감 {row.due_date})")

    with st.container(border=True):
        st.subheader("③ 파일 위치")
        st.caption("오른쪽 위 복사 아이콘으로 경로를 복사합니다")
        for row in records.itertuples():
            st.code(row.file_location, language=None)

    with st.container(border=True):
        st.subheader("④ 수정내용")
        for row in records.itertuples():
            st.write(f"{row.work_date} · {row.revision_note}")

    show_memos(client)

    st.button(
        "업무 기록 작성·수정",
        use_container_width=True,
        on_click=go,
        args=("record", client),
    )
    st.caption("업무 기록 작성·수정 → 화면 3")

    st.button("목록으로", use_container_width=True, on_click=go, args=("home",))
    st.caption("목록으로 → 화면 1")


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


def show_record_form(client):
    """화면 3의 업무 기록 입력 칸 6개와 저장 버튼. 저장하면 고른 기록은 바꾸고, 아니면 Supabase 업무 기록 표에 새로 넣는다."""
    with st.container(border=True):
        st.subheader("업무 기록 입력")

        # 다른 고객사에서 골라 둔 기록은 보여 주지 않는다
        picked = st.session_state.get("picked_record")
        if picked and picked["client"] == client:
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

    with st.container(border=True):
        st.markdown(f"**고객사명** {client}")

    show_record_form(client)

    show_work_records(client)

    st.button(
        "고객사 현황으로", use_container_width=True, on_click=go, args=("detail", client)
    )
    st.caption("고객사 현황으로 → 화면 2")


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
                    st.caption("AI가 쓴 초안입니다")
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
                    answer = ask_chatbot(api_key, messages)
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


st.caption("샘플 자료로 보여 드립니다")

records = load_records()
st.session_state.setdefault("screen", "home")

if st.session_state.screen == "detail":
    show_detail(records)
elif st.session_state.screen == "record":
    show_record()
else:
    show_home(records)

show_chatbot()
