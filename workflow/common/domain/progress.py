from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Sequence


class FlowPhase(Enum):
    """Lifecycle phases for a workflow run."""

    PLANNING = auto()
    EXECUTING = auto()
    FINISHING = auto()


@dataclass(frozen=True)
class PlanProgressSnapshot:
    """Immutable view of plan progress used to route flow transitions."""

    step_ids: Sequence[str]
    statuses: Sequence[str]
    active_step_id: str | None

    @property
    def total_steps(self) -> int:
        return len(self.step_ids)

    @property
    def remaining_steps(self) -> int:
        return sum(1 for status in self.statuses if status in ("pending", "in_progress"))

    @property
    def is_finished(self) -> bool:
        if self.total_steps == 0:
            return True
        if self.remaining_steps > 0:
            return False
        return self.active_step_id is None

    @property
    def has_remaining_work(self) -> bool:
        return not self.is_finished

    def next_pending_index(self) -> int | None:
        for index, status in enumerate(self.statuses):
            if status in ("pending", "in_progress"):
                return index
        return None
