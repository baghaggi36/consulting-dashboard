"""챗봇 — .env의 GEMINI_API_KEY가 채워져 있는지 알려 주고, 빈칸에 넣은 말을 Gemini에 보내 받은 답을 보여 주는 Streamlit 화면.

준비:
    pip install -U google-genai

실행:
    streamlit run helper.py
"""

from pathlib import Path

import streamlit as st
from google import genai

ENV_PATH = Path(__file__).with_name(".env")
# 부르는 방법(generate_content)은 공식 문서 기준
# https://ai.google.dev/gemini-api/docs/generate-content/get-started
# 모델은 공식 모델 목록의 안정판 중 가장 가벼운 flash-lite 계열
# https://ai.google.dev/gemini-api/docs/models
MODEL = "gemini-3.5-flash-lite"


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


def ask_gemini(api_key, text):
    """빈칸에 넣은 말을 Gemini에 보내고 받은 답 글을 돌려준다."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=MODEL, contents=text)
    return response.text


st.set_page_config(page_title="챗봇", page_icon="💬")
st.title("챗봇")

api_key = load_env(ENV_PATH).get("GEMINI_API_KEY")

# 키 값은 화면에 보이지 않고, 채워져 있는지만 알려 준다.
if api_key:
    st.write("✅ .env의 GEMINI_API_KEY가 채워져 있습니다.")
else:
    st.write("❌ .env의 GEMINI_API_KEY가 비어 있습니다.")

question = st.text_area("Gemini에게 보낼 말")

if st.button("보내기"):
    if not api_key:
        st.error(".env에 GEMINI_API_KEY를 먼저 채워 주세요.")
    elif not question.strip():
        st.warning("빈칸에 보낼 말을 먼저 적어 주세요.")
    else:
        with st.spinner("Gemini가 답을 쓰는 중입니다..."):
            try:
                answer = ask_gemini(api_key, question)
            except Exception as error:
                st.error(f"Gemini를 부르다 문제가 생겼습니다: {error}")
            else:
                st.write(answer or "(받은 답이 비어 있습니다.)")
