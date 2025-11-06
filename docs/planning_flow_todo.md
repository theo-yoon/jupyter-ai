# Planning Flow Refactor To‑Do

## ✅ 현재까지 완료
- RootNode/ToolExecutorNode 책임을 `jupyter_ai/workflow/planning_flow/nodes/components/` 하위 모듈로 분리했습니다.
- 스트리밍·응답 라우팅·도구 실행 컴포넌트에 대한 단위 테스트(`tests/workflow/test_planning_components.py`)를 작성하고 전체 테스트 스위트를 통과시켰습니다.
- `_init_litellm_messages` TODO를 해소해 호출 메시지가 항상 prompt에 포함되도록 보강했습니다.
- `run_default_flow` 예외 처리 개선: 실패 시 사용자 메시지와 워크로그 상태를 일관되게 마무리하고, 크래시 경로 테스트를 추가했습니다.
- `tests/default_flow/test_runtime_helpers.py`와 통합 테스트가 새 런타임 헬퍼를 직접 사용하도록 정리했습니다.
- 기존 플레이북 전용 서비스는 제거했고, 플래닝 플로우만 유지하도록 런타임을 단순화했습니다.

## 🚧 진행 예정 작업
- 컴포넌트 테스트 확대: 빈 `tool_calls`, 중단된 워크로그 등 에지 케이스를 커버하는 시나리오 추가.
- `planning_flow` 모듈이 재노출하는 상수/함수를 단계적으로 정리하고, 실제 정의 모듈을 직접 임포트하도록 후속 정비.
- 런타임 초기화 로직을 `PlanStateService`/`WorklogService`로 이관했고, 추가 단위 테스트로 공백을 메꿀 예정.
- `planning_flow` 소비자 목록 점검 후 재노출 상수 제거 계획 수립 (각 모듈이 `root_node` 등에서 직접 import하도록 단계적 변경).

## 📝 참고 링크
- `jupyter_ai/workflow/planning_flow/nodes/components/` – 분리된 런타임 컴포넌트
- `tests/workflow/test_planning_components.py` – 신규 단위 테스트 모음
