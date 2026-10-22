import os
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# 카카오 로컬 API 공식 문서: https://developers.kakao.com/docs/latest/ko/local/dev-guide
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
FOOD_CODE = "FD6"  # 카테고리 그룹 코드: 음식점
PAGE_SIZE = 15  # size 최대값
MAX_PAGES = 3  # pageable_count 최대 45건 = 15건 × 3쪽
RADIUS_OPTIONS = [100, 200, 300, 500, 700, 1000, 1500, 2000, 3000, 5000, 10000, 20000]  # 최대 20000m

COLUMN_LABELS = {
    "place_name": "가게",
    "category": "종류",
    "distance": "거리(m)",
    "road_address_name": "도로명 주소",
    "phone": "전화",
    "place_url": "카카오맵",
    "naver_url": "네이버 지도",
}
NAVER_SEARCH_URL = "https://map.naver.com/p/search/"


def kakao_get(url, params):
    response = requests.get(
        url,
        headers={"Authorization": f"KakaoAK {os.environ['KAKAO_REST_API_KEY']}"},
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def find_base(place):
    """기준 장소를 카카오에서 찾는다. 못 찾으면 None (좌표를 지어내지 않는다)."""
    # 동네 이름(예: 서신동)은 주소 검색에서 지명(REGION)으로 나온다
    data = kakao_get(ADDRESS_URL, {"query": place, "analyze_type": "exact", "size": 1})
    if data["documents"] and data["documents"][0]["address_type"] == "REGION":
        region = data["documents"][0]
        return {
            "name": region["address_name"].split()[-1],
            "address": region["address_name"],
            "kind": "지명",
            "x": region["x"],
            "y": region["y"],
        }
    # 역·건물 같은 장소는 키워드 검색 첫 결과를 쓴다
    data = kakao_get(KEYWORD_URL, {"query": place, "size": 1})
    if data["documents"]:
        spot = data["documents"][0]
        return {
            "name": spot["place_name"],
            "address": spot["road_address_name"] or spot["address_name"],
            "kind": spot["category_name"] or "장소",
            "x": spot["x"],
            "y": spot["y"],
        }
    return None


def search_restaurants(base, query, radius):
    params = {
        "category_group_code": FOOD_CODE,
        "x": base["x"],
        "y": base["y"],
        "radius": radius,
        "sort": "distance",
        "size": PAGE_SIZE,
    }
    # 검색어가 있으면 키워드 검색(음식점으로 한정), 없으면 음식점 카테고리 전체 검색
    url = CATEGORY_URL
    if query:
        url = KEYWORD_URL
        params["query"] = query

    places = []
    for page in range(1, MAX_PAGES + 1):
        data = kakao_get(url, {**params, "page": page})
        places.extend(data["documents"])
        if data["meta"]["is_end"]:
            break
    return places


st.set_page_config(page_title="동네 맛집", layout="wide")
st.title("내 조건 맛집 대시보드")

# 검색 조건 — API는 검색 버튼을 눌렀을 때만 부른다
st.sidebar.header("카카오 검색")
with st.sidebar.form("search"):
    base_name = st.text_input("기준 장소(역·동네 이름)", value="전주객사", placeholder="예: 전주역, 서신동")
    query = st.text_input("찾을 음식(비우면 음식점 전체)", placeholder="예: 비빔밥, 콩나물국밥")
    radius = st.select_slider("기준 장소에서 반경(m)", RADIUS_OPTIONS, value=500)
    submitted = st.form_submit_button("검색", type="primary")

if submitted:
    if not os.environ.get("KAKAO_REST_API_KEY"):
        st.error(".env 파일에 KAKAO_REST_API_KEY가 없습니다.")
        st.stop()
    if not base_name.strip():
        st.error("기준 장소를 입력해 주세요.")
        st.stop()
    try:
        with st.spinner("카카오에서 찾는 중..."):
            base = find_base(base_name.strip())
            if base is None:
                st.error(f"카카오에서 '{base_name.strip()}' 장소를 찾지 못했습니다. 이름을 바꿔 다시 검색해 주세요.")
                st.stop()
            st.session_state["base"] = base
            st.session_state["places"] = search_restaurants(base, query.strip(), radius)
    except requests.HTTPError as error:
        st.error(f"카카오 API 요청이 실패했습니다 (HTTP {error.response.status_code}). 키와 앱 설정을 확인해 주세요.")
        st.stop()
    except requests.RequestException:
        st.error("카카오 API에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.")
        st.stop()

if "places" not in st.session_state:
    st.info("왼쪽에서 조건을 고르고 검색 버튼을 눌러 주세요.")
    st.stop()

# 카카오에서 실제로 찾은 기준 장소
base = st.session_state["base"]
st.markdown(f"📍 **기준 장소: {base['name']}** ({base['kind']}) — {base['address']}")

df = pd.DataFrame(st.session_state["places"])
if df.empty:
    st.info("검색 결과가 없습니다. 검색어나 반경을 바꿔 보세요.")
    st.stop()

df = df.drop_duplicates("id")
df["distance"] = pd.to_numeric(df["distance"], errors="coerce").astype("Int64")
# "음식점 > 한식 > 국밥"에서 두 번째 단계(한식·중식 등)를 종류로 쓴다
df["category"] = df["category_name"].str.split(" > ").str[1].fillna("기타")
df["road_address_name"] = df["road_address_name"].where(
    df["road_address_name"] != "", df["address_name"]
)
# 네이버 지도 검색 링크: 가게 이름과 도로명 주소를 띄어 이어 붙인다
df["naver_url"] = NAVER_SEARCH_URL + (df["place_name"] + " " + df["road_address_name"]).map(quote)

# 받아 온 결과 안에서 거르기와 정렬 (API를 다시 부르지 않는다)
st.sidebar.header("결과 거르기·정렬")
keyword = st.sidebar.text_input("가게 이름 검색")
categories = sorted(df["category"].unique())
selected = st.sidebar.multiselect("종류", categories, default=categories)
sort_column = st.sidebar.selectbox(
    "정렬 기준", ["distance", "place_name", "category"], format_func=COLUMN_LABELS.get
)
ascending = st.sidebar.radio("순서", ["오름차순", "내림차순"]) == "오름차순"

filtered = df[df["category"].isin(selected)]
if keyword:
    filtered = filtered[filtered["place_name"].str.contains(keyword, case=False, regex=False)]
filtered = filtered.sort_values(sort_column, ascending=ascending)

if filtered.empty:
    st.info("조건에 맞는 가게가 없습니다. 거르기 조건을 바꿔 보세요.")
    st.stop()

# 요약 숫자
col1, col2, col3 = st.columns(3)
col1.metric("가게 수", f"{len(filtered)}곳")
col2.metric("종류 수", f"{filtered['category'].nunique()}가지")
col3.metric("평균 거리", f"{filtered['distance'].mean():,.0f}m")

# 맛집 뽑기 — 지금 표에 보이는 가게 안에서만 고른다 (API를 다시 부르지 않는다)
if st.button("🎲 맛집 뽑기"):
    st.session_state["picked_id"] = filtered["id"].sample(1).iloc[0]

picked = filtered[filtered["id"] == st.session_state.get("picked_id")]
if not picked.empty:
    shop = picked.iloc[0]
    with st.container(border=True):
        st.markdown(f"## 🍽️ {shop['place_name']}")
        st.markdown(f"### {shop['category']} · 기준 장소에서 {shop['distance']:,}m")
        st.markdown(f"[카카오맵에서 보기]({shop['place_url']})")

# 가게 표
st.subheader(f"가게 목록 ({len(filtered)}곳)")
st.dataframe(
    filtered[list(COLUMN_LABELS)].rename(columns=COLUMN_LABELS),
    width="stretch",
    hide_index=True,
    column_config={
        "카카오맵": st.column_config.LinkColumn(display_text="열기"),
        "네이버 지도": st.column_config.LinkColumn(display_text="열기"),
    },
)

# 차트
st.subheader("차트")
left, right = st.columns(2)

with left:
    st.markdown("**종류별 가게 수**")
    st.bar_chart(filtered["category"].value_counts().rename("가게 수"))

with right:
    st.markdown("**거리별 가게 수**")
    bins = list(range(0, int(filtered["distance"].max()) + 200, 200))
    distance_counts = (
        pd.cut(filtered["distance"].astype(float), bins=bins, right=False)
        .value_counts()
        .sort_index()
    )
    distance_counts.index = [f"{int(b.left)}~{int(b.right)}m" for b in distance_counts.index]
    st.bar_chart(distance_counts.rename("가게 수"), sort=False)

st.markdown("**지도**")
st.map(
    filtered.assign(lat=filtered["y"].astype(float), lon=filtered["x"].astype(float)),
    latitude="lat",
    longitude="lon",
)
