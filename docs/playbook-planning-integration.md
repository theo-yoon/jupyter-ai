# Playbook Actions → Planning Flow Injection

목표는 Planning Flow가 반복 실패할 때, 플레이북 메타데이터에 담긴 자동화 단계를 Plan Step/Work Item으로 주입해 해결을 이어 가도록 하는 것이다. 추가 구현 전에 구조만 정의해 둔다.

## 처리 흐름 개요

1. `KnowledgeCoordinator`에서 플레이북 메타데이터(`metadata.playbook`)를 파싱해 `KnowledgeContext`에 `playbook_spec`을 보존한다.
2. Planning Flow의 `RootNode.prep_async`가 기본 plan을 만든 직후 `playbook_spec`이 있으면 전용 어댑터를 호출해 Plan Step 및 Work Node를 생성한다.
3. 생성된 Step/Work Node는 `PlanStepManager`와 `Worklog`에 병합되어 기존 승인·툴 실행 로직을 그대로 재사용한다.

## 변경 포인트

- `packages/jupyter-ai/jupyter_ai/default_flow/knowledge.py`
  - `KnowledgeContext` 구조 확장 (`playbook_spec` 필드 추가).
  - `_build_payload`에서 `metadata.playbook`을 `PlaybookSpec`으로 변환.

- `packages/jupyter-ai/jupyter_ai/default_flow/planning_flow.py`
  - `RootNode.prep_async` 내 `generate_plan_steps` 직후 `playbook_spec` 존재 시 Plan Step 주입.
  - 주입 로직은 별도 util 함수로 분리 (아래 어댑터 참조).

- `packages/jupyter-ai/jupyter_ai/playbook_flow/adapters.py` (신규)
  - `build_plan_steps_from_playbook(spec)` → `PlanStep` 리스트 생성.
  - `build_work_nodes_from_playbook(spec)` → `WorkNode` 리스트 생성 (command/instruction에 따라 payload 채움).
  - Planning Flow가 이 어댑터를 호출해 step/work node 병합.

- `packages/jupyter-ai/jupyter_ai/worklog/builders.py`
  - 특별한 분기 없이 merge 시 새 step/work node가 반영되도록 기존 로직 사용.

## 실행 시나리오

1. Planning Flow가 일반 플랜을 생성하고 실행을 시도하다 실패.
2. 실패 핸들러에서 `playbook_spec`이 존재하면 Plan Step을 동적으로 추가.
3. 이후 Planning Flow는 해당 Step에 따라 자동으로 재시도하거나 사용자 승인 후 진행.
4. Playbook action이 command/tool인 경우 `WorkNode` payload에 명령/파라미터를 담아 기존 tool 실행 경로를 사용.
5. 액션 완료 후 worklog에 결과가 축적되며, 실패 시 `support_url`을 step metadata에 넣어 UI가 문의 링크를 제공.

## 테스트 메모

- 단위 테스트에서 `KnowledgeContext.playbook_spec`이 있는 상황을 만들어 Plan Step/Work Node가 생성되는지 확인.
- command action이 tool 호출로 변환되는지, instruction은 텍스트 노드로 추가되는지 검증.
- 플레이북 주입 후 Planning Flow가 정상적으로 다음 Step을 실행하는지 통합 테스트로 검증.
