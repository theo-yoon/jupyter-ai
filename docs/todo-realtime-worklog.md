# TODO: 실시간 플랜/워크로그 재설계

## 요구사항
- 질문을 수신하면 에이전트가 최상위 플랜 스텝(`plan_steps`)을 먼저 작성하고, 각 스텝은 고유 `step_id`, `title`, `status(pending/in_progress/completed/failed)`, `child_step_ids`를 가진다. 플랜은 질문을 해결하기 위한 1~5개의 의미 있는 단계로 구성되며, 단순 작업이 아닌 관련 워크 아이템 묶음이어야 한다. 단일 스텝은 전체 요구사항을 한 번에 처리할 수 있는 경우에 한해 허용한다. **플랜 스텝은 반드시 LLM이 생성해야 하며, 규칙 기반/하드코딩 플랜 생성은 금지한다. LLM 생성이 실패하면 플랜 작성 자체를 중단하고 오류로 처리한다.**
- 최초 사용자 질문을 수신하면 한 문장 요약을 생성해 `WorklogEntry.metadata.query_summary`에 저장하고, UI 카드 헤더에 항상 노출한다. 요약은 질문 의도를 간결히 드러내고 1줄을 넘기지 않게 자르며, 이후 워크로그 진행 중에도 변경되지 않는다. **요약 역시 LLM을 통한 생성만 허용하며, 규칙 기반 요약이나 하드코딩 대체는 절대 사용하지 않는다. 생성이 실패하면 빈 요약 상태로 둔다.**
- 실행 중 생성되는 워크 노드(`work_nodes`)는 `node_id`, `step_id`, `node_type(self_reflection|tool_call|result_summary|instruction_update 등)`, `status`, `payload`(텍스트/코드/메타데이터), `created_at`을 포함하며, 서버가 순차 append/merge 할 수 있어야 한다.
- 도구 실행 결과는 `payload` 안에서 구조화된 형태로 표현한다. 코드 변경(diff/patch), bash 실행(stdout/stderr/exit code), 추가 산출물(파일 링크, 시각화 스냅샷 등)을 구분해 전달할 수 있도록 타입과 필드를 확장한다. UI는 해당 구조를 해석해 하이라이트, 로그 블록, 미리보기 등 적절한 뷰를 제공해야 한다.
- 플랜 스텝은 “Analyze request / Compose final answer” 같은 자리채움 문구가 아니라, 사용자 요구를 해결하기 위한 실제 작업 단계를 담는다. 예: `test.csv 구조 분석`, `분석 노트북 생성`, `데이터 분석 코드 작성`, `결과 요약 전달`. UI는 `Steps X/Y` 형태로 진행률을 계산한다.
- 플랜 스텝은 초기 작성 이후에도 실시간으로 상태가 갱신된다. 각 스텝의 상태가 `in_progress`/`completed` 등으로 바뀌면 즉시 UI에 반영된다.
- 워크 아이템(워크 노드)은 스텝을 수행하면서 순차적으로 생성된다. 에이전트가 도구를 호출하거나 중간 정리를 수행할 때마다 새로운 노드를 append하고, 각 워크 아이템은 작업 → 검증 → 필요 시 수정 과정을 거친 뒤 다음 아이템으로 넘어간다.
- 각 스텝이 완료될 때 에이전트는 해당 단계의 결과를 점검하고 필요 시 추가 워크 아이템을 생성한다. 모든 스텝이 완료되면 전체 워크 노드 결과를 요약한다.
- 최종 답변은 모든 작업 결과를 사용자가 이해하기 쉽도록 정리(가능하다면 시각화 포함)한 한 번의 응답으로 전달한다.
- 워크 노드 목록은 각 스텝별 세부 작업(`analyze csv file`, `create notebook`, `write data analysis code` 등)을 표시하고, 항목을 열고 닫으며 도구 실행 결과나 산출물을 확인할 수 있어야 한다.
- 채팅 답변은 다음 구조를 따른다.
  ```text
  ┌────────────────────────────────────────────┐
  │ Agent worklog                [Pause][Stop] │
  │ test.csv 데이터 인사이트 추출              │
  ├────────────────────────────────────────────┤
  │ Steps 0/4                                   │
  │  1. test.csv 구조 분석        (Pending)     │
  │  2. 분석 노트북 작성          (Pending)     │
  │  3. 데이터 분석 실행 및 확인  (Pending)     │
  │  4. 결과 요약 후 전달         (Pending)     │
  ├────────────────────────────────────────────┤
  │ Work items                                  │
  │  ▸ analyze csv file (completed ✓ 10:28)     │
  │  ▸ create notebook (in progress…)           │
  │  ┌──────────── live append ─────────────┐   │
  │  │ ▾ write data analysis code (NEW)      │  │
  │  │   • 10:32 실행 로그…                  │  │
  │  └──────────────────────────────────────┘   │
  │  ▸ summarize result (pending)               │
  ├────────────────────────────────────────────┤
  │ Summary result                              │
  │  ▸ 마케팅 핵심 KPI 상승 요인 요약          │
  ├────────────────────────────────────────────┤
  │ Final answer                                │
  │  “test.csv 분석 결과, A/B 캠페인 전환율은…” │
  └────────────────────────────────────────────┘
  ```
- 실시간 스냅샷 예시:

## 최근 작업 현황
- ToolExecutor를 단일 도구 실행→리뷰→재진입 구조로 고정해, 매 워크아이템 뒤에 LLM 리뷰를 강제하고 있습니다.
- 리뷰 메시지는 `PlanContextManager.append_step_review()`를 통해 스텝 메타데이터에 기록되며, `_parse_review_message()`가 후속 작업 후보를 추출합니다.
- WorkNodeList UI는 스텝 구분 없이 시간순으로 워크아이템을 평탄화해 보여주도록 갱신되었습니다.

## 다음 집중 포인트
- 리뷰 메시지에서 파싱한 `next_actions`를 스텝 메타데이터와 UI 모두에서 활용하도록 후속 액션 흐름을 정리합니다.
- General update와 Step review가 중복되지 않도록 메타데이터 구조를 재조정하고, 리뷰 이후 다음 도구 호출까지의 연결 로직을 다듬습니다.
- 플랜 생성→승인→도구 실행→리뷰→스텝 완료까지 이어지는 end-to-end 통합 테스트를 추가해 review-follow-up 경로를 검증합니다.
- `_parse_review_message()`의 bullet 인식 로직을 보강해 엣지 케이스에서도 후속 작업이 누락되지 않도록 합니다.

  | 시점 | Steps 진행률 | Work items 피드 |
  | --- | --- | --- |
  | t0 (요청 직후) | Steps 0/4 | `analyze csv file` (pending) |
  | t1 (CSV 분석 완료) | Steps 1/4 | `analyze csv file` (completed ✓), `create notebook` (pending) |
  | t2 (노트북 생성 중) | Steps 1/4 | `analyze csv file` (completed ✓), `create notebook` (in progress…) |
  | t3 (코드 실행 시작) | Steps 2/4 | 위 항목 + `write data analysis code` (NEW, in progress) |
  | t4 (요약 정리) | Steps 3/4 | 위 항목 + `summarize result` (NEW, pending) |
  | t5 (최종 답변) | Steps 4/4 | 모든 항목 completed, `Summary result` · `Final answer` 노드 채워짐 |
- 플랜과 워크 상태 업데이트는 사용자 출력과 분리된다. 모든 중간 질문·요약·툴 호출 결과는 워크 노드로만 기록하고, 최종 답변(`final_answer`) 한 번만 사용자 채널로 전송한다.
- 워크셋 카드 헤더에 일시정지/재개 버튼을 추가하고, `run_state(active|paused|awaiting_approval|stopped)`를 UI와 백엔드에서 공통으로 인지하여 pause 시 툴 실행과 워크 노드 append를 중단/큐잉한다. 최종 스텝 완료 후에는 개념적으로 `awaiting_approval` 단계를 거치지만, 서버가 즉시 자동 승인 처리하여 최종 답변을 바로 전송한다(향후 수동 승인 확장을 고려해 상태 값은 유지).
- `CommandExecutionRegistry` 또는 동등한 추상화를 도입해 `(entry_id, command_id, args_hash)` 단위로 실행 중인 툴을 추적하고, `await` 기반 호출과 fire-and-forget 호출의 중복 실행을 차단한다.
- UI(`jai-workitems-card.tsx`, `jai-plan-card.tsx`, 레거시 `jai-worklog-card.tsx`)는 플랜 스텝과 워크 노드를 각각 컴포넌트로 렌더링하고, 노드 타입별 시각적 구분, “최종 답변 대기” 배너, pause 상태 표시를 제공한다.
- 상태 모델(`WorklogEntry`, `WorklogEntryPatch`, `PlanStep`, `WorkNode`)과 업데이트 파이프라인(`build_worklog_patch`)을 확장해 plan/work 분리, 상태 머신(planning→executing→finishing) 전이를 지원한다.
- 모든 신규 모듈은 책임이 좁고 명확하도록 분리하며, 단일 파일이 과도하게 비대해지지 않도록 한다. 제어 흐름은 SOLID 원칙에 맞춰 구성하고 복잡한 `if/else` 중첩을 최소화한다.
- 본 작업은 원본 커밋 기준으로 새 브랜치에서 진행하고, 세부 요구사항과 테스트 범위는 항상 이 문서를 참조한다.
- 작업 브랜치 전략: `advanced-ai-5`를 베이스로 새 브랜치 `workflow-ai`를 생성하여 모든 구현을 진행한다.

## 구현 항목
1. 서버 모델 및 직렬화 스키마 업데이트: `plan_steps`, `work_nodes`, `run_state`, `final_answer`, `metadata.query_summary` 필드 추가와 ID 병합 로직 확장.  
   - 참고 파일: `jupyter_ai/workflow/common/worklog/plan_steps.py`, `jupyter_ai/workflow/common/worklog/work_nodes.py`, `jupyter_ai/workflow/common/worklog/entry.py`, `jupyter_ai/workflow/common/worklog/builders.py`, `jupyter_ai/workflow/common/worklog/repository.py`, 관련 pydantic 모델 테스트.
2. `worklog_tracking` 실행 루프 리팩터링: 플랜 선작성, 워크 노드 append, 상태 머신 전이, pause/resume 훅.  
   - 참고 파일: `jupyter_ai/workflow/common/worklog/controller.py`, `jupyter_ai/workflow/common/worklog/handlers.py`, `jupyter_ai/workflow/router/default_flow.py`, `jupyter_ai/litellm_lib/run_tools.py`, 향후 `jupyter_ai/tools/worklog_tracking.py`(신규).  
   - 사용자 질문 내용을 기반으로 초기 플랜 스텝을 LLM/규칙으로 생성하고, 스텝 상태를 실제 진행 흐름에 따라 갱신한다.
3. 질문 요약 생성 및 전달 파이프라인 구현: 최초 사용자 입력을 받아 한 줄 요약 생성 → `metadata.query_summary`에 저장 → 웹 컴포넌트에 프롭/스트림으로 공급.  
   - 참고 파일: `jupyter_ai/workflow/router/default_flow.py`, `jupyter_ai/workflow/common/worklog/builders.py`, `jupyter_ai/workflow/common/worklog/markup.py`, `src/web-components/jai-worklog-card.tsx`.
4. 커맨드 실행 레지스트리/큐 추가 및 기존 `command-store`와 동기화.  
   - 참고 파일: `jupyter_ai/tools/command_registry.py`(신규), `src/web-components/worklog/command-store.ts`, 백엔드 커맨드 처리 경로.
5. 프론트엔드 UI 리팩터링: 새로운 스텝 리스트/워크 노드 리스트 컴포넌트, pause/resume 버튼, 상태 배너 구현.  
   - 질문 요약을 헤더에 표시하고, `Steps X/Y` 진행률·워크 노드 토글 UI를 제공한다.  
   - 참고 파일: `src/web-components/jai-workitems-card.tsx`, `src/web-components/jai-plan-card.tsx`, `src/web-components/worklog/components/*`, 신규 `PlanStepList`/`WorkNodeList`.
6. 최종 답변 전용 이벤트 경로(`emit_final_answer`) 정의 및 기존 메시지 파이프라인 통합.  
   - 참고 파일: `jupyter_ai/worklog/worklog_events.py`, `jupyter_ai/server/api.py` 또는 메시지 브로커 경로, UI의 최종 답변 수신 컴포넌트.

## 검증 및 테스트
- **단위 테스트**: `state_models` 병합 로직, `command_registry` 중복 차단, 상태 머신 전이(planning→executing→paused→resumed→finishing) 시나리오.
- **통합 테스트**: `worklog_tracking.execute_with_worklog` 플로우에서 플랜 생성→워크 노드 append→pause/resume→최종 답변 전송까지의 비동기 시나리오 검증.
- **프론트엔드 테스트**: React 컴포넌트 렌더링 및 상태 전환 스냅샷, pause 버튼 UX, “최종 답변 대기” 배너 표시.
- **E2E/회귀 테스트**: 실제 툴 호출 경로에서 중간 메시지가 사용자 채널로 전송되지 않고 최종 답변만 전달되는지 확인하며, 기존 워크로그 엔트리 로딩/머지 동작이 유지되는지 확인한다.
