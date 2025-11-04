import React from 'react';
import { Box, Chip } from '@mui/material';

type TagListProps = {
  tags: Array<string | number | boolean>;
};

export const TagList: React.FC<TagListProps> = ({ tags }) => (
  <Box
    component="span"
    sx={{ display: 'inline-flex', gap: 0.5, flexWrap: 'wrap' }}
  >
    {tags.map(tag => (
      <Chip
        key={String(tag)}
        label={String(tag)}
        size="small"
        sx={{ height: 18, fontSize: '0.65rem' }}
      />
    ))}
  </Box>
);
