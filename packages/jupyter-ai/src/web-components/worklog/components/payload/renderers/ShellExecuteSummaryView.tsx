import React from 'react';
import { Box, Chip, Stack, Typography } from '@mui/material';

import {
  registerSummaryContent,
  registerToolSummaryBuilder
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const TerminalBlock: React.FC<{
  label: string;
  content: string;
  highlight?: boolean;
}> = ({ label, content, highlight = false }) => (
  <Box
    sx={{
      borderRadius: 1,
      overflow: 'hidden',
      border: '1px solid var(--jp-border-color2)',
      backgroundColor: highlight
        ? 'rgba(0, 0, 0, 0.6)'
        : 'var(--jp-layout-color1)',
      fontFamily: 'var(--jp-code-font-family)',
      fontSize: '0.78rem'
    }}
  >
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 1,
        py: 0.5,
        borderBottom: '1px solid var(--jp-border-color2)',
        backgroundColor: highlight
          ? 'rgba(255, 255, 255, 0.08)'
          : 'var(--jp-layout-color0)',
        fontSize: '0.7rem',
        textTransform: 'uppercase',
        letterSpacing: 0.5,
        color: highlight ? '#c5d7ff' : 'var(--jp-ui-font-color2)'
      }}
    >
      <Box
        component="span"
        sx={{ display: 'inline-flex', gap: 0.5, opacity: 0.4 }}
      >
        <Box
          component="span"
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: '#ff5f56'
          }}
        />
        <Box
          component="span"
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: '#ffbd2e'
          }}
        />
        <Box
          component="span"
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: '#27c93f'
          }}
        />
      </Box>
      {label}
    </Box>
    <Box
      component="pre"
      sx={{
        m: 0,
        px: 1,
        py: 0.75,
        whiteSpace: 'pre-wrap',
        overflowX: 'auto',
        color: highlight ? '#eaf1ff' : 'inherit'
      }}
    >
      {content || '(empty)'}
    </Box>
  </Box>
);

type ShellExecuteSummaryViewProps = {
  data: Record<string, unknown>;
};

export const ShellExecuteSummaryView: React.FC<
  ShellExecuteSummaryViewProps
> = ({ data }) => {
  const baseData = data;
  const succeeded = baseData.succeeded as boolean | undefined;
  const exitCode = baseData.exit_code as number | null | undefined;
  const stdout = (baseData.stdout as string | undefined) ?? '';
  const stderr = (baseData.stderr as string | undefined) ?? '';
  const command = baseData.command as string | undefined;
  const cwd = baseData.cwd as string | undefined;

  const rows = [
    { label: 'Command', value: command },
    { label: 'Working directory', value: cwd },
    {
      label: 'Exit code',
      value:
        exitCode === null || exitCode === undefined
          ? 'n/a'
          : exitCode.toString()
    }
  ];

  const badge = (
    <Chip
      size="small"
      color={succeeded ? 'success' : 'error'}
      variant="outlined"
      label={succeeded ? 'Succeeded' : 'Failed'}
      sx={{ height: 18, fontSize: '0.65rem' }}
    />
  );

  const terminalBlocks = [
    command ? (
      <TerminalBlock
        key="command"
        label={cwd ? `${cwd}` : 'shell'}
        content={stdout ? `$ ${command}\n${stdout}` : `$ ${command}`}
        highlight
      />
    ) : null,
    !command && stdout ? (
      <TerminalBlock key="stdout" label="stdout" content={stdout} />
    ) : null,
    stderr ? (
      <TerminalBlock key="stderr" label="stderr" content={stderr} />
    ) : null
  ].filter(Boolean);

  return (
    <Stack spacing={0.5}>
      <Stack spacing={0.5}>
        {rows
          .filter(row => row.value)
          .map(row => (
            <Typography
              key={row.label}
              variant="body2"
              sx={{ fontSize: '0.75rem', color: 'var(--jp-ui-font-color1)' }}
            >
              <strong>{row.label}:</strong> {row.value}
            </Typography>
          ))}
      </Stack>
      <Box sx={{ display: 'flex', gap: 0.5 }}>{badge}</Box>
      {terminalBlocks}
    </Stack>
  );
};

registerSummaryContent('shell.execute', 'summary:shell.execute');
registerSummaryContent('shell.command', 'summary:shell.command');
registerPayloadRenderer('summary:shell.execute', ShellExecuteSummaryView);
registerPayloadRenderer('summary:shell.command', ShellExecuteSummaryView);
registerToolSummaryBuilder('bash', data => [
  {
    key: 'summary:shell.command',
    props: { data }
  }
]);
