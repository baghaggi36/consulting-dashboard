"""사진 보관함 — Supabase Storage(파일을 담아 두는 저장 공간)의 photos 버킷(파일을 담는 통)에
그림을 올리고, 올라와 있는 그림을 모두 보여 주는 Streamlit 화면.

실행:
    streamlit run photos.py

필요한 준비 (Supabase에서 한 번):
    1. Storage 메뉴에서 이름이 photos인 버킷을 만든다.
    2. SQL Editor에서 아래를 실행해 누구나 올리고 볼 수 있게 한다.
        create policy "photos 누구나 보기" on storage.objects
            for select using (bucket_id = 'photos');
        create policy "photos 누구나 올리기" on storage.objects
            for insert with check (bucket_id = 'photos');
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

BUCKET = "photos"
# 그림 주소를 이 시간(초) 동안만 열리게 만든다. 버킷이 공개가 아니어도 그림이 보인다.
URL_SECONDS = 3600
COLUMNS = 3

load_dotenv(Path(__file__).parent / ".env")


@st.cache_resource
def get_supabase():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def upload_photo(photo):
    """올린 그림을 원래 파일 이름 그대로 버킷에 넣는다."""
    name = photo.name
    get_supabase().storage.from_(BUCKET).upload(
        name, photo.getvalue(), {"content-type": photo.type}
    )
    return name


def list_photos():
    """버킷에 있는 그림을 최근에 올린 것부터 돌려준다."""
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


st.set_page_config(page_title="사진 보관함", page_icon="🖼️")
st.title("🖼️ 사진 보관함")

if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
    st.error(".env에 SUPABASE_URL과 SUPABASE_KEY 값을 넣어 주세요.")
    st.stop()

# 그림 고르는 칸 + 올리기 버튼 (clear_on_submit: 올린 뒤 칸을 비운다)
with st.form("upload", clear_on_submit=True):
    photos = st.file_uploader(
        "올릴 그림",
        type=["png", "jpg", "jpeg", "gif", "webp"],
        accept_multiple_files=True,
    )
    submitted = st.form_submit_button("올리기", use_container_width=True)

if submitted:
    if not photos:
        st.warning("올릴 그림을 먼저 골라 주세요.")
    for photo in photos:
        try:
            upload_photo(photo)
            st.success(f"올렸습니다: {photo.name}")
        except Exception as e:
            st.error(f"{photo.name}을(를) 올리지 못했습니다: {e}")

# 올라와 있는 그림 모두 (최근에 올린 것이 앞)
try:
    items = list_photos()
except Exception as e:
    st.error(f"그림 목록을 불러오지 못했습니다: {e}")
    st.stop()

st.subheader(f"올라와 있는 그림 · {len(items)}장")

if not items:
    st.caption("아직 올라온 그림이 없습니다.")

columns = st.columns(COLUMNS)
for i, item in enumerate(items):
    with columns[i % COLUMNS]:
        try:
            url = get_supabase().storage.from_(BUCKET).create_signed_url(
                item["name"], URL_SECONDS
            )["signedURL"]
        except Exception as e:
            st.error(f"{item['name']}을(를) 열지 못했습니다: {e}")
            continue
        st.image(url, caption=item["name"])
