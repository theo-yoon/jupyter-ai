import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JaiAnswerCard } from '../jai-answer-card';

declare const Buffer: {
  from(data: string, encoding: string): { toString(enc: string): string };
};

const encodePayload = (
  value: unknown,
  options?: { base64?: boolean }
): string => {
  const serialized = JSON.stringify(value);
  if (options?.base64) {
    return Buffer.from(serialized, 'utf-8').toString('base64');
  }
  return serialized;
};

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
      content: 'Work complete. (W1)\nSummary ready. (W2)',
      citations: [
        {
          id: 'w1',
          label: 'W1',
          title: 'Collect data',
          summary: 'Gathered workspace documents.',
          references: [
            {
              label: 'Collect data',
              stage: 'plan',
              ref_id: 'step-1'
            }
          ],
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
      ],
      key_findings: ['Collect data: Gathered workspace documents.'],
      insight_prompts: ['Compare new results with last week.']
    });

    render(<JaiAnswerCard payload={payload} />);

    expect(screen.getByText('Key findings')).toBeInTheDocument();
    expect(
      screen.getByText('Collect data: Gathered workspace documents.')
    ).toBeInTheDocument();
    expect(screen.getByText('Perspectives')).toBeInTheDocument();
    expect(
      screen.getByText('Compare new results with last week.')
    ).toBeInTheDocument();
    expect(screen.getByText('W1')).toBeInTheDocument();
    expect(screen.queryByText('Collect data')).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByText('W1')[0]);
    expect(screen.getByText('Collect data')).toBeInTheDocument();
    expect(screen.getByText('Plan: Collect data')).toBeInTheDocument();
    expect(screen.getByTestId('tool-run')).toHaveTextContent('Search output');
    expect(screen.getByText('+5 / -1')).toBeInTheDocument();

    fireEvent.click(screen.getAllByText('W2')[0]);
    expect(screen.getByText('Summarize findings')).toBeInTheDocument();
    expect(screen.getByText('+2 / -0')).toBeInTheDocument();
    fireEvent.click(screen.getAllByText('W2')[0]);
    expect(screen.queryByText('Summarize findings')).not.toBeInTheDocument();
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

  it('hides work summary details but surfaces next actions from the summary', () => {
    const payload = encodePayload({
      content: 'Answer ready.',
      work_summary: {
        overall_summary: 'Hidden summary',
        notes: 'Internal note',
        next_actions: ['Follow up']
      }
    });

    render(<JaiAnswerCard payload={payload} />);

    expect(screen.queryByText('Work summary')).not.toBeInTheDocument();
    expect(screen.queryByText('Hidden summary')).not.toBeInTheDocument();
    expect(screen.getByText('Next actions')).toBeInTheDocument();
    expect(screen.getByText('Follow up')).toBeInTheDocument();
  });

  it('renders citation chips inline when no explicit markers exist', () => {
    const payload = encodePayload({
      content: 'Answer ready without inline markers.',
      citations: [
        {
          id: 'w1',
          label: 'W1',
          title: 'Notebook summary',
          summary: 'Summarized notebook steps.',
          tool_runs: []
        }
      ]
    });

    render(<JaiAnswerCard payload={payload} />);

    expect(screen.getByText('W1')).toBeInTheDocument();
    expect(
      screen.getByText(content =>
        content.includes('Answer ready without inline markers.')
      )
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText('W1'));
    expect(screen.getByText('Notebook summary')).toBeInTheDocument();
  });

  it('decodes utf-8 base64 payloads', () => {
    const payload = encodePayload(
      {
        content: '한글 노트북 결과입니다.'
      },
      { base64: true }
    );

    render(<JaiAnswerCard payload={payload} />);

    expect(screen.getByText('한글 노트북 결과입니다.')).toBeInTheDocument();
  });

  it('renders markdown content with inline citation chips', () => {
    const payload = encodePayload({
      content: '**Key results**\n- Completed task (W1)\n- Follow-up pending',
      content_format: 'markdown',
      citations: [
        {
          id: 'w1',
          label: 'W1',
          title: 'Implement feature',
          tool_runs: []
        }
      ]
    });

    render(<JaiAnswerCard payload={payload} />);

    expect(screen.getByText('Key results')).toBeInTheDocument();
    expect(
      screen.getByText(content => content.includes('Completed task'))
    ).toBeInTheDocument();
    expect(screen.getByText('W1')).toBeInTheDocument();
    fireEvent.click(screen.getByText('W1'));
    expect(screen.getByText('Implement feature')).toBeInTheDocument();
  });

  it('shows a context badge when payload marks context insufficient', () => {
    const payload = encodePayload({
      content: 'Answer text.',
      context_status: 'insufficient',
      context_missing: ['knowledge_context']
    });

    render(<JaiAnswerCard payload={payload} />);

    expect(screen.getByText('Context refresh needed')).toBeInTheDocument();
  });
});
