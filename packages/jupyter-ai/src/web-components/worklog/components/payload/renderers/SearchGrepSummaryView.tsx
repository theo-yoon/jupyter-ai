import React from 'react';
import SearchIcon from '@mui/icons-material/Search';
import { Box, Stack, Typography } from '@mui/material';

import {
  ACCENT_INFO,
  BLOCK_BACKGROUND,
  PayloadCard,
  SummaryList,
  SURFACE_BORDER,
  TEXT_MUTED,
  TEXT_SECONDARY,
  TextBlock,
  coerceRecord
} from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveMatches = (matches: unknown) =>
  Array.isArray(matches) ? (matches as Array<Record<string, unknown>>) : [];

type SearchGrepSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
  sectionGroup?: string;
};

export const SearchGrepSummaryView: React.FC<SearchGrepSummaryViewProps> = ({
  data,
  sectionKey,
  sectionGroup
}) => {
  const baseData = coerceRecord(data) ?? data;
  const matches = resolveMatches(baseData.matches);
  const matchCount = baseData.match_count as number | undefined;
  const topMatches = matches.slice(0, 5);

  const rows = [
    { label: 'Pattern', value: baseData.pattern as string | undefined },
    { label: 'Include', value: baseData.include as string | undefined },
    { label: 'Match count', value: matchCount?.toString() }
  ];

  const moreCount =
    matches.length > topMatches.length ? matches.length - topMatches.length : 0;

  const moreLabel = moreCount
    ? [
        <Typography key="more" variant="caption" sx={{ color: TEXT_MUTED }}>
          … {moreCount} more match(es) omitted
        </Typography>
      ]
    : [];

  const matchList = topMatches.length ? (
    <Stack spacing={0.5}>
      {topMatches.map((match, idx) => {
        const file = (match.file as string | undefined) ?? '';
        const line = match.line as number | string | undefined;
        const preview = (match.preview as string | undefined) ?? '';
        return (
          <Box
            key={`${file}:${line ?? idx}`}
            sx={{
              border: `1px solid ${SURFACE_BORDER}`,
              borderRadius: 1,
              px: 1,
              py: 0.75,
              backgroundColor: BLOCK_BACKGROUND
            }}
          >
            <Typography
              variant="caption"
              sx={{
                color: TEXT_MUTED,
                display: 'block',
                marginBottom: 0.25
              }}
            >
              {file}:{line ?? '?'}
            </Typography>
            <TextBlock text={preview} format="ansi" maxHeight={110} />
          </Box>
        );
      })}
      {moreLabel}
    </Stack>
  ) : null;

  return (
    <PayloadCard
      title="Search results"
      subtitle={
        matchCount !== undefined ? `${matchCount} matches found` : undefined
      }
      icon={<SearchIcon fontSize="small" sx={{ color: ACCENT_INFO }} />}
      badgeLabel={topMatches.length ? `${topMatches.length} shown` : undefined}
      collapsible={Boolean(matchList)}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={0.75}>
        <SummaryList rows={rows} />
        {matchList ?? (
          <Typography variant="body2" sx={{ color: TEXT_SECONDARY }}>
            일치하는 결과가 없습니다.
          </Typography>
        )}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('search.grep', 'summary:search.grep');
registerPayloadRenderer('summary:search.grep', SearchGrepSummaryView);
