import React from 'react';
import { Stack, Typography } from '@mui/material';

type MetadataListProps = {
  entries: Array<[string, unknown]>;
  formatter: (value: unknown) => string;
};

export const MetadataList: React.FC<MetadataListProps> = ({
  entries,
  formatter
}) =>
  entries.length ? (
    <Stack spacing={0.25}>
      {entries.map(([key, value]) => (
        <Typography
          key={key}
          variant="caption"
          sx={{
            color: 'var(--jp-ui-font-color2)',
            fontSize: '0.68rem',
            letterSpacing: '0.012em'
          }}
        >
          <strong>{key}:</strong> {formatter(value)}
        </Typography>
      ))}
    </Stack>
  ) : null;
