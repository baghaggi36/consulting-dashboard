# 작업 공간 안내

- 매출 데이터 정리 및 보고 (`01_docs/`, `02_output/`, `03_reports/`, `99_backup/`, `memo.md`) — 지저분한 매출 데이터셋을 점검하고 정리하여 담당자별로 나누고, 워크숍 지출·견적 문서와 대조합니다.
- 제품 아이디어 → PRD → 할 일 목록 (`idea/`, `PRD.md`, `tasks.md`, `dashboard/`) — 미카엘이라는 1인 중소기업 컨설턴트 페르소나를 위한 개인용 관리판 앱("관리판")의 범위를 정하고 명세하는 작업으로, 제품관리 강좌나 실습 과제로 보입니다.
- 번호가 붙은 최상위 폴더(`01_docs`, `02_output`, `03_reports`, `99_backup`)는 파이프라인 단계를 나타냅니다: 원본 입력 → 처리된 산출물 → 최종 산출물 → 백업. 새 최상위 폴더를 만들기보다는 새 파일을 해당 단계 폴더에 맞춰 넣으세요.
- 관리판 문서는 다음 순서로 쌓여 있습니다: `idea/topic.md`(확정된 한 줄 개념 + 페르소나) → `idea/scope.md` / `idea/scope-detail.md`(범위 안/밖) → `idea/screens.md` / `idea/wireframe.md`(+ `.png`) → `idea/flow.md` / `idea/flow-detail.md` → `PRD.md`(최종 PRD) → `tasks.md`(수용 기준 번호가 태그된 작업 목록).
- `dashboard/index.html`은 워크숍 지출 정산을 보여주는 기존 보고서이며, 작업 흐름 1(매출 데이터)의 산출물입니다 — 새로 만드는 관리판 앱이 아닙니다.
