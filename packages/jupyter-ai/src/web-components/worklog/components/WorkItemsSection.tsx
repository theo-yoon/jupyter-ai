import React, { useState } from 'react';
import { Box, Collapse, Typography } from '@mui/material';

import type { WorkNode } from '../types';
import { WorkNodeList } from './WorkNodeList';

type WorkItemsSectionProps = {
  nodes: WorkNode[];
  defaultExpanded?: boolean;
};

export function WorkItemsSection({
  nodes,
  defaultExpanded = true
}: WorkItemsSectionProps): JSX.Element {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <Box
      sx={{
        flex: 1,
        minHeight: 0,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        gap: 2
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          mb: expanded ? 1 : 0
        }}
        onClick={() => setExpanded(prev => !prev)}
      >
        <Typography variant="overline" sx={{ letterSpacing: 1 }}>
          Work items
        </Typography>
        <Typography
          variant="caption"
          sx={{ color: 'var(--jp-ui-font-color2)' }}
        >
          {expanded ? 'Hide' : 'Show'} • {nodes.length}
        </Typography>
      </Box>
      <Collapse in={expanded} timeout="auto">
        <WorkNodeList nodes={nodes} />
      </Collapse>
    </Box>
  );
}
