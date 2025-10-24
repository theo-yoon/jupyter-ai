import React, { useMemo, useState } from 'react';
import { Box, Button, Collapse, Typography } from '@mui/material';

type JaiAgentReplyProps = {
  message?: string;
  title?: string;
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

export function JaiAgentReply(props: JaiAgentReplyProps): JSX.Element | null {
  const rawMessage = props.message ?? '';
  const trimmedMessage = rawMessage.trim();
  const [expanded, setExpanded] = useState(false);

  const snippet = useMemo(() => summarize(trimmedMessage), [trimmedMessage]);

  if (!trimmedMessage) {
    return null;
  }

  const title = props.title?.trim() || 'Agent reply';

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
        gap: 0.5
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="caption" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
        <Button
          size="small"
          variant="text"
          sx={{ fontSize: '0.7rem', textTransform: 'none', p: 0, minWidth: 'auto' }}
          onClick={() => setExpanded(prev => !prev)}
        >
          {expanded ? 'Hide message' : 'Show message'}
        </Button>
      </Box>

      {snippet ? (
        <Typography variant="caption" color="text.secondary">
          {snippet}
        </Typography>
      ) : null}

      <Collapse in={expanded} timeout="auto" unmountOnExit>
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
  );
}
