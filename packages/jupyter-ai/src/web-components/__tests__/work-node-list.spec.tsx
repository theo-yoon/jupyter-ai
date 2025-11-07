import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { WorkNodeList } from '../worklog/components/WorkNodeList/WorkNodeList';
import type { WorkNode } from '../worklog/types';

const buildToolNode = (
  overrides: Partial<WorkNode> = {}
): WorkNode => ({
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

    expect(
      screen.getByText('search_docs — dataset.csv')
    ).toBeInTheDocument();
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
});
