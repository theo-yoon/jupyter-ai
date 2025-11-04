import React from 'react';
import { Box, Stack, Typography } from '@mui/material';

import { SummaryList } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveMatches = (matches: unknown) =>
  Array.isArray(matches) ? (matches as Array<Record<string, unknown>>) : [];

type SearchGrepSummaryViewProps = {
  data: Record<string, unknown>;
};

export const SearchGrepSummaryView: React.FC<SearchGrepSummaryViewProps> = ({
  data
}) => {
  const matches = resolveMatches(data.matches);
  const matchCount = data.match_count as number | undefined;
  const topMatches = matches.slice(0, 5);

  const rows = [
    { label: 'Pattern', value: data.pattern as string | undefined },
    { label: 'Include', value: data.include as string | undefined },
    { label: 'Match count', value: matchCount?.toString() }
  ];

  const moreCount =
    matches.length > topMatches.length ? matches.length - topMatches.length : 0;

  const moreLabel = moreCount
    ? [
        <Typography
          key="more"
          variant="caption"
          sx={{ color: 'var(--jp-ui-font-color2)' }}
        >
          … {moreCount} more match(es) omitted
        </Typography>
      ]
    : [];

  const matchList = topMatches.length
    ? [
        <Stack
          key="matches"
          spacing={0.25}
          sx={{ fontFamily: 'var(--jp-code-font-family)', fontSize: '0.75rem' }}
        >
          {topMatches.map((match, idx) => {
            const file = (match.file as string | undefined) ?? '';
            const line = match.line as number | string | undefined;
            const preview = (match.preview as string | undefined) ?? '';
            return (
              <Box key={`${file}:${line ?? idx}`}>{`${file}:${
                line ?? '?'
              } — ${preview}`}</Box>
            );
          })}
          {moreLabel}
        </Stack>
      ]
    : [];

  return (
    <Stack spacing={0.5}>
      <SummaryList rows={rows} />
      {matchList}
    </Stack>
  );
};

registerSummaryContent('search.grep', 'summary:search.grep');
registerPayloadRenderer('summary:search.grep', SearchGrepSummaryView);
