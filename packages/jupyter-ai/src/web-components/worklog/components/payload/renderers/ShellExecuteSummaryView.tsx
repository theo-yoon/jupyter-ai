import React from 'react';
import TerminalOutlinedIcon from '@mui/icons-material/TerminalOutlined';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { Box, Stack, Typography } from '@mui/material';

import {
  ACCENT_ERROR,
  ACCENT_INFO,
  PayloadCard,
  SummaryList,
  TEXT_SECONDARY,
  TextBlock
} from '../common';
import {
  registerSummaryContent,
  registerToolSummaryBuilder
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type ShellExecuteSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
  sectionGroup?: string;
};

export const ShellExecuteSummaryView: React.FC<
  ShellExecuteSummaryViewProps
> = ({ data, sectionKey, sectionGroup }) => {
  const baseData = data;
  const succeeded = baseData.succeeded as boolean | undefined;
  const exitCode = baseData.exit_code as number | null | undefined;
  const stdout = (baseData.stdout as string | undefined) ?? '';
  const stderr = (baseData.stderr as string | undefined) ?? '';
  const command = baseData.command as string | undefined;
  const cwd = baseData.cwd as string | undefined;

  const rows = [
    { label: 'Command', value: command ? <code>{command}</code> : undefined },
    { label: 'Working directory', value: cwd },
    {
      label: 'Exit code',
      value:
        exitCode === null || exitCode === undefined
          ? 'n/a'
          : exitCode.toString()
    }
  ];

  const status =
    succeeded === false ? 'error' : succeeded ? 'success' : 'warning';
  const exitBadge =
    exitCode !== undefined && exitCode !== null
      ? `exit ${exitCode}`
      : succeeded === false
      ? 'failed'
      : succeeded
      ? 'done'
      : undefined;

  const icon =
    status === 'error'
      ? React.createElement(WarningAmberIcon, {
          fontSize: 'small',
          sx: { color: ACCENT_ERROR }
        })
      : React.createElement(TerminalOutlinedIcon, {
          fontSize: 'small',
          sx: { color: ACCENT_INFO }
        });

  const terminalBlocks: Array<{
    label: string;
    content: string;
    highlight: boolean;
  }> = [];
  if (command || stdout) {
    terminalBlocks.push({
      label: 'stdout',
      content: stdout ? String(stdout) : '',
      highlight: true
    });
  }
  if (stderr) {
    terminalBlocks.push({
      label: 'stderr',
      content: String(stderr),
      highlight: false
    });
  }

  return (
    <PayloadCard
      title={command ? `$ ${command}` : 'Shell command'}
      subtitle={cwd ? `cwd: ${cwd}` : undefined}
      icon={icon}
      status={status}
      badgeLabel={exitBadge}
      collapsible={terminalBlocks.length > 0}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={1}>
        <SummaryList rows={rows} />
        {terminalBlocks.length > 0 ? (
          <Stack spacing={0.75}>
            {terminalBlocks.map(block => (
              <Box key={block.label}>
                <Typography
                  variant="caption"
                  sx={{
                    color: TEXT_SECONDARY,
                    fontWeight: 500,
                    letterSpacing: 0.3,
                    textTransform: 'uppercase'
                  }}
                >
                  {block.label}
                </Typography>
                <TextBlock
                  text={block.content || '(empty)'}
                  format="ansi"
                  maxHeight={200}
                />
              </Box>
            ))}
          </Stack>
        ) : (
          <Typography
            variant="body2"
            sx={{ color: TEXT_SECONDARY }}
          >
            출력이 없어요.
          </Typography>
        )}
      </Stack>
    </PayloadCard>
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
