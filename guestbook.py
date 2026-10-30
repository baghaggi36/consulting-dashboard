"""한 줄 방명록 — Supabase의 guestbook 표에 글을 남기고, 쌓인 글을 보여 주는 Streamlit 화면.

실행:
    streamlit run guestbook.py

필요한 표 (Supabase SQL Editor에서 한 번 실행):
    create table guestbook (
        id bigint generated always as identity primary key,
        message text not null,
        created_at timestamptz not null default now()
    );
    alter table guestbook enable row level security;
    create policy "누구나 읽기" on guestbook for select using (true);
    create policy "누구나 쓰기" on guestbook for insert with check (true);
"""

import os
from pathlib import Path

import requests
import streamlit as st

ENV_PATH = Path(__file__).with_name(".env")
TABLE = "guestbook"


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
    return res.json()


def count_entries(base_url, key):
    """표에 쌓인 글 수를 센다. 글 내용은 받지 않고 개수만 받는다(Content-Range: 0-9/N 의 N)."""
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"}
    res = requests.head(base_url, headers=headers, params={"select": "message"}, timeout=10)
    res.raise_for_status()
    return int(res.headers["Content-Range"].split("/")[-1])


st.set_page_config(page_title="한 줄 방명록", page_icon="📝")
st.title("📝 한 줄 방명록")

env = load_env(ENV_PATH)
# .env가 없는 올린 곳에서는, Streamlit이 Secrets 값을 같은 이름의 환경 변수로 넣어 둔 것을 읽는다
url = env.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
key = env.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")
if not url or not key:
    st.error(".env에 SUPABASE_URL과 SUPABASE_KEY 값을 넣어 주세요.")
    st.stop()
base_url = f"{url.rstrip('/')}/rest/v1/{TABLE}"

# 글 넣는 칸 + 남기기 버튼 (clear_on_submit: 남긴 뒤 칸을 비운다)
with st.form("write", clear_on_submit=True):
    message = st.text_input("남길 한 줄", max_chars=200, placeholder="한 줄 남겨 주세요")
    submitted = st.form_submit_button("남기기")

if submitted:
    if not message.strip():
        st.warning("빈 글은 남길 수 없습니다.")
    else:
        try:
            supabase("POST", base_url, key, json={"message": message.strip()})
            st.success("남겼습니다.")
        except requests.RequestException as e:
            st.error(f"저장하지 못했습니다: {e}")

# 쌓인 글 목록 (최신 글이 위)
try:
    total = count_entries(base_url, key)
    entries = supabase(
        "GET", base_url, key,
        params={"select": "message,created_at", "order": "created_at.desc"},
    )
except requests.RequestException as e:
    st.error(f"글을 불러오지 못했습니다: {e}")
    st.stop()

st.subheader(f"쌓인 글 · 지금까지 {total}줄")

if not entries:
    st.caption("아직 남겨진 글이 없습니다.")
for entry in entries:
    when = entry["created_at"][:16].replace("T", " ")
    st.text(entry["message"])
    st.caption(f"{when} (UTC)")
