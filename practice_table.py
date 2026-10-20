from pathlib import Path

import pandas as pd
import streamlit as st

CSV_PATH = Path(__file__).parent / "data" / "56_practice-inquiries.csv"

st.title("연습용 문의 목록")

df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")

selected_type = st.selectbox("type", ["전체"] + sorted(df["type"].unique()))
if selected_type != "전체":
    df = df[df["type"] == selected_type]

st.write(f"보이는 줄 수: {len(df)}")
st.dataframe(df, use_container_width=True, hide_index=True)
