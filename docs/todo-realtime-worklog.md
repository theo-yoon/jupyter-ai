# TODO: 실시간 플랜/워크로그 재설계

## 요구사항
- 질문을 수신하면 에이전트가 최상위 플랜 스텝(`plan_steps`)을 먼저 작성하고, 각 스텝은 고유 `step_id`, `title`, `status(pending/in_progress/completed/failed)`, `child_step_ids`를 가진다.
- 실행 중 생성되는 워크 노드(`work_nodes`)는 `node_id`, `step_id`, `node_type(self_reflection|tool_call|result_summary|instruction_update 등)`, `status`, `payload`(텍스트/코드/메타데이터), `created_at`을 포함하며, 서버가 순차 append/merge 할 수 있어야 한다.
- 플랜과 워크 상태 업데이트는 사용자 출력과 분리된다. 모든 중간 질문·요약·툴 호출 결과는 워크 노드로만 기록하고, 최종 답변(`final_answer`) 한 번만 사용자 채널로 전송한다.
- 워크셋 카드 헤더에 일시정지/재개 버튼을 추가하고, `run_state(active|paused|stopped)`를 UI와 백엔드에서 공통으로 인지하여 pause 시 툴 실행과 워크 노드 append를 중단/큐잉한다.
- `CommandExecutionRegistry` 또는 동등한 추상화를 도입해 `(entry_id, command_id, args_hash)` 단위로 실행 중인 툴을 추적하고, `await` 기반 호출과 fire-and-forget 호출의 중복 실행을 차단한다.
- UI(`jai-worklog-card.tsx`)는 플랜 스텝과 워크 노드를 각각 컴포넌트로 렌더링하고, 노드 타입별 시각적 구분, “최종 답변 대기” 배너, pause 상태 표시를 제공한다.
- 상태 모델(`WorklogEntry`, `WorklogEntryPatch`, `PlanStep`, `WorkNode`)과 업데이트 파이프라인(`build_worklog_patch`)을 확장해 plan/work 분리, 상태 머신(planning→executing→finishing) 전이를 지원한다.
- 모든 신규 모듈은 책임이 좁고 명확하도록 분리하며, 단일 파일이 과도하게 비대해지지 않도록 한다. 제어 흐름은 SOLID 원칙에 맞춰 구성하고 복잡한 `if/else` 중첩을 최소화한다.
- 본 작업은 원본 커밋 기준으로 새 브랜치에서 진행하고, 세부 요구사항과 테스트 범위는 항상 이 문서를 참조한다.
- 작업 브랜치 전략: `advanced-ai-5`를 베이스로 새 브랜치 `workflow-ai`를 생성하여 모든 구현을 진행한다.

## 구현 항목
1. 서버 모델 및 직렬화 스키마 업데이트: `plan_steps`, `work_nodes`, `run_state`, `final_answer` 필드 추가와 ID 병합 로직 확장.  
   - 참고 파일: `jupyter_ai/worklog/plan_steps.py`, `jupyter_ai/worklog/work_nodes.py`, `jupyter_ai/worklog/entry.py`, `jupyter_ai/worklog/builders.py`, `jupyter_ai/worklog/repository.py`, 관련 pydantic 모델 테스트.
2. `worklog_tracking` 실행 루프 리팩터링: 플랜 선작성, 워크 노드 append, 상태 머신 전이, pause/resume 훅.  
   - 참고 파일: `jupyter_ai/tools/worklog_tracking.py`, `jupyter_ai/worklog/worklog_events.py`, 새 상태 머신 헬퍼 모듈.
3. 커맨드 실행 레지스트리/큐 추가 및 기존 `command-store`와 동기화.  
   - 참고 파일: `jupyter_ai/tools/command_registry.py`(신규), `src/web-components/worklog/command-store.ts`, 백엔드 커맨드 처리 경로.
4. 프론트엔드 UI 리팩터링: 새로운 스텝 리스트/워크 노드 리스트 컴포넌트, pause/resume 버튼, 상태 배너 구현.  
   - 참고 파일: `src/web-components/jai-worklog-card.tsx`, `src/web-components/worklog/components/*`, 신규 `PlanStepList`/`WorkNodeList`.
5. 최종 답변 전용 이벤트 경로(`emit_final_answer`) 정의 및 기존 메시지 파이프라인 통합.  
   - 참고 파일: `jupyter_ai/worklog/worklog_events.py`, `jupyter_ai/server/api.py` 또는 메시지 브로커 경로, UI의 최종 답변 수신 컴포넌트.

## 검증 및 테스트
- **단위 테스트**: `state_models` 병합 로직, `command_registry` 중복 차단, 상태 머신 전이(planning→executing→paused→resumed→finishing) 시나리오.
- **통합 테스트**: `worklog_tracking.execute_with_worklog` 플로우에서 플랜 생성→워크 노드 append→pause/resume→최종 답변 전송까지의 비동기 시나리오 검증.
- **프론트엔드 테스트**: React 컴포넌트 렌더링 및 상태 전환 스냅샷, pause 버튼 UX, “최종 답변 대기” 배너 표시.
- **E2E/회귀 테스트**: 실제 툴 호출 경로에서 중간 메시지가 사용자 채널로 전송되지 않고 최종 답변만 전달되는지 확인하며, 기존 워크로그 엔트리 로딩/머지 동작이 유지되는지 확인한다.
