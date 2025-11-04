import React, { useEffect } from 'react';
import { Box, Collapse, Typography } from '@mui/material';

import type { WorkNode } from '../types';
import { WorkNodeList } from './WorkNodeList/WorkNodeList';
import { buildUIStateKey, usePersistentUIState } from '../uiState';

type WorkItemsSectionProps = {
  nodes: WorkNode[];
  defaultExpanded?: boolean;
  title: string;
  completed?: boolean;
  virtualNode?: WorkNode | null;
  stateNamespace?: string;
};

export function WorkItemsSection({
  nodes,
  defaultExpanded = true,
  title,
  completed = false,
  virtualNode = null,
  stateNamespace
}: WorkItemsSectionProps): JSX.Element {
  const storageKey = stateNamespace
    ? buildUIStateKey(stateNamespace, 'work-items', 'expanded')
    : undefined;
  const [expanded, setExpanded, { hasStoredValue }] = usePersistentUIState<boolean>(
    storageKey ?? null,
    defaultExpanded
  );

  useEffect(() => {
    if (!hasStoredValue) {
      setExpanded(defaultExpanded);
    }
  }, [defaultExpanded, hasStoredValue, setExpanded]);

  useEffect(() => {
    if (completed) {
      setExpanded(false);
    }
  }, [completed, setExpanded]);

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
        <WorkNodeList
          nodes={nodes}
          virtualNode={virtualNode}
          stateNamespace={stateNamespace}
        />
      </Collapse>
    </Box>
  );
}
