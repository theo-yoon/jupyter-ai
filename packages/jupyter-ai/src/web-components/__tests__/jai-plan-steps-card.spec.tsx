import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JaiPlanStepsCard } from '../jai-plan-steps-card';
import { createPlanStep, createWorklogEntry } from './worklog-fixtures';

const runStateControlsMock = jest.fn(({ runState }: { runState: string }) => (
  <div data-testid="run-state-controls">{runState}</div>
));
const planSummaryMock = jest.fn(({ steps }: { steps: unknown[] }) => (
  <div data-testid="plan-summary">{steps.length} steps</div>
));

jest.mock('../worklog/useWorklogEntry', () => ({
  useWorklogEntryCard: jest.fn()
}));
jest.mock('../worklog/components/RunStateControls', () => ({
  RunStateControls: (props: any) => runStateControlsMock(props)
}));
jest.mock('../worklog/components/PlanSummarySection', () => ({
  PlanSummarySection: (props: any) => planSummaryMock(props)
}));

import { useWorklogEntryCard } from '../worklog/useWorklogEntry';

const useWorklogEntryCardMock = jest.mocked(useWorklogEntryCard);

describe('JaiPlanStepsCard', () => {
  beforeEach(() => {
    useWorklogEntryCardMock.mockReset();
    runStateControlsMock.mockClear();
    planSummaryMock.mockClear();
  });

  it('shows placeholder when entry id missing', () => {
    useWorklogEntryCardMock.mockReturnValue({
      entryId: '',
      entry: undefined,
      active: false,
      payload: null
    });
    render(<JaiPlanStepsCard />);
    expect(screen.getByText(/Missing entry identifier/i)).toBeInTheDocument();
  });

  it('returns null when entry is finished', () => {
    const entry = createWorklogEntry({
      status: 'finished',
      plan_steps: [createPlanStep({ status: 'completed' })],
      run_state: 'active'
    });
    useWorklogEntryCardMock.mockReturnValue({
      entryId: entry.entry_id,
      entry,
      active: true,
      payload: null
    });
    const { container } = render(
      <JaiPlanStepsCard entry_id={entry.entry_id} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders plan summary and toggles collapse', () => {
    const entry = createWorklogEntry({
      plan_steps: [
        createPlanStep({ status: 'in_progress', title: 'Research' }),
        createPlanStep({ status: 'pending', title: 'Write up' })
      ],
      run_state: 'active'
    });
    useWorklogEntryCardMock.mockReturnValue({
      entryId: entry.entry_id,
      entry,
      active: true,
      payload: null
    });

    render(<JaiPlanStepsCard entry_id={entry.entry_id} />);
    expect(screen.getByTestId('plan-summary')).toHaveTextContent('2 steps');
    const toggle = screen.getByRole('button', { name: /Collapse plan steps/i });
    fireEvent.click(toggle);
    expect(
      screen.getByRole('button', { name: /Expand plan steps/i })
    ).toBeInTheDocument();
    expect(runStateControlsMock).toHaveBeenCalledWith(
      expect.objectContaining({ runState: entry.run_state })
    );
  });
});
