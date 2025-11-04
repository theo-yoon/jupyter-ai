import React from 'react';
import { Box, Divider, Stack } from '@mui/material';

type DetailPanelProps = {
  items: React.ReactNode[];
};

export const DetailPanel: React.FC<DetailPanelProps> = ({ items }) =>
  items.length ? (
    <Box
      sx={{
        mt: 0.5,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.55
      }}
    >
      {items.map((item, index) => (
        <Stack key={`detail-${index}`} spacing={0.55}>
          {item}
          {index < items.length - 1 && (
            <Divider sx={{ borderColor: 'rgba(0,0,0,0.08)' }} />
          )}
        </Stack>
      ))}
    </Box>
  ) : null;
