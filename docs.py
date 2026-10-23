"""문서 보관함 — Supabase Storage(파일을 담아 두는 저장 공간)의 docs 버킷(파일을 담는 통)에
문서를 올리고, 올라와 있는 문서마다 잠깐만 열리는 내려받기 링크를 보여 주는 Streamlit 화면.

실행:
    streamlit run docs.py

필요한 준비 (Supabase에서 한 번):
    1. Storage 메뉴에서 이름이 docs인 비공개 버킷(Public bucket 끔)을 만든다.
       파일 크기·종류 제한은 두지 않는다.
    2. SQL Editor에서 아래를 실행해 보기(SELECT)와 올리기(INSERT)만 허용한다.
        create policy "docs anyone can upload" on storage.objects
            for insert to anon with check (bucket_id = 'docs');
        create policy "docs anyone can list" on storage.objects
            for select to anon using (bucket_id = 'docs');
    덮어쓰기(UPDATE)·지우기(DELETE) 허용은 없으므로 같은 이름으로 다시 올릴 수 없고,
    화면에서 문서를 지울 수도 없다.
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

BUCKET = "docs"
# 비공개 버킷이라 문서 주소가 그냥은 열리지 않는다. 이 시간(초) 동안만 열리는
# 내려받기 링크를 만들고, 지나면 화면을 새로 고쳐 새 링크를 받는다.
URL_SECONDS = 60

load_dotenv(Path(__file__).parent / ".env")


@st.cache_resource
def get_supabase():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def upload_doc(doc):
    """올린 문서를 원래 파일 이름 그대로 버킷에 넣는다."""
    name = doc.name
    get_supabase().storage.from_(BUCKET).upload(
        name, doc.getvalue(), {"content-type": doc.type or "application/octet-stream"}
    )
    return name


def upload_error_message(name, error):
    """Supabase가 돌려준 오류를 무엇을 하면 되는지 알 수 있는 안내로 바꾼다."""
    text = str(error)
    if "Duplicate" in text or "already exists" in text:
        # 덮어쓰기(UPDATE) 허용이 없어 같은 이름은 다시 올릴 수 없다
        return f"{name}은(는) 이미 올라와 있습니다. 파일 이름을 바꿔서 올려 주세요."
    if "Invalid key" in text:
        return f"{name}: 파일 이름에 쓸 수 없는 글자(한글 등)가 있습니다. 영문 이름으로 바꿔서 올려 주세요."
    if "row-level security" in text or "Unauthorized" in text:
        return f"{name}을(를) 올릴 허용이 없습니다. Supabase에서 docs 올리기(INSERT) 허용을 확인해 주세요."
    return f"{name}을(를) 올리지 못했습니다: {error}"


def list_docs():
    """버킷에 있는 문서를 최근에 올린 것부터 돌려준다."""
    items = get_supabase().storage.from_(BUCKET).list(
        "",
        {"limit": 1000, "sortBy": {"column": "created_at", "order": "desc"}},
    )
    # 폴더(id 없음)와 Supabase가 빈 폴더에 넣어 두는 표시용 파일은 뺀다
    return [
        item
        for item in items
        if item.get("id") and item["name"] != ".emptyFolderPlaceholder"
    ]


def download_url(name):
    """URL_SECONDS 동안만 열리는 내려받기 링크. download 옵션으로 브라우저가 열지 않고 내려받는다."""
    return get_supabase().storage.from_(BUCKET).create_signed_url(
        name, URL_SECONDS, {"download": True}
    )["signedURL"]


def readable_size(size):
    for unit in ["B", "KB", "MB"]:
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


st.set_page_config(page_title="문서 보관함", page_icon="📁")
st.title("📁 문서 보관함")

if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
    st.error(".env에 SUPABASE_URL과 SUPABASE_KEY 값을 넣어 주세요.")
    st.stop()

# 문서 고르는 칸 + 올리기 버튼 (clear_on_submit: 올린 뒤 칸을 비운다)
with st.form("upload", clear_on_submit=True):
    # 버킷에 파일 종류 제한이 없으므로 어떤 파일이든 고를 수 있다
    docs = st.file_uploader("올릴 문서", accept_multiple_files=True)
    submitted = st.form_submit_button("올리기", use_container_width=True)

if submitted:
    if not docs:
        st.warning("올릴 문서를 먼저 골라 주세요.")
    for doc in docs:
        try:
            upload_doc(doc)
            st.success(f"올렸습니다: {doc.name}")
        except Exception as e:
            st.error(upload_error_message(doc.name, e))

# 올라와 있는 문서 모두 (최근에 올린 것이 앞)
try:
    items = list_docs()
except Exception as e:
    st.error(f"문서 목록을 불러오지 못했습니다: {e}")
    st.stop()

st.subheader(f"올라와 있는 문서 · {len(items)}개")
st.caption(f"내려받기 링크는 {URL_SECONDS}초 동안만 열립니다. 지나면 화면을 새로 고쳐 주세요.")

if not items:
    st.caption("아직 올라온 문서가 없습니다.")

for item in items:
    name_col, button_col = st.columns([3, 1])
    size = (item.get("metadata") or {}).get("size")
    uploaded = (item.get("created_at") or "")[:10]
    name_col.markdown(f"**{item['name']}**")
    name_col.caption(" · ".join(filter(None, [uploaded, size and readable_size(size)])))
    try:
        url = download_url(item["name"])
    except Exception as e:
        button_col.error(f"링크를 만들지 못했습니다: {e}")
        continue
    button_col.link_button("내려받기", url, use_container_width=True)
