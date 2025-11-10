import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JaiPlanCard } from '../jai-plan-card';
import { createWorklogEntry } from './worklog-fixtures';

jest.mock('../worklog/useWorklogEntry', () => ({
  useWorklogEntryCard: jest.fn()
}));

import { useWorklogEntryCard } from '../worklog/useWorklogEntry';

const useWorklogEntryCardMock = jest.mocked(useWorklogEntryCard);

describe('JaiPlanCard', () => {
  beforeEach(() => {
    useWorklogEntryCardMock.mockReset();
  });

  it('shows a placeholder when entry id is missing', () => {
    useWorklogEntryCardMock.mockReturnValue({
      entryId: '',
      entry: undefined,
      active: false,
      payload: null
    });

    render(<JaiPlanCard />);
    expect(screen.getByText(/Missing entry identifier/i)).toBeInTheDocument();
  });

  it('renders worklog metadata when entry is provided', () => {
    const entry = createWorklogEntry({
      summary: 'Weekly plan',
      metadata: { query_summary: 'Summarize notebooks' }
    });
    useWorklogEntryCardMock.mockReturnValue({
      entryId: entry.entry_id,
      entry,
      active: true,
      payload: null
    });

    render(<JaiPlanCard entry_id={entry.entry_id} />);
    expect(screen.getByText('Weekly plan')).toBeInTheDocument();
    expect(
      screen.getByText(/Review the worklog and plan steps/i)
    ).toBeInTheDocument();
  });
});
