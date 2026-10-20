"""Stop 훅(require-answer-signature): 답변 마지막 줄에 서명이 있는지 확인한다.

CLAUDE.md 규칙 — "모든 답의 맨 마지막 줄에 '이상입니다, 미카엘'을 적는다" — 를
기계적으로 지키게 하는 훅이다. 클로드 코드(Claude Code)는 한 번의 답변이 끝날 때
(Stop 이벤트) 이 스크립트를 실행하며, 표준입력(stdin)으로 그 턴에 대한 정보를
JSON으로 건네준다.

스키마를 둘러싼 불확실성에 대한 메모:
  이 훅을 만들면서 두 곳(서브에이전트 조사, 직접 돌린 WebFetch)에서 입력 JSON에
  `last_assistant_message`(마지막 답변 글) 필드가 있고 `stop_hook_active`(무한
  반복 방지용 플래그) 필드는 없다는 답을 받았다. 그런데 앞의 조사 결과는 시스템이
  "bypass-permissions" 패턴이 섞여 있다고 경고한 바 있어 곧이곧대로 믿지 않기로
  했다. 그래서 이 스크립트는 두 가능성 모두에서 안전하게 동작하도록 짰다:
    - `last_assistant_message`가 있으면 그걸 쓰고, 없으면 `transcript_path`
      (대화 기록 파일 경로)를 직접 읽어 마지막 답변을 찾는다.
    - `stop_hook_active`가 있으면 그 값을 지켜 반복을 막고, 없어도(즉 매번
      None으로 읽혀도) 서명이 한 번 채워지면 바로 통과하므로 반복이 쌓이지 않는다.
  알 수 없는 형식을 만나면 막지 않고 그냥 통과시킨다(안전 우선).
"""

# json 모듈을 불러온다 — 표준입력 JSON을 읽고, 결과 JSON을 만들기 위함
import json
# sys 모듈을 불러온다 — 표준입출력과 종료 코드 처리를 위함
import sys

# 표준입출력 인코딩을 UTF-8로 맞추는 시도를 시작한다
try:
    # 표준입력의 인코딩을 UTF-8로 재설정한다
    sys.stdin.reconfigure(encoding="utf-8")
    # 표준출력의 인코딩을 UTF-8로 재설정한다
    sys.stdout.reconfigure(encoding="utf-8")
    # 표준에러의 인코딩을 UTF-8로 재설정한다
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    # reconfigure가 없는 환경(예: 오래된 파이썬)이면 오류를 무시하고 넘어간다
    pass

# 답변 마지막 줄에 반드시 있어야 하는 서명 문자열을 정의한다
REQUIRED_SIGNATURE = "이상입니다, 미카엘"


# 훅으로 전달된 표준입력을 JSON으로 읽어오는 함수를 정의한다
def read_payload():
    # JSON 파싱을 시도한다
    try:
        # 표준입력에서 JSON을 읽어 그대로 반환한다
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # JSON 형식이 아니거나 값이 잘못됐으면 None을 반환한다
        return None


# 메시지의 content에서 마지막 텍스트 내용을 뽑아내는 함수를 정의한다
def extract_text_from_content(content) -> str:
    """메시지의 content가 문자열이거나, {"type": "text", "text": ...} 블록
    목록인 두 경우를 모두 지원해 마지막 글자 내용을 모은다."""
    # content가 단순 문자열이면
    if isinstance(content, str):
        # 그 문자열을 그대로 반환한다
        return content
    # content가 블록 목록이면
    if isinstance(content, list):
        # type이 "text"인 블록들에서 text 값만 모아 리스트로 만든다
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        # 모은 텍스트 중 마지막 것을 반환하고, 없으면 빈 문자열을 반환한다
        return texts[-1] if texts else ""
    # 문자열도 리스트도 아니면 빈 문자열을 반환한다
    return ""


# 대화 기록 파일(transcript)에서 마지막 어시스턴트 답변 텍스트를 찾는 함수를 정의한다
def last_assistant_text_from_transcript(transcript_path: str) -> str | None:
    # 파일 경로가 주어지지 않았으면
    if not transcript_path:
        # 찾을 수 없으므로 None을 반환한다
        return None
    # 대화 기록 파일 열기를 시도한다
    try:
        # 대화 기록 파일을 UTF-8로 연다
        with open(transcript_path, "r", encoding="utf-8") as f:
            # 파일의 모든 줄을 읽어 리스트로 저장한다
            lines = f.readlines()
    except OSError:
        # 파일을 열거나 읽는 중 오류가 나면 None을 반환한다
        return None

    # 파일의 마지막 줄부터 거꾸로 하나씩 살펴본다
    for line in reversed(lines):
        # 줄 양끝의 공백과 줄바꿈을 제거한다
        line = line.strip()
        # 빈 줄이면
        if not line:
            # 건너뛰고 다음 줄로 넘어간다
            continue
        # 이 줄을 JSON으로 해석해본다
        try:
            # 줄 하나를 JSON 객체로 변환한다
            entry = json.loads(line)
        except json.JSONDecodeError:
            # JSON으로 해석할 수 없으면 건너뛰고 다음 줄로 넘어간다
            continue

        # 이 항목의 종류(type)를 꺼낸다
        entry_type = entry.get("type")
        # 이 항목의 message 필드를 꺼낸다
        message = entry.get("message")
        # message가 딕셔너리면 그 안의 role을, 아니면 entry의 role을 가져온다
        role = message.get("role") if isinstance(message, dict) else entry.get("role")

        # 이 항목이 어시스턴트(assistant)가 쓴 것이면
        if entry_type == "assistant" or role == "assistant":
            # message가 딕셔너리면 그 안의 content를, 아니면 entry의 content를 가져온다
            content = message.get("content") if isinstance(message, dict) else entry.get("content")
            # content에서 실제 텍스트를 뽑아낸다
            text = extract_text_from_content(content)
            # 텍스트가 비어 있지 않으면
            if text:
                # 가장 최근 답변이므로 그 텍스트를 바로 반환한다
                return text
    # 끝까지 찾아도 어시스턴트 답변이 없으면 None을 반환한다
    return None


# 훅의 실제 진입점 함수를 정의한다
def main() -> int:
    # 표준입력에서 훅 페이로드(JSON)를 읽어온다
    payload = read_payload()
    # 페이로드를 읽지 못했으면
    if payload is None:
        # 막지 않고 정상 종료한다(0을 반환)
        return 0

    # 이 훅이 다루는 이벤트(Stop)가 아니면
    if payload.get("hook_event_name") not in (None, "Stop"):
        # 상관없는 이벤트이므로 막지 않고 종료한다
        return 0

    # stop_hook_active가 실제로 존재한다면: 이미 한 번 막아서 다시 돌아온 경우
    # 더는 막지 않는다(무한 반복 방지). 필드가 없으면 falsy이므로 영향 없다.
    if payload.get("stop_hook_active"):
        # 더 막지 않고 종료한다
        return 0

    # 페이로드에 마지막 어시스턴트 답변이 직접 들어있는지 확인한다
    last_message = payload.get("last_assistant_message")
    # 없으면
    if not last_message:
        # 대화 기록 파일을 직접 읽어서 마지막 답변을 찾는다
        last_message = last_assistant_text_from_transcript(payload.get("transcript_path"))

    # 그래도 마지막 답변을 찾지 못했으면
    if not last_message:
        # 마지막 답변을 못 찾으면(형식이 다르거나 파일이 아직 안 쓰였거나) 막지 않는다.
        return 0

    # 답변을 줄 단위로 나누고, 빈 줄은 제외한 목록을 만든다
    lines = [line for line in last_message.strip().splitlines() if line.strip()]
    # 남은 줄 중 마지막 줄을 꺼낸다(없으면 빈 문자열)
    last_line = lines[-1].strip() if lines else ""

    # 마지막 줄이 정확히 필요한 서명과 같으면
    if last_line == REQUIRED_SIGNATURE:
        # 규칙을 지켰으므로 막지 않고 종료한다
        return 0

    # 서명이 없을 때 되돌려줄 차단 결과를 만든다
    result = {
        # 이 답변을 막겠다는 결정
        "decision": "block",
        # 막은 이유를 설명하는 문자열을 만든다
        "reason": (
            # 서명이 없다는 안내 문구
            f"답 마지막 줄에 서명이 없습니다. "
            # 정확한 서명 문구를 다시 안내하는 문구
            f"맨 마지막 줄에 정확히 '{REQUIRED_SIGNATURE}'를 적어 다시 마무리하세요."
        ),
    }
    # 결과를 JSON 문자열로 바꿔 표준출력에 출력한다(클로드 코드가 이걸 읽어 차단 처리)
    print(json.dumps(result, ensure_ascii=False))
    # 함수 자체는 정상 종료 코드(0)를 반환한다(차단 여부는 위 출력으로 전달됨)
    return 0


# 이 파일이 직접 실행될 때만 아래 코드를 실행한다
if __name__ == "__main__":
    # main 함수를 실행하고, 그 반환값을 프로세스 종료 코드로 사용한다
    sys.exit(main())
