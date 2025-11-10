import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { JaiToolCall } from '../jai-tool-call';

const payloadViewMock = jest.fn(({ adapted }: { adapted: unknown }) => (
  <div data-testid="payload-view">{JSON.stringify(adapted)}</div>
));

jest.mock('../worklog/components/payload', () => ({
  WorkNodePayloadView: (props: any) => payloadViewMock(props)
}));
jest.mock('../worklog/components/payload/adapters', () => ({
  adaptWorkNodePayload: (payload: any) => ({
    sections: payload ? [{ title: payload.kind ?? 'payload' }] : [],
    fallbackText: payload?.kind ?? null
  })
}));

describe('JaiToolCall', () => {
  beforeEach(() => {
    payloadViewMock.mockClear();
  });

  it('returns null when required identifiers are missing', () => {
    const { container } = render(
      <JaiToolCall type="function" function_name="demo" />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders running state before output is available', () => {
    render(
      <JaiToolCall
        id="call-1"
        type="function"
        function_name="demo"
        function_args='{"arg": 1}'
      />
    );
    expect(screen.getByText(/Running/i)).toBeInTheDocument();
  });

  it('displays completed state and allows expanding details', () => {
    const output = JSON.stringify({
      tool_call_id: 'call-2',
      role: 'tool',
      name: 'demo',
      content: '{"result": "ok"}'
    });
    render(
      <JaiToolCall
        id="call-2"
        type="function"
        function_name="demo"
        function_args='{"arg": 1}'
        output={output}
      />
    );
    expect(screen.getByText(/Ran/i)).toBeInTheDocument();
    const expandButton = screen.getByRole('button');
    expect(expandButton).not.toBeDisabled();
    fireEvent.click(expandButton);
    expect(payloadViewMock).toHaveBeenCalled();
  });
});
