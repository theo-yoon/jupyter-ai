import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JaiWorkitemsCard } from '../jai-workitems-card';
import {
  createPlanStep,
  createWorkNode,
  createWorklogEntry
} from './worklog-fixtures';

const workItemsSectionMock = jest.fn(({ title }: { title: string }) => (
  <div data-testid="work-items-section">{title}</div>
));

jest.mock('../worklog/useWorklogEntry', () => ({
  useWorklogEntryCard: jest.fn()
}));
jest.mock('../worklog/components/WorkItemsSection', () => ({
  WorkItemsSection: (props: any) => workItemsSectionMock(props)
}));

import { useWorklogEntryCard } from '../worklog/useWorklogEntry';

const useWorklogEntryCardMock = jest.mocked(useWorklogEntryCard);

describe('JaiWorkitemsCard', () => {
  beforeEach(() => {
    useWorklogEntryCardMock.mockReset();
    workItemsSectionMock.mockClear();
  });

  it('shows placeholder when entry id missing', () => {
    useWorklogEntryCardMock.mockReturnValue({
      entryId: '',
      entry: undefined,
      active: false,
      payload: null
    });
    render(<JaiWorkitemsCard />);
    expect(screen.getByText(/Missing entry identifier/i)).toBeInTheDocument();
  });

  it('renders working section when entry active', () => {
    const entry = createWorklogEntry({
      plan_steps: [
        createPlanStep({ status: 'in_progress' }),
        createPlanStep({ status: 'pending' })
      ],
      work_nodes: [createWorkNode({ title: 'Search docs' })],
      status: 'working',
      run_state: 'active'
    });
    useWorklogEntryCardMock.mockReturnValue({
      entryId: entry.entry_id,
      entry,
      active: true,
      payload: null
    });

    render(<JaiWorkitemsCard entry_id={entry.entry_id} />);
    expect(screen.getByTestId('work-items-section')).toHaveTextContent(
      'Working'
    );
  });

  it('shows status notice when run failed', () => {
    const entry = createWorklogEntry({
      plan_steps: [createPlanStep({ status: 'completed' })],
      work_nodes: [],
      status: 'failed',
      run_state: 'active'
    });
    useWorklogEntryCardMock.mockReturnValue({
      entryId: entry.entry_id,
      entry,
      active: true,
      payload: null
    });

    render(<JaiWorkitemsCard entry_id={entry.entry_id} />);
    expect(
      screen.getByText(/Run failed\. Check work items for details\./i)
    ).toBeInTheDocument();
  });
});
