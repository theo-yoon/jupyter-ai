import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JaiWorklogCard } from '../jai-worklog-card';
import {
  createPlanStep,
  createWorkNode,
  createWorklogEntry
} from './worklog-fixtures';

const workItemsSectionMock = jest.fn(({ title }: { title: string }) => (
  <div data-testid="worklog-items-section">{title}</div>
));

jest.mock('../worklog/useWorklogEntry', () => ({
  useWorklogEntryCard: jest.fn()
}));
jest.mock('../worklog/components/WorkItemsSection', () => ({
  WorkItemsSection: (props: any) => workItemsSectionMock(props)
}));

import { useWorklogEntryCard } from '../worklog/useWorklogEntry';

const useWorklogEntryCardMock = jest.mocked(useWorklogEntryCard);

describe('JaiWorklogCard', () => {
  beforeEach(() => {
    useWorklogEntryCardMock.mockReset();
    workItemsSectionMock.mockClear();
  });

  it('shows placeholder when entry id is missing', () => {
    useWorklogEntryCardMock.mockReturnValue({
      entryId: '',
      entry: undefined,
      active: false,
      payload: null
    });
    render(<JaiWorklogCard />);
    expect(screen.getByText(/Missing entry identifier/i)).toBeInTheDocument();
  });

  it('renders header and work items when entry is active', () => {
    const entry = createWorklogEntry({
      summary: 'Workspace sync',
      metadata: { query_summary: 'Sync workspace files' },
      plan_steps: [
        createPlanStep({ status: 'in_progress', title: 'Collect data' })
      ],
      work_nodes: [createWorkNode({ title: 'Collect data' })]
    });
    useWorklogEntryCardMock.mockReturnValue({
      entryId: entry.entry_id,
      entry,
      active: true,
      payload: null
    });

    render(<JaiWorklogCard entry_id={entry.entry_id} />);

    expect(screen.getByText('Workspace sync')).toBeInTheDocument();
    expect(screen.getByTestId('worklog-items-section')).toHaveTextContent(
      'Working'
    );
  });

  it('displays finished title when work completed', () => {
    const entry = createWorklogEntry({
      plan_steps: [
        createPlanStep({ status: 'completed' }),
        createPlanStep({ status: 'completed' })
      ],
      work_nodes: [createWorkNode({ title: 'Review results' })],
      status: 'finished'
    });
    useWorklogEntryCardMock.mockReturnValue({
      entryId: entry.entry_id,
      entry,
      active: true,
      payload: null
    });

    render(<JaiWorklogCard entry_id={entry.entry_id} />);
    expect(screen.getByTestId('worklog-items-section')).toHaveTextContent(
      'Finished working'
    );
  });
});
