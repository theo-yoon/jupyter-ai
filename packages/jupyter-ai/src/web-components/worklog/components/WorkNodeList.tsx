import React from 'react';
import {
  Box,
  Chip,
  Divider,
  Stack,
  Typography
} from '@mui/material';

import type { WorkNode } from '../types';
import { describeWorkStatus, iconForNodeType } from '../status';
import { formatTimestamp } from '../format';

type WorkNodeListProps = {
  nodes: WorkNode[];
};

export function WorkNodeList({ nodes }: WorkNodeListProps): JSX.Element {
  if (!nodes.length) {
    return (
      <Box
        sx={{
          border: '1px dashed var(--jp-border-color1)',
          borderRadius: 1,
          p: 1.5,
          color: 'var(--jp-ui-font-color2)'
        }}
      >
        <Typography variant="body2">Waiting for work items…</Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={1.5}>
      {nodes.map((node, index) => {
        const meta = describeWorkStatus(node.status);
        const timestamp = formatTimestamp(node.created_at);
        return (
          <Box
            key={node.node_id}
            sx={{
              border: '1px solid var(--jp-border-color2)',
              borderRadius: 1,
              p: 1.25,
              display: 'flex',
              flexDirection: 'column',
              gap: 0.75,
              backgroundColor: 'var(--jp-layout-color1)'
            }}
          >
            <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center' }}>
              <Typography component="span" sx={{ fontSize: 18 }}>
                {iconForNodeType(node.node_type)}
              </Typography>
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {node.title || `Work item #${index + 1}`}
              </Typography>
              <Chip
                label={meta.label}
                size="small"
                sx={{
                  ml: 'auto',
                  backgroundColor: meta.color,
                  color: '#fff',
                  fontWeight: 500
                }}
              />
            </Box>
            {node.body && (
              <Typography
                variant="body2"
                sx={{ whiteSpace: 'pre-wrap', color: 'var(--jp-ui-font-color1)' }}
              >
                {node.body}
              </Typography>
            )}
            <Divider />
            <Box sx={{ display: 'flex', gap: 1, color: 'var(--jp-ui-font-color2)' }}>
              {node.step_id && (
                <Typography variant="caption">Step: {node.step_id}</Typography>
              )}
              {timestamp && (
                <Typography variant="caption">{timestamp}</Typography>
              )}
            </Box>
          </Box>
        );
      })}
    </Stack>
  );
}
