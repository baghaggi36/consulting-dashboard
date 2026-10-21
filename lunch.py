from pathlib import Path

import pandas as pd
import streamlit as st

CSV_PATH = Path(__file__).parent / "data" / "72_lunch-log.csv"

COLUMN_LABELS = {
    "date": "날짜",
    "menu": "메뉴",
    "shop": "가게",
    "type": "종류",
    "price": "가격",
    "rating": "별점",
}

st.set_page_config(page_title="맛집 기록", layout="wide")
st.title("맛집 기록 대시보드")

df = pd.read_csv(CSV_PATH, encoding="utf-8-sig", parse_dates=["date"])

# 검색과 필터
st.sidebar.header("검색·필터")
keyword = st.sidebar.text_input("메뉴·가게 검색", placeholder="예: 국밥, 황금성")
types = sorted(df["type"].unique())
selected_types = st.sidebar.multiselect("종류", types, default=types)
min_rating, max_rating = st.sidebar.slider("별점", 1, 5, (1, 5))
period = st.sidebar.date_input(
    "기간",
    (df["date"].min().date(), df["date"].max().date()),
    min_value=df["date"].min().date(),
    max_value=df["date"].max().date(),
)
# 시작일만 고른 상태에서는 그날 하루로 보고, 비우면 전체 기간으로 본다
if not period:
    period = (df["date"].min().date(), df["date"].max().date())
start_date, end_date = period[0], period[-1]

filtered = df[
    df["type"].isin(selected_types)
    & df["rating"].between(min_rating, max_rating)
    & df["date"].dt.date.between(start_date, end_date)
]
if keyword:
    filtered = filtered[
        filtered["menu"].str.contains(keyword, case=False, regex=False)
        | filtered["shop"].str.contains(keyword, case=False, regex=False)
    ]

# 정렬
st.sidebar.header("정렬")
sort_column = st.sidebar.selectbox(
    "정렬 기준", list(COLUMN_LABELS), format_func=COLUMN_LABELS.get
)
ascending = st.sidebar.radio("순서", ["오름차순", "내림차순"], index=1) == "오름차순"
filtered = filtered.sort_values(sort_column, ascending=ascending)

if filtered.empty:
    st.info("조건에 맞는 기록이 없습니다. 검색어나 필터를 바꿔 보세요.")
    st.stop()

# 요약 숫자
col1, col2, col3, col4 = st.columns(4)
col1.metric("방문 횟수", f"{len(filtered)}회")
col2.metric("총 지출", f"{filtered['price'].sum():,}원")
col3.metric("평균 가격", f"{filtered['price'].mean():,.0f}원")
col4.metric("평균 별점", f"{filtered['rating'].mean():.2f}점")

# 기록 표
st.subheader(f"기록 목록 ({len(filtered)}건)")
st.dataframe(
    filtered.assign(date=filtered["date"].dt.strftime("%Y-%m-%d")).rename(
        columns=COLUMN_LABELS
    ),
    use_container_width=True,
    hide_index=True,
)

# 차트
st.subheader("차트")
left, right = st.columns(2)

with left:
    st.markdown("**종류별 방문 횟수**")
    st.bar_chart(filtered["type"].value_counts().rename("방문 횟수"))

    st.markdown("**월별 지출**")
    monthly = filtered.groupby(filtered["date"].dt.strftime("%Y-%m"))["price"].sum()
    st.bar_chart(monthly.rename("지출(원)"))

with right:
    st.markdown("**가게별 평균 별점**")
    shop_rating = (
        filtered.groupby("shop")["rating"].mean().sort_values(ascending=False)
    )
    st.bar_chart(shop_rating.rename("평균 별점"))

    st.markdown("**별점 분포**")
    rating_counts = (
        filtered["rating"].value_counts().reindex(range(1, 6), fill_value=0)
    )
    rating_counts.index = [f"{r}점" for r in rating_counts.index]
    st.bar_chart(rating_counts.rename("횟수"))
