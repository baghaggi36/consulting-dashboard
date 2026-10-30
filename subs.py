"""구독 정리함 — Supabase의 subscriptions 표를 보여 주고, 줄을 더하고 고치고 지우는 Streamlit 화면.

실행:
    streamlit run subs.py

쓰는 표 (이미 Supabase에 있음):
    subscriptions (id, created_at, name, category, monthly_fee, last_used)
    줄을 더하고 고치고 지우려면 표의 RLS(행 단위 접근 규칙)에서 insert·update·delete가 허용되어야 한다.
"""

import os
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

ENV_PATH = Path(__file__).with_name(".env")
TABLE = "subscriptions"
EDIT_COLUMNS = ["name", "category", "monthly_fee", "last_used"]
EDITOR_KEY = "subs_editor"


def load_env(path):
    """.env 파일의 이름=값 줄을 읽어 사전으로 돌려준다."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def supabase(method, base_url, key, **kwargs):
    """Supabase REST(웹 주소로 데이터를 주고받는 방식) 요청을 보내고 JSON 결과를 돌려준다."""
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "return=representation",
    }
    res = requests.request(method, base_url, headers=headers, timeout=10, **kwargs)
    res.raise_for_status()
    return res.json() if res.content else None


def clean(row):
    """편집 표에서 받은 한 줄 값을 Supabase에 보낼 모양으로 바꾼다(빈 칸은 None, 날짜는 YYYY-MM-DD)."""
    out = {}
    for col, value in row.items():
        if col not in EDIT_COLUMNS:
            continue
        if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
            out[col] = None
        elif col == "last_used":
            out[col] = value.isoformat() if hasattr(value, "isoformat") else str(value)[:10]
        elif col == "monthly_fee":
            out[col] = int(value)
        else:
            out[col] = str(value).strip()
    return out


st.set_page_config(page_title="구독 정리함", page_icon="📦", layout="wide")
st.title("📦 구독 정리함")

env = load_env(ENV_PATH)
# .env가 없는 올린 곳에서는, Streamlit이 Secrets 값을 같은 이름의 환경 변수로 넣어 둔 것을 읽는다
url = env.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
key = env.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")
if not url or not key:
    st.error(".env에 SUPABASE_URL과 SUPABASE_KEY 값을 넣어 주세요.")
    st.stop()
base_url = f"{url.rstrip('/')}/rest/v1/{TABLE}"

# 저장 뒤 다시 그려질 때 보여 줄 결과 안내
if "notice" in st.session_state:
    st.success(st.session_state.pop("notice"))

try:
    rows = supabase("GET", base_url, key, params={"select": "*", "order": "monthly_fee.desc.nullslast,id.asc"})
except requests.RequestException as e:
    st.error(f"표를 불러오지 못했습니다: {e}")
    st.stop()

df = pd.DataFrame(rows, columns=["id"] + EDIT_COLUMNS)
df["last_used"] = pd.to_datetime(df["last_used"], errors="coerce").dt.date

total = int(pd.to_numeric(df["monthly_fee"], errors="coerce").fillna(0).sum())
st.caption(f"구독 {len(df)}개 · 한 달 합계 {total:,}원")
st.caption("칸을 눌러 고치고, 맨 아래 빈 줄에 새 구독을 적고, 줄 왼쪽 칸을 골라 휴지통으로 지운 뒤 저장을 누르세요.")

editor_key = f"{EDITOR_KEY}_{st.session_state.get('editor_version', 0)}"
st.data_editor(
    df,
    key=editor_key,
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    disabled=["id"],
    column_config={
        "id": st.column_config.NumberColumn("번호"),
        "name": st.column_config.TextColumn("이름", required=True),
        "category": st.column_config.TextColumn("분류"),
        "monthly_fee": st.column_config.NumberColumn("월 요금(원)", min_value=0, step=100, format="%d"),
        "last_used": st.column_config.DateColumn("마지막 사용일", format="YYYY-MM-DD", max_value=date.today()),
    },
)

changes = st.session_state[editor_key]
added = [clean(r) for r in changes["added_rows"] if clean(r).get("name")]
edited = {int(df.iloc[i]["id"]): clean(v) for i, v in changes["edited_rows"].items()}
deleted = [int(df.iloc[i]["id"]) for i in changes["deleted_rows"]]


def save(delete_ids):
    """더한 줄·고친 줄과, 지우기로 확정한 줄을 Supabase에 반영하고 표를 새로 불러온다."""
    try:
        if added:
            supabase("POST", base_url, key, json=added)
        for row_id, values in edited.items():
            if row_id not in delete_ids and values:
                supabase("PATCH", base_url, key, params={"id": f"eq.{row_id}"}, json=values)
        for row_id in delete_ids:
            supabase("DELETE", base_url, key, params={"id": f"eq.{row_id}"})
    except requests.RequestException as e:
        st.error(f"저장하지 못했습니다: {e}")
        st.stop()
    kept = len(deleted) - len(delete_ids)
    notice = f"저장했습니다 — 더함 {len(added)} · 고침 {len(edited)} · 지움 {len(delete_ids)}"
    if kept:
        notice += f" (지우지 않고 남긴 줄 {kept}개)"
    st.session_state["notice"] = notice
    st.session_state.pop("ask_delete", None)
    # 편집 표의 이름을 바꿔야 브라우저에 남은 편집(휴지통 표시 등)까지 비우고 새로 그린다
    st.session_state.pop(editor_key, None)
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
    st.rerun()


if st.button("저장", type="primary"):
    if not (added or edited or deleted):
        st.info("바뀐 내용이 없습니다.")
    elif deleted:
        # 지울 줄이 있으면 바로 지우지 않고 아래에서 한 번 더 묻는다
        st.session_state["ask_delete"] = True
    else:
        save([])

if not deleted:
    st.session_state.pop("ask_delete", None)

if st.session_state.get("ask_delete"):
    names = [str(df.iloc[i]["name"]) for i in changes["deleted_rows"]]
    st.warning(f"구독 {len(names)}개를 지웁니다: {', '.join(names)}\n\n정말 지울까요? 지운 줄은 되살릴 수 없습니다.")
    yes, no = st.columns(2)
    if yes.button("네, 지웁니다", type="primary", width="stretch"):
        save(deleted)
    if no.button("지우지 않기 (나머지만 저장)", width="stretch"):
        save([])
