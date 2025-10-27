import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Box, Button, Collapse, Typography } from '@mui/material';

type JaiAgentReplyProps = {
  message?: string;
  message_b64?: string;
  title?: string;
  tools_markup?: string;
  work_markup?: string;
  tools_heading?: string;
  work_heading?: string;
};

function summarize(message: string): string {
  const trimmed = message.trim();
  if (!trimmed) {
    return '';
  }
  const firstLine = trimmed.split(/\r?\n/)[0] ?? '';
  if (firstLine.length <= 160) {
    return firstLine;
  }
  return `${firstLine.slice(0, 157)}…`;
}

function decodeMarkup(raw?: string): string {
  if (!raw) {
    return '';
  }
  const textarea = document.createElement('textarea');
  textarea.innerHTML = raw;
  return textarea.value;
}

function hasVisibleContent(markup: string): boolean {
  return markup.replace(/<[^>]+>/g, '').trim().length > 0 || markup.includes('<');
}

function decodeMessageFromBase64(value?: string): string | null {
  if (!value) {
    return null;
  }
  try {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    const decoder = new TextDecoder('utf-8', { fatal: false });
    return decoder.decode(bytes);
  } catch (error) {
    console.warn('Failed to decode jai-agent-reply message_b64 attribute.', error);
    return null;
  }
}

export function JaiAgentReply(props: JaiAgentReplyProps): JSX.Element | null {
  const decodedMessage = useMemo(
    () => decodeMessageFromBase64(props.message_b64),
    [props.message_b64]
  );
  const rawMessage = props.message ?? decodedMessage ?? '';
  const trimmedMessage = rawMessage.trim();

  const decodedToolsMarkup = useMemo(
    () => decodeMarkup(props.tools_markup),
    [props.tools_markup]
  );
  const decodedWorkMarkup = useMemo(
    () => decodeMarkup(props.work_markup),
    [props.work_markup]
  );

  const [replyOpen, setReplyOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [workOpen, setWorkOpen] = useState(false);
  const [widgetsReady, setWidgetsReady] = useState(false);

  const snippet = useMemo(() => summarize(trimmedMessage), [trimmedMessage]);

  const hasReply = Boolean(trimmedMessage);
  const hasTools = hasVisibleContent(decodedToolsMarkup);
  const hasWork = hasVisibleContent(decodedWorkMarkup);
  const containerRef = useRef<HTMLDivElement | null>(null);

  if (!hasReply && !hasTools && !hasWork) {
    return null;
  }

  const title = props.title?.trim() || 'Agent reply';
  const toolsHeading = props.tools_heading?.trim() || 'Ran tools';
  const workHeading = props.work_heading?.trim() || 'Working';

  useEffect(() => {
    const root = containerRef.current?.parentElement;
    if (!root) {
      return;
    }
    const fallbackNodes = root.querySelectorAll('[data-jai-agent-fallback="true"]');
    fallbackNodes.forEach(node => {
      if (node instanceof HTMLElement) {
        node.remove();
      }
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    const trackDefinitions = async (): Promise<void> => {
      const names = ['jai-tool-call', 'jai-plan-worklog'];
      try {
        await Promise.all(
          names.map(name =>
            customElements.get(name)
              ? Promise.resolve()
              : customElements.whenDefined(name)
          )
        );
        if (!cancelled) {
          setWidgetsReady(true);
        }
      } catch (error) {
        console.warn('Failed waiting for custom elements to register', error);
        if (!cancelled) {
          setWidgetsReady(true);
        }
      }
    };
    void trackDefinitions();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Box
      ref={containerRef}
      sx={{
        border: '1px solid var(--jp-border-color2, #d4d4d4)',
        borderRadius: 1.25,
        backgroundColor: 'var(--jp-layout-color2, #fff)',
        p: 1,
        mb: 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75
      }}
    >
      {hasReply ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="caption" sx={{ fontWeight: 600 }}>
              {title}
            </Typography>
            <Button
              size="small"
              variant="text"
              sx={{ fontSize: '0.7rem', textTransform: 'none', p: 0, minWidth: 'auto', ml: 'auto' }}
              onClick={() => setReplyOpen(prev => !prev)}
            >
              {replyOpen ? 'Hide message' : 'Show message'}
            </Button>
          </Box>
          {snippet ? (
            <Typography variant="caption" color="text.secondary">
              {snippet}
            </Typography>
          ) : null}
          <Collapse in={replyOpen} timeout="auto" unmountOnExit>
            <Box
              component="pre"
              sx={{
                m: 0,
                mt: 0.5,
                p: 0.75,
                backgroundColor: 'var(--jp-layout-color1, #f9f9f9)',
                borderRadius: 1,
                whiteSpace: 'pre-wrap',
                fontSize: '0.8rem',
                border: '1px solid var(--jp-border-color2, rgba(0,0,0,0.08))'
              }}
            >
              {trimmedMessage}
            </Box>
          </Collapse>
        </Box>
      ) : null}

      {hasTools ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="caption" sx={{ fontWeight: 600 }}>
              {toolsHeading}
            </Typography>
            <Button
              size="small"
              variant="text"
              sx={{ fontSize: '0.7rem', textTransform: 'none', p: 0, minWidth: 'auto', ml: 'auto' }}
              onClick={() => setToolsOpen(prev => !prev)}
            >
              {toolsOpen ? 'Hide details' : 'View details'}
            </Button>
          </Box>
          <Collapse in={toolsOpen && widgetsReady} timeout="auto" unmountOnExit>
            <Box
              sx={{
                mt: 0.5,
                p: 0.5,
                borderRadius: 1,
                border: '1px solid var(--jp-border-color2, rgba(0,0,0,0.08))',
                backgroundColor: 'var(--jp-layout-color1, #f9f9f9)'
              }}
              dangerouslySetInnerHTML={{ __html: decodedToolsMarkup }}
            />
          </Collapse>
          {!widgetsReady && toolsOpen ? (
            <Typography variant="caption" color="text.secondary">
              Loading tool details…
            </Typography>
          ) : null}
        </Box>
      ) : null}

      {hasWork ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="caption" sx={{ fontWeight: 600 }}>
              {workHeading}
            </Typography>
            <Button
              size="small"
              variant="text"
              sx={{ fontSize: '0.7rem', textTransform: 'none', p: 0, minWidth: 'auto', ml: 'auto' }}
              onClick={() => setWorkOpen(prev => !prev)}
            >
              {workOpen ? 'Hide details' : 'View details'}
            </Button>
          </Box>
          <Collapse in={workOpen && widgetsReady} timeout="auto" unmountOnExit>
            <Box
              sx={{
                mt: 0.5,
                p: 0.5,
                borderRadius: 1,
                border: '1px solid var(--jp-border-color2, rgba(0,0,0,0.08))',
                backgroundColor: 'var(--jp-layout-color1, #f9f9f9)'
              }}
              dangerouslySetInnerHTML={{ __html: decodedWorkMarkup }}
            />
          </Collapse>
          {!widgetsReady && workOpen ? (
            <Typography variant="caption" color="text.secondary">
              Loading working details…
            </Typography>
          ) : null}
        </Box>
      ) : null}
    </Box>
  );
}
