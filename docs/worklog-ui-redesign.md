# 워크로그 UI 개편 가이드

이 문서는 `jai-worklog-card` 기반 워크로그 UI를 스크린샷과 동일한 스타일로 재구성하기 위한 설계 지침을 정리한다. 레이아웃, 플랜/워크 아이템 표현, 상태 및 시간 표시 방식, 추가 개선 아이디어 순으로 설명한다.

## 카드 레이아웃 재구성

- **파일**: `packages/jupyter-ai/src/web-components/jai-worklog-card.tsx`
- “Timeline” 단일 블록을 제거하고 `Working`, `Completed or Aborted`(필요 시 명칭 조정) 두 섹션으로 분리한다. 각 섹션에 렌더링할 워크 노드 목록을 필터링한 뒤 자식 컴포넌트에 전달한다.
- 플랜 진행도는 헤더 하단 텍스트 배너로 노출한다. 예: `2 / 3 tasks completed`. `plan_steps` 완료 수를 계산해 문구 및 섹션 제목 위에 배치한다.
- `RunStateControls`와 승인(Plan/Final) 경고는 한 줄 툴바 형태로 축소한다. 버튼 그룹과 경고 문구를 좌우 정렬해 여백을 줄인다.
- 섹션 접기는 전체 카드에서 공유하는 `expanded` 상태 대신 섹션별 상태를 도입해 “Working”과 “Completed”를 독립적으로 열고 닫을 수 있게 한다.
- 필터링 로직과 진행도 계산을 `useMemo` 수준으로 정리해 렌더링 시 매번 새 배열을 만들지 않도록 주의한다.

## 플랜 스텝 표현

- **파일**: `packages/jupyter-ai/src/web-components/worklog/components/PlanStepList.tsx`
- 카드형 리스트 대신 트리형 목록으로 전환한다. `parent_step_id`와 `child_step_ids`를 사용해 재귀적으로 렌더링하며, 단계 깊이에 따라 들여쓰기(`ml`) 또는 좌측 가이드 라인을 추가한다.
- 상태 표시는 칩 대신 텍스트/아이콘으로 대체한다.
  - `pending`: 회색 `◦` 아이콘
  - `in_progress`: 다른 컴포넌트와 동일한 녹색 계열 아이콘을 사용하고, 얇은 회전 링과 은은한 펄스 정도로만 반짝임을 준다.
  - `completed`: 제목 취소선 또는 옅은 회색 텍스트 + `✓`
  - `failed`: 빨간 텍스트와 “(blocked)” 꼬리표
- 스텝 텍스트는 워크 아이템보다 한 단계 더 작은 크기(예: `fontSize: '0.8rem'`)로 맞추고, letter-spacing을 소폭 늘려 섬세하게 보이도록 한다. 아이콘과 텍스트가 정확히 수직 정렬되도록 `alignItems: 'center'`와 line-height를 함께 조절한다.
- 상위 컴포넌트(`jai-worklog-card`)가 전체 완료 수를 계산해 `PlanStepList`로 전달하면, 리스트는 상태/들여쓰기 렌더링에 집중한다.

## 워크 아이템(Work Node) 표현

- **파일**: `packages/jupyter-ai/src/web-components/worklog/components/WorkNodeList.tsx`
- 세로 타임라인 형태의 리스트로 재구성한다. 왼쪽에는 얇은 라인과 원형 아이콘을 두고, 오른쪽에는 한 줄 요약만 노출한다.
- 라인은 “아이콘이 있는 행 → 선만 있는 빈 행 → 다음 아이콘 행” 순으로 반복해 아이콘이 항상 선의 중앙에 위치하도록 한다. 필요하다면 빈 `Box`를 삽입하거나 `::before`/`::after` 가상 요소를 활용해 이 구조를 구현하고, 선 두께는 1px 내외로 가볍게 유지한다.
- 각 워크 아이템은 기본적으로 접힌 상태이며, 사용자가 펼친 항목은 상태를 기억해 재렌더링 후에도 열린 채 유지한다.
- 진행 상태는 아이콘 컬러/반짝임으로만 표현한다. 텍스트 라벨(`completed`, `in_progress`)과 단계/시간 표시는 숨긴다.
- 본문 타이포그래피는 기본 `body2`보다 작고 세련된 스타일(예: `fontSize: '0.82rem'`, `fontWeight: 500`, `letterSpacing: '0.01em'`)을 사용한다. 메타데이터/보조 텍스트는 `fontSize: '0.7rem'` 이하로 더 줄여 계층을 명확히 한다.
- 펼쳤을 때만 페이로드/메타데이터를 보여주고, 콘솔/JSON/diff 등은 기존 포맷터를 재사용하되 최소한의 여백만 준다.
- `iconForNodeType`은 `@mui/icons-material`의 세련된 아이콘(예: `SearchRounded`, `TerminalRounded`, `SummarizeRounded`)으로 매핑하고, `status === 'in_progress'` 조건에서 shimmer 애니메이션을 건다.

## 상태/시간 헬퍼 수정

- **파일**: `packages/jupyter-ai/src/web-components/worklog/status.ts`, `.../format.ts`
- `describePlanStatus`, `describeWorkStatus` 반환값을 칩 메타 대신 `{ label, color, icon }` 등 텍스트 중심 구조로 변경한다.
- 타임스탬프는 `toLocaleTimeString` 옵션을 `hour: '2-digit', minute: '2-digit'`으로 좁혀 `10:32`처럼 짧게 표시한다. 필요 시 상대 시각(예: `5m ago`) 포맷터를 추가한다.

## 추가 개선 아이디어

1. 커맨드 실행 패널이 필요하다면 `CommandExecutionList`를 같은 카드에 배치하고 상단 탭 또는 토글로 구분한다.
2. `ProgressHeader`, `NodeToggle` 등 공통 UI를 캡슐화해 스타일 변화를 컴포넌트 단위로 관리한다.
3. 긴 텍스트(요약, 노트)는 `title` 속성이나 툴팁으로 전문을 노출하고 기본 뷰는 한 줄로 제한한다.

## 적용 순서 제안

1. `jai-worklog-card.tsx` 레이아웃을 두 섹션 구조로 재편하고 진행도 계산을 추가한다.
2. `PlanStepList.tsx`, `WorkNodeList.tsx`를 새로운 트리/리스트 스타일로 교체한다.
3. 상태/시간 헬퍼를 조정해 새로운 UI와 맞춘다.
4. 선택적 기능(커맨드 패널, 공통 컴포넌트)을 도입해 유지보수를 단순화한다.

## 진행 중 상태 강조 & 애니메이션

- 진행 중인 스텝/워크 아이콘에는 `sx`를 이용해 반짝이는 애니메이션을 적용한다. 예:
  ```ts
  const ACTIVE_ICON_SX = {
    animation: "jaiShimmer 1.4s ease-in-out infinite",
    "@keyframes jaiShimmer": {
      "0%": { filter: "drop-shadow(0 0 0 rgba(255,255,255,0))" },
      "50%": { filter: "drop-shadow(0 0 6px rgba(255,255,255,0.6))" },
      "100%": { filter: "drop-shadow(0 0 0 rgba(255,255,255,0))" },
    },
  } as const;
  ```
  `PlanStepList`와 `WorkNodeList`에서 `status === 'in_progress'`일 때 위 스타일을 펼쳐주면 된다.
- 아이콘은 `describePlanStatus`/`describeWorkStatus`에서 반환한 `icon` 값을 활용해 `<span>` 또는 MUI `SvgIcon`으로 렌더링한다. 상태별 색상은 CSS 변수(`--jai-active-node`, `--jai-pending-node` 등)를 활용하면 테마 대응성이 높아진다.

## 스텝 리스트 하단 고정 전략

- 상위 채팅 확장을 수정하지 않고 카드 내부에서만 스텝 리스트를 “하단 고정”처럼 보이게 만들 수 있다.
  1. `jai-worklog-card.tsx` 루트 `Paper`를 `display: flex; flex-direction: column; max-height: 100%;`로 변경한다.
  2. 워크 아이템 섹션을 감싸는 컨테이너에 `flex: 1; overflow-y: auto;`를 지정해 스크롤을 이 영역으로 한정한다.
  3. 스텝 섹션을 아래와 같이 감싸 sticky 효과를 준다.
     ```tsx
     <Box
       sx={{
         position: 'sticky',
         bottom: 0,
         backgroundColor: 'var(--jp-layout-color0)',
         borderTop: '1px solid var(--jp-border-color2)',
         pt: 1.5
       }}
     >
       <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)' }}>
         Steps {completedSteps}/{totalSteps}
       </Typography>
       <PlanStepList ... />
     </Box>
     ```
- sticky가 정상 동작하려면 카드 상위 컨테이너가 `overflow: visible` 상태여야 하므로, 레이아웃 조정 후 스크롤이 카드 내부에서만 일어나는지 확인한다.
- 채팅 패널 전체 하단에 완전히 고정하고 싶다면 라이트 DOM 상위 요소에 `position: sticky`를 적용해야 하는데, 이는 별도 확장에 손을 대야 하므로 우선 카드 내부 sticky 방식으로 구현한다.

## 색상 & 타이포그래피 가이드

- **컬러 팔레트**
  - 기본 글자는 `var(--jp-ui-font-color1)`(약한 회색), 보조 텍스트는 `var(--jp-ui-font-color2)`를 사용해 대비를 확보한다.
  - 강조 색상은 상태별로 일관성 있게 사용한다: 진행 중 중간톤 녹색(`#2E7D32` 계열), 완료 진한 녹색(`#1B5E20`), 실패 빨강(`#B71C1C`), 보류 회색(`#616161`). CSS 변수로 추출해 테마 스위칭에 대비한다.
  - 배경은 `var(--jp-layout-color0)`(카드), `var(--jp-layout-color1)`(리스트 항목) 두 단계만 사용해 계층감을 만든다. 강조 섹션은 살짝 짙은 회색 보더(`var(--jp-border-color2)`)로 구분한다.
- **타이포그래피**
  - 헤더(`Agent worklog`, 진행도 등)는 `subtitle1`/`subtitle2` 변형을 기반으로 하고, 최대 600의 fontWeight를 유지한다.
  - 워크 아이템 및 스텝 본문은 `fontSize: 0.8~0.85rem` 범위로 제한하고, `letterSpacing`을 0.008~0.012em 정도로 늘려 세련된 인상을 준다. 콘솔/코드 출력은 기존처럼 `var(--jp-code-font-family)`를 사용하되 본문보다 약간 큰 0.85rem로 유지한다.
  - 보조 정보(타임스탬프, 메타데이터 라벨)는 `caption` 이하 크기로 축소하고, 색상을 `var(--jp-ui-font-color2)`로 낮춰 시각적 계층을 만든다.
- **간격**
  - 섹션 간 `Stack spacing`은 1.5~2(12~16px)로, 리스트 항목 내부 padding은 12px 전후로 통일한다.
  - sticky 스텝 섹션 상단에는 `pt: 1.5` 정도의 여백을 주어 스크롤 영역과 부드럽게 연결한다.
- **포커스/호버 상태**
  - 키보드 탐색을 고려해 `:focus-visible`에서 `outline` 대신 얇은 보더 색상 변경(`#4FC3F7` 같은 밝은 파랑)을 적용한다.
  - 호버 시 배경을 살짝 밝게(`rgba(255,255,255,0.05)`) 바꾸고, 애니메이션은 150ms 이하로 제한해 산만함을 줄인다.
