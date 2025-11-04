import React from 'react';
import { Box, Typography } from '@mui/material';

export const EmptyState: React.FC = () => (
  <Box
    sx={{
      border: '1px dashed var(--jp-border-color1)',
      borderRadius: 1,
      p: 1.5,
      color: 'var(--jp-ui-font-color2)'
    }}
  >
    <Typography variant="body2">No work items yet.</Typography>
  </Box>
);
