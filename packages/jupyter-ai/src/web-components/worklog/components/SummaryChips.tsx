import React from 'react';
import ArticleIcon from '@mui/icons-material/Article';
import { Chip, Stack } from '@mui/material';

import type { WorklogEntry } from '../../worklog-store';

export function SummaryChips({ entry }: { entry: WorklogEntry }) {
  const summary = entry.change_summary;
  if (!summary) {
    return null;
  }

  const chips: React.ReactElement[] = [
    <Chip
      key="files"
      size="small"
      variant="outlined"
      icon={<ArticleIcon fontSize="small" />}
      label={`${summary.files_changed} files`}
      sx={{ fontWeight: 400 }}
    />,
    <Chip
      key="lines_added"
      size="small"
      variant="outlined"
      color="success"
      label={`+${summary.lines_added} lines`}
      sx={{ fontWeight: 400 }}
    />,
    <Chip
      key="lines_deleted"
      size="small"
      variant="outlined"
      color="error"
      label={`-${summary.lines_deleted} lines`}
      sx={{ fontWeight: 400 }}
    />
  ];

  summary.actions?.forEach(action => {
    chips.push(
      <Chip
        key={`action-${action}`}
        size="small"
        color="primary"
        label={action}
        variant="outlined"
        sx={{ fontWeight: 400 }}
      />
    );
  });

  return (
    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
      {chips}
    </Stack>
  );
}
