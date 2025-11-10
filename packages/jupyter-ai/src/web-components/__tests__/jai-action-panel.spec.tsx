import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JaiActionPanel } from '../jai-action-panel';

const encodePayload = (value: unknown): string => JSON.stringify(value);

describe('JaiActionPanel', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('returns null when no panel payload is available', () => {
    const { container } = render(<JaiActionPanel />);
    expect(container.firstChild).toBeNull();
  });

  it('dispatches jai:run-command and updates status when action completes', async () => {
    const payload = encodePayload({
      panel: {
        panel_id: 'panel-1',
        title: 'Follow-up actions',
        actions: [
          {
            action_id: 'action-1',
            label: 'Run search',
            command: {
              type: 'jupyterlab_command',
              command_id: 'search:execute',
              args: { query: 'docs' }
            }
          }
        ]
      }
    });

    const runHandler = jest.fn();
    window.addEventListener('jai:run-command', event =>
      runHandler((event as CustomEvent).detail)
    );

    render(<JaiActionPanel payload={payload} />);

    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(runHandler).toHaveBeenCalledTimes(1);
    const detail = runHandler.mock.calls[0][0];
    expect(detail).toMatchObject({
      commandId: 'search:execute',
      args: { query: 'docs' }
    });

    await act(async () => {
      window.dispatchEvent(
        new CustomEvent('jai:command-result', {
          detail: {
            requestId: detail.requestId,
            status: 'ok',
            result: 'Search completed.'
          }
        })
      );
    });

    expect(
      screen.getByText(/Search completed/i, { selector: 'span, p, div' })
    ).toBeInTheDocument();
  });

  it('marks panel complete and emits completion event', () => {
    const payload = encodePayload({
      panel: {
        panel_id: 'panel-complete',
        title: 'Approve run',
        actions: [],
        completion: {
          label: 'Mark complete'
        }
      }
    });
    const completionSpy = jest.fn();
    window.addEventListener('jai:action-panel-complete', event =>
      completionSpy((event as CustomEvent).detail)
    );

    render(<JaiActionPanel payload={payload} />);

    const completeButton = screen.getByRole('button', {
      name: 'Mark complete'
    });
    fireEvent.click(completeButton);
    expect(completionSpy).toHaveBeenCalledWith({ panelId: 'panel-complete' });
    const doneButton = screen.getByRole('button', { name: '완료됨' });
    fireEvent.click(doneButton);
    expect(completionSpy).toHaveBeenCalledTimes(1);
  });
});
