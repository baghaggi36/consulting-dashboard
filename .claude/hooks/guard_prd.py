"""PreToolUse 훅: PRD.md를 Edit/Write/MultiEdit으로 고치거나 새로 쓰려는 시도를 막는다.

클로드 코드(Claude Code)가 이 스크립트를 실행할 때, 어떤 도구가 어떤 입력으로
호출됐는지를 표준입력(stdin)으로 JSON 형태로 건네준다. 이 스크립트는 그 JSON을
읽어 대상 파일이 이 프로젝트의 PRD.md인지 확인한 뒤:
  - 맞으면: 화면 가운데에 항상 위(always-on-top)인 경고창을 띄우고,
    exit code 2로 종료해 도구 실행을 막고, stderr에 거부 이유를 적어
    AI에게 돌려준다.
  - 아니면: 아무 것도 하지 않고 그대로 종료해 원래 동작을 통과시킨다.
"""

import json
import os
import sys

try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

PRD_FILENAME = "prd.md"
BLOCKED_TOOLS = {"Edit", "Write", "MultiEdit"}


def get_project_root() -> str:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return env_root
    # .claude/hooks/guard_prd.py -> 프로젝트 루트는 두 단계 위
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_prd_path(file_path: str, project_root: str) -> bool:
    if not file_path:
        return False
    candidate = file_path if os.path.isabs(file_path) else os.path.join(project_root, file_path)
    candidate = os.path.normcase(os.path.abspath(candidate))
    prd_path = os.path.normcase(os.path.abspath(os.path.join(project_root, "PRD.md")))
    return candidate == prd_path


def show_warning_popup() -> None:
    try:
        import tkinter as tk
    except ImportError:
        return

    root = tk.Tk()
    root.title("PRD 자물쇠")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    width, height = 360, 150
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")

    tk.Label(
        root,
        text="PRD.md 는 잠겨 있습니다",
        font=("맑은 고딕", 13),
        pady=20,
    ).pack()

    tk.Button(root, text="확인", width=10, command=root.destroy).pack(pady=10)

    root.lift()
    root.focus_force()
    root.mainloop()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = payload.get("tool_name")
    if tool_name not in BLOCKED_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    project_root = payload.get("cwd") or get_project_root()

    if not is_prd_path(file_path, project_root):
        return 0

    show_warning_popup()

    print(
        "PRD.md는 잠겨 있으니 고치지 말고 바꿀 내용을 제안만 하세요.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
