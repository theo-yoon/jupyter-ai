# Workflow Service Architecture

## 목적
- **단일 책임 원칙(SRP)**을 철저히 지키고, 서비스 간 결합도를 낮춘다.
- 순환 의존성을 제거해 테스트 가능성과 확장성을 확보한다.
- “헬퍼 함수/플래그” 의존에서 벗어나 명확한 API와 레이어 구분을 제공한다.

## 레이어 구조

### 1. 도메인 레이어 (`packages/jupyter-ai/jupyter_ai/workflow/domain/...`)
- 순수 데이터 모델과 상태 전이 로직만 포함한다.
- JupyterLab, planning_flow 모듈에 대한 의존성이 없다.
- 예: `PlanState`(read/write), `PlanProgressSnapshot`, `WorkplanEvents`.
- 도메인 객체는 **단일 책임**을 갖도록 작은 단위로 분리한다.  
  (예: “plan 진행도 계산” vs “worklog 스냅샷 병합”)

### 2. 어댑터 레이어 (`packages/jupyter-ai/jupyter_ai/workflow/planning_flow/adapters/...`)
- JupyterLab 플래닝 객체(`PlanContextManager`, `StepManager`, `WorklogTracker` 등)를 도메인 인터페이스에 맞춰 감싼다.
- 도메인 레이어에서 정의한 프로토콜(예: `PlanStore`, `TrackerGateway`)을 구현한다.
- Adapter는 변환 외 작업을 하지 않는다. 비즈니스 규칙은 도메인 레이어로 되돌린다.

### 3. 애플리케이션 레이어 (서비스 파사드)
- `PlanStateFacade`, `WorklogFacade`, `SummaryFacade` 등으로 구성한다.
- 각 파사드는 **하나의 유스케이스**를 다룬다. (예: “플랜 초기화”, “플랜 상태 저장”)
- 파사드는 도메인 서비스 + 어댑터를 의존성 주입으로 받아 orchestration만 담당한다.
- 플래그, 다중 책임 함수, 임시 헬퍼 함수를 사용하지 않는다.

## 의존성 규칙
```
planning_flow (nodes) --> Facade (application)
Facade --> Domain Interfaces
Facade --> Adapter 구현 (injected)
Adapter --> planning_flow / External libs
```
- 역방향 의존성은 허용되지 않는다. (예: 도메인 레이어가 어댑터를 import 금지)
- **모든 import는 패키지 절대 경로**를 사용한다.  
  상대 경로(`from ..foo import bar`) 대신 `from jupyter_ai.workflow...` 형식으로 명시하여
  모듈 이동과 리팩터링을 단순화한다.

## 함수/메서드 가이드
- **하나의 함수 = 하나의 작업**.  
  반환 값 혹은 사이드 이펙트는 단일 목적이어야 한다.
- 상태 변경 전과 후를 명확히 표현한다.  
  예: `advance_plan_step(step_id)` → 성공 여부 또는 변경된 스냅샷 반환.
- **플래그 매개변수 금지**. 분기를 외부로 올리고, 필요하면 전략 객체/별도 메서드 사용.
- **임시 헬퍼 금지**. 동일 로직 반복 시 별도 클래스로 책임 이전하거나 도메인/어댑터에 로직 이동.
- 모든 public 메서드는 타입힌트와 docstring으로 의도를 명확히 기술한다.

## 서비스 컨테이너
- `WorkflowServiceContainer`는 **생성/조립 책임만** 가진다.
- 캐싱 외 추가 로직(분기/헬퍼) 금지.
- 컨테이너는 인터페이스 기반으로 서비스를 반환한다.  
  예: `container.plan_state()` → `PlanStateFacade` 인터페이스 구현체 반환.

## 테스트 전략
- 도메인: 순수 단위 테스트 (fixture 없이)
- 어댑터: planning_flow mock/stub 활용, API 계약 검증
- 파사드: 도메인+어댑터 더블 주입으로 orchestration 검증
- 플로우 테스트: 실제 파사드 wiring 검증 (기존 `tests/workflow/...`)

## 리팩터링 체크리스트
1. 도메인 레이어 추출 및 인터페이스 정의
2. 기존 `PlanStateService` 코드를 도메인/어댑터/파사드로 분해
3. planning nodes가 컨테이너에서 새 파사드를 주입받도록 교체
4. 기존 각종 “헬퍼”/“플래그” 검출 → 책임을 분리한 모듈로 이동
5. 테스트 갱신 및 문서 업데이트

## 넘어야 할 과제
- 계획/트래커 동기화 로직을 도메인 규칙과 어댑터 구현으로 분리
- 워크로그/요약 서비스도 동일 패턴으로 재구조화
- 단계별 PR로 진행하여 회귀 위험을 줄이고 테스트를 병행

---
궁극적으로 이 구조는 “서비스 레이어는 orchestration만”, “도메인 레이어는 핵심 규칙만”이라는 원칙을 지키며, 순환참조 없이 확장 가능한 워크플로우 아키텍처를 보장한다.
