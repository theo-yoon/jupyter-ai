import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { WorkNodeList } from '../worklog/components/WorkNodeList/WorkNodeList';
import type { WorkNode } from '../worklog/types';

const buildToolNode = (overrides: Partial<WorkNode> = {}): WorkNode => ({
  node_id: 'node-base',
  node_type: 'tool_call',
  status: 'completed',
  step_id: null,
  title: 'Run tool',
  body: null,
  payload: {
    kind: 'tool_response',
    tool_name: 'apply_patch',
    result: {
      type: 'json',
      data: {
        lines_added: 12,
        lines_removed: 5
      }
    }
  },
  metadata: {
    tool_name: 'apply_patch'
  },
  ...overrides
});

describe('WorkNodeList', () => {
  it('shows tool summary with change stats badge when metadata summary exists', () => {
    const nodes = [
      buildToolNode({
        node_id: 'node-1',
        metadata: {
          summary: 'Updated README copy',
          tool_name: 'apply_patch',
          work_item_title: 'README.md'
        }
      })
    ];

    render(<WorkNodeList nodes={nodes} />);

    expect(screen.getByText('Updated README copy')).toBeInTheDocument();
    const chips = screen.getAllByText('+12 / -5');
    expect(chips.length).toBeGreaterThan(0);
  });

  it('falls back to tool name and work item title when summary missing', () => {
    const nodes = [
      buildToolNode({
        node_id: 'node-2',
        metadata: {
          tool_name: 'search_docs',
          work_item_title: 'dataset.csv'
        },
        payload: {
          kind: 'tool_response',
          tool_name: 'search_docs',
          result: {
            type: 'text',
            content: 'Search results'
          }
        }
      })
    ];

    render(<WorkNodeList nodes={nodes} />);

    expect(screen.getByText('dataset.csv')).toBeInTheDocument();
    expect(screen.queryByText('search_docs')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('dataset.csv'));
    expect(screen.getByText('search_docs')).toBeInTheDocument();
  });

  it('expands detail panel when summary row clicked', async () => {
    const nodes = [
      buildToolNode({
        node_id: 'node-3',
        metadata: {
          summary: 'Listed files',
          tool_name: 'list_files'
        },
        payload: null,
        body: 'file-a\nfile-b'
      })
    ];

    render(<WorkNodeList nodes={nodes} />);

    fireEvent.click(screen.getByText('Listed files'));
    const textMatcher = (_: string, element?: Element | null) =>
      Boolean(element?.textContent?.includes('file-a'));
    const matches = await screen.findAllByText(textMatcher);
    expect(matches.length).toBeGreaterThan(0);
  });

  it('shows Thinking indicator for reasoning nodes in progress', () => {
    const nodes: WorkNode[] = [
      {
        node_id: 'node-thinking',
        node_type: 'self_reflection',
        status: 'in_progress',
        step_id: null,
        title: 'Draft response',
        body: null,
        payload: null,
        metadata: {}
      }
    ];

    render(<WorkNodeList nodes={nodes} />);
    const reasoningTitle = screen.getByLabelText('Thinking');
    expect(reasoningTitle).toHaveAttribute('data-title-pulse', 'true');
  });

  it('shows tool running indicator with tool name', () => {
    const nodes = [
      buildToolNode({
        node_id: 'node-running',
        status: 'in_progress',
        metadata: {
          tool_name: 'apply_patch'
        }
      })
    ];

    render(<WorkNodeList nodes={nodes} />);
    const title = screen.getByText('Run apply_patch');
    expect(title).toHaveAttribute('data-title-pulse', 'true');
  });

  it('omits completed status indicators', () => {
    const nodes = [
      buildToolNode({
        node_id: 'node-no-status',
        metadata: {
          tool_name: 'create_notebook',
          work_item_title: 'Create a notebook'
        }
      })
    ];

    render(<WorkNodeList nodes={nodes} />);
    expect(screen.queryByText('Completed')).not.toBeInTheDocument();
  });

  it('renders reasoning summary with body preview', () => {
    const nodes: WorkNode[] = [
      {
        node_id: 'node-reasoning',
        node_type: 'self_reflection',
        status: 'completed',
        step_id: null,
        title: 'Reasoning block',
        body: 'First create the notebook, then insert a cell.',
        payload: null,
        metadata: {
          summary_title: 'Plan next actions',
          summary_details: 'Confirm the new notebook runs the Hello World cell.'
        }
      }
    ];

    render(<WorkNodeList nodes={nodes} />);
    expect(screen.getByText('Plan next actions')).toBeInTheDocument();
    expect(
      screen.queryByText('Confirm the new notebook runs the Hello World cell.')
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Plan next actions'));
    expect(
      screen.getByText('Confirm the new notebook runs the Hello World cell.')
    ).toBeInTheDocument();
    const bodyMatches = screen.getAllByText(
      'First create the notebook, then insert a cell.'
    );
    expect(bodyMatches.length).toBeGreaterThan(0);
  });

  it('shows concise titles for final answer nodes without exposing metadata.summary', () => {
    const nodes: WorkNode[] = [
      {
        node_id: 'node-final-answer',
        node_type: 'self_reflection',
        status: 'completed',
        step_id: null,
        title: 'Deliver final answer',
        body: '최종 답변 본문을 여기에 노출합니다.',
        payload: null,
        metadata: {
          node_kind: 'final_answer',
          summary_title: '최종 답변 요약',
          summary_details: '주요 결과만 정리했습니다.',
          summary: '이 텍스트는 목록에서 보이면 안 됩니다.'
        }
      }
    ];

    render(<WorkNodeList nodes={nodes} />);

    expect(screen.getByText('최종 답변 요약')).toBeInTheDocument();
    expect(
      screen.queryByText('이 텍스트는 목록에서 보이면 안 됩니다.')
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('최종 답변 요약'));
    expect(screen.getByText('주요 결과만 정리했습니다.')).toBeInTheDocument();
    expect(
      screen.getByText('최종 답변 본문을 여기에 노출합니다.')
    ).toBeInTheDocument();
  });

  it('renders reasoning summary in English even when text is Korean', () => {
    const nodes: WorkNode[] = [
      {
        node_id: 'node-reasoning-ko',
        node_type: 'self_reflection',
        status: 'completed',
        step_id: null,
        title: '추론 단계',
        body: '다음 셀을 실행하고, 결과를 확인한다.',
        payload: null,
        metadata: {
          summary_title: '셀 실행 준비'
        }
      }
    ];

    render(<WorkNodeList nodes={nodes} />);
    expect(screen.getByText('셀 실행 준비')).toBeInTheDocument();
  });

  it('shows tool subtitle only when expanded', () => {
    const nodes = [
      buildToolNode({
        node_id: 'node-subtitle',
        metadata: {
          tool_name: 'run_tests',
          work_item_title: 'tests.py'
        },
        payload: {
          kind: 'tool_response',
          tool_name: 'run_tests',
          result: {
            type: 'text',
            content: 'ok'
          }
        }
      })
    ];

    render(<WorkNodeList nodes={nodes} />);
    expect(screen.queryByText('run_tests')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('tests.py'));
    expect(screen.getByText('run_tests')).toBeInTheDocument();
  });

  it('shows tool text output immediately when expanded', () => {
    const nodes = [
      buildToolNode({
        node_id: 'node-inline-text',
        metadata: {
          summary: 'Printed greeting',
          tool_name: 'echo_text'
        },
        payload: {
          kind: 'tool_response',
          tool_name: 'echo_text',
          result: {
            type: 'text',
            content: 'Hello, World!'
          }
        }
      })
    ];

    render(<WorkNodeList nodes={nodes} />);
    fireEvent.click(screen.getByText('Printed greeting'));
    expect(screen.getByText('Hello, World!')).toBeInTheDocument();
  });
});
