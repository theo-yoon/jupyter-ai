# Worklog & Plan UI Integration Design

## 배경
- 에이전트 답변은 채팅 로그 대신 단일 `plan` 카드와 단일 `worklog` 카드로 표현된다.
- 동일 응답 ID(`worklogEntryId`)에 속한 이벤트는 기존 카드 내용을 덮어쓰며, 새로운 카드 DOM 노드를 생성하지 않는다.
- 도구 실행 결과는 완료 시점에만 반환한다. 다만 실행 단계와 상태 전환은 별도 이벤트로 push해 `Working → Finished working` 흐름을 실시간으로 반영한다.

## UX 요구사항 요약
- 상태 헤더는 진행 중 `Working`, 완료 후 `Finished working`으로 전환되며 최신 요약을 렌더링한다.
- 완료 요약은 핵심 결과와 코드 식별자 링크(`CodeReference`)를 포함한다.
- 변경 요약 카드는 `n files changed +x -y`, `Undo`, `View diff` 액션을 제공한다.
- 타임라인은 플랜 단계별로 그룹화되고, 각 항목은 상태 아이콘, 관련 파일, 라인 증감, 접기/펼치기를 지원한다.
- 계획 기반 항목은 별도 섹션에서 완료 여부를 강조한다.
- 채팅 메시지는 누적하지 않고 `worklog` 이벤트만 갱신한다.

## 아키텍처 개요
- YDoc 기반의 기존 저장 구조는 유지하되, 이벤트 헬퍼를 통해 동일 ID의 카드 노드를 패치한다.
- 기존 `packages/jupyter-ai/jupyter_ai/tools/default_toolkit.py`는 수정하지 않는다.
- 새로운 모듈에서 상태 이벤트 전파, DTO 조립, 툴 래핑을 담당한다.

## 백엔드 확장 포인트

### `packages/jupyter-ai/jupyter_ai/tools/worklog_events.py`
- `async def push_worklog_update(entry_id: str, payload: WorklogEntry) -> None`
  - YDoc 문서의 `worklog` 트리에 entry ID별로 덮어쓰기 패치를 수행한다.
- `async def emit_status_transition(entry_id: str, state: str, meta: dict[str, Any]) -> None`
  - `state`는 `working`, `finished`, `failed` 등으로 한정한다.
  - 상태 변경 시 헤더·요약이 재렌더링되도록 최소 메타데이터를 포함한다.
- `async def emit_failure(entry_id: str, error_info: str) -> None`
  - 실패 시 상태 플래그와 메시지를 갱신한다.

### `packages/jupyter-ai/jupyter_ai/tools/extended_toolkit.py`
- `DEFAULT_TOOLKIT`을 import해 그대로 재노출한다.
- 각 도구를 감싸는 프록시(예: `tracked_bash`)를 정의해 실행 전후로 상태 이벤트를 전송한다.
- `Toolkit(name="jupyter-ai-plan-toolkit", ...)`에 프록시 도구와 `push_worklog_update`를 등록한다.
- 프록시는 `entry_id`와 단계 메타데이터를 인자로 받고, 실행 완료 후 DTO를 조립해 `push_worklog_update`로 전송하며 상태를 `finished`로 바꾼다.

### `packages/jupyter-ai/jupyter_ai/worklog/context.py`
- 작업 실행 동안 유지될 `WorklogContext`(`entry_id`, `room_id`, `persona_id`, 기타 메타데이터)를 정의하고 `contextvars`를 통해 set/reset/get API 제공.
- `run_tools()` 호출 전에 컨텍스트를 세팅하면, 툴 래퍼는 인자 없이도 현재 응답 스코프를 알 수 있다.

### `packages/jupyter-ai/jupyter_ai/worklog/ydoc_dispatcher.py`
- `YDocWorklogStore`가 YChat `metadata.worklog_entries`를 캐시/병합하며, `WorklogEventDispatcher`가 이 스토어를 통해 push/status/failure 이벤트를 기록한다.
- 컨텍스트 기반으로 올바른 YChat 인스턴스를 찾아 업데이트를 적용한다.

### `packages/jupyter-ai/jupyter_ai/worklog/state_models.py`
- 데이터 클래스:
  - `WorklogEntry`: `entry_id`, `status`, `summary`, `change_summary`, `nodes`.
  - `PlanNode`: `node_id`, `title`, `status`, `related_files`, `line_delta`, `is_plan`.
  - `ChangeSummary`: `files_changed`, `lines_added`, `lines_deleted`, `actions`.
  - `CodeReference`: `path`, `line`, `symbol`.
- DTO 빌드 헬퍼: 실행 결과나 diff 메타데이터를 위 구조로 변환.

### `packages/jupyter-ai/jupyter_ai/worklog/update_pipeline.py`
- 실행 결과를 받아 DTO를 만들고 `push_worklog_update`에 전달하는 파이프라인.
- 상태 전환, 완료, 실패 이벤트를 캡슐화한 헬퍼 포함.

## 프론트엔드 연동(별도 저장소)
- `StatusHeader`는 상태 이벤트를 구독해 `working`/`finished` 전환과 요약 갱신을 수행한다.
- `ChangeSummaryCard`는 `ChangeSummary` DTO로 라인 통계와 액션 핸들러(`Undo`, `View diff`)를 바인딩한다.
- `WorklogTimeline`은 플랜 단계 노드를 트리 형태로 렌더링, 이벤트 수신 시 해당 노드를 업데이트한다.
- `PlanSection`은 `is_plan=True` 노드만 필터링해 완료 여부와 진행 흐름을 표시한다.
- 모든 이벤트는 동일 `entry_id`를 사용하므로 카드 컨테이너는 한번만 생성된다.
- `<jai-worklog>` 웹컴포넌트가 응답 메시지에 포함되면, React 컴포넌트가 payload를 파싱해 전역 스토어(`worklog-store.ts`)에 머지하고 카드 UI를 렌더한다. 동일 `entry_id`의 업데이트는 메시지 추가 없이 카드만 갱신한다.

## 이벤트 흐름
1. 응답 시작: 새 `entry_id` 생성, `push_worklog_update`로 초기 `Working` 카드 생성.
2. 도구 실행 전: 프록시가 `emit_status_transition(entry_id, "working", {...})` 호출.
3. 도구 완료: 결과 DTO 생성 후 `push_worklog_update(entry_id, payload)` 호출 → 요약·타임라인·변경 카드 갱신.
4. 모든 단계 완료: `emit_status_transition(entry_id, "finished", final_meta)` 호출.
5. 오류 발생 시: `emit_failure(entry_id, error_info)`로 상태를 `failed`로 변경.

### `packages/jupyter-ai/jupyter_ai/litellm_lib/run_tools.py`
- `worklog_context` 인자를 받아 툴 실행 전후로 `WorklogContext`를 세팅/복원한다.

### `packages/jupyter-ai/jupyter_ai/default_flow/default_flow.py`
- `ToolExecutorNode`에서 메시지 ID, 룸 ID, 페르소나 ID로 `WorklogContext`를 구성해 전달한다.

## 검증 체크리스트
- [x] 새 모듈 추가 후 참조 경로와 import 순환이 없는지 확인.
- [x] 툴 프록시가 기존 도구 시그니처와 호환되는지 테스트.
- [ ] YDoc에 중복 entry가 생기지 않고 동일 ID에 덮어쓰기 되는지 확인.
- [ ] 프론트엔드 카드가 중복 생성되지 않고 내용만 갱신되는지 확인.
- [ ] `failed` 상태 시 UI가 오류 메시지와 후속 액션을 노출하는지 확인.

## 개발 메모
- `python3 -m compileall packages/jupyter-ai`로 신규 모듈 구문 검증 완료.
- `PLAN_AWARE_TOOLKIT`을 통해 기존 도구 + 추적 래퍼를 함께 노출.
- dispatcher 미설정 시에도 안전하게 동작하도록 no-op 핸들러 포함.
- `WorklogContext`를 `run_tools` 경로에 세팅해 툴 래퍼가 `entry_id`를 자동 해석하도록 변경.
- `<jai-worklog>` 컴포넌트와 sanitizer 허용 목록을 등록해 메시지 기반으로 워크로그 카드를 전달.
