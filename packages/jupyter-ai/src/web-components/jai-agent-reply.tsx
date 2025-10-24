import React, { useMemo, useState } from 'react';
import { Box, Button, Collapse, Typography } from '@mui/material';

type JaiAgentReplyProps = {
  message?: string;
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

export function JaiAgentReply(props: JaiAgentReplyProps): JSX.Element | null {
  const rawMessage = props.message ?? '';
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

  const snippet = useMemo(() => summarize(trimmedMessage), [trimmedMessage]);

  const hasReply = Boolean(trimmedMessage);
  const hasTools = hasVisibleContent(decodedToolsMarkup);
  const hasWork = hasVisibleContent(decodedWorkMarkup);

  if (!hasReply && !hasTools && !hasWork) {
    return null;
  }

  const title = props.title?.trim() || 'Agent reply';
  const toolsHeading = props.tools_heading?.trim() || 'Ran tools';
  const workHeading = props.work_heading?.trim() || 'Working';

  return (
    <Box
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
          <Collapse in={toolsOpen} timeout="auto" unmountOnExit>
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
          <Collapse in={workOpen} timeout="auto" unmountOnExit>
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
        </Box>
      ) : null}
    </Box>
  );
}
