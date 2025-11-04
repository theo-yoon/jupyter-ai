import React, { useEffect, useState } from 'react';
import { Box, Collapse, Typography } from '@mui/material';

import type { WorkNode } from '../types';
import { WorkNodeList } from './WorkNodeList/WorkNodeList';

type WorkItemsSectionProps = {
  nodes: WorkNode[];
  defaultExpanded?: boolean;
  title: string;
  completed?: boolean;
  virtualNode?: WorkNode | null;
};

export function WorkItemsSection({
  nodes,
  defaultExpanded = true,
  title,
  completed = false,
  virtualNode = null
}: WorkItemsSectionProps): JSX.Element {
  const [expanded, setExpanded] = useState(defaultExpanded);

  useEffect(() => {
    setExpanded(defaultExpanded);
  }, [defaultExpanded]);

  useEffect(() => {
    if (completed) {
      setExpanded(false);
    }
  }, [completed]);

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
          {title}
        </Typography>
      </Box>
      <Collapse in={expanded} timeout="auto">
        <WorkNodeList nodes={nodes} virtualNode={virtualNode} />
      </Collapse>
    </Box>
  );
}
