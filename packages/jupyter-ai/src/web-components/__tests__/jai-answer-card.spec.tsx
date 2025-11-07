import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JaiAnswerCard } from '../jai-answer-card';

const encodePayload = (value: unknown): string => JSON.stringify(value);

const ensureAtob = (): void => {
  globalThis.atob = (input: string): string => input;
};

describe('JaiAnswerCard', () => {
  beforeAll(() => {
    ensureAtob();
  });

  it('shows a placeholder while content is unavailable', () => {
    render(<JaiAnswerCard payload={encodePayload({ content: '' })} />);
    expect(screen.getByText(/Preparing answer/i)).toBeInTheDocument();
  });

  it('renders citations and embedded tool markup with summaries', () => {
    const payload = encodePayload({
      content: 'Work complete.',
      citations: [
        {
          id: 'w1',
          label: 'W1',
          title: 'Collect data',
          summary: 'Gathered workspace documents.',
          metrics: {
            lines_added: 5,
            lines_removed: 1
          },
          tool_runs: [
            {
              tool_call_id: 'tool-1',
              label: 'Search docs',
              markup: '<div data-testid="tool-run">Search output</div>',
              summary: 'Search output',
              change_summary: {
                lines_added: 5,
                lines_removed: 1
              }
            }
          ]
        },
        {
          id: 'w2',
          label: 'W2',
          title: 'Summarize findings',
          summary: 'Created executive summary.',
          tool_runs: [
            {
              tool_call_id: 'tool-2',
              label: 'Summarize',
              markup: '<div>Summary</div>',
              change_summary: {
                lines_added: 2
              }
            }
          ]
        }
      ]
    });

    render(<JaiAnswerCard payload={payload} />);

    expect(screen.getByText('Collect data')).toBeInTheDocument();
    expect(screen.getByText('W1')).toBeInTheDocument();
    expect(screen.getByTestId('tool-run')).toHaveTextContent('Search output');
    expect(screen.getByText('+5 / -1')).toBeInTheDocument();

    fireEvent.click(screen.getByText('W2'));
    expect(screen.getByText('Summarize findings')).toBeInTheDocument();
    expect(screen.getByText('+2 / -0')).toBeInTheDocument();
  });

  it('falls back to rendering next actions when no work summary exists', () => {
    const payload = encodePayload({
      content: 'Next steps.',
      next_actions: ['Review draft', 'Ship update']
    });
    render(<JaiAnswerCard payload={payload} />);
    expect(screen.getByText('Next actions')).toBeInTheDocument();
    expect(screen.getByText('Review draft')).toBeInTheDocument();
    expect(screen.getByText('Ship update')).toBeInTheDocument();
  });
});
