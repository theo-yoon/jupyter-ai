import React, { useCallback, useEffect, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
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

  const [expanded, setExpanded] = useState<string | false>(false);

  useEffect(() => {
    if (!nodes.length) {
      setExpanded(false);
      return;
    }
    const latest = nodes[nodes.length - 1]?.node_id;
    setExpanded(latest ?? false);
  }, [nodes]);

  const handleToggle = useCallback(
    (nodeId: string) => (_event: React.SyntheticEvent, isExpanded: boolean) => {
      setExpanded(isExpanded ? nodeId : false);
    },
    []
  );

  return (
    <Stack spacing={1.5}>
      {nodes.map((node, index) => {
        const meta = describeWorkStatus(node.status);
        const timestamp = formatTimestamp(node.created_at);
        const metadataEntries = node.metadata ? Object.entries(node.metadata) : [];
        const expandIcon = (
          <Box
            component="span"
            sx={{
              transform: expanded === node.node_id ? 'rotate(180deg)' : 'none',
              transition: 'transform 0.2s ease',
              fontSize: 12,
              color: 'var(--jp-ui-font-color2)'
            }}
          >
            ▼
          </Box>
        );
        return (
          <Accordion
            key={node.node_id}
            expanded={expanded === node.node_id}
            onChange={handleToggle(node.node_id)}
            disableGutters
            elevation={0}
            sx={{
              border: '1px solid var(--jp-border-color2)',
              borderRadius: 1,
              backgroundColor: 'var(--jp-layout-color1)',
              '&:before': { display: 'none' }
            }}
          >
            <AccordionSummary
              expandIcon={expandIcon}
              sx={{
                px: 1.5,
                py: 1,
                '& .MuiAccordionSummary-content': {
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.75
                }
              }}
            >
              <Typography component="span" sx={{ fontSize: 18 }}>
                {iconForNodeType(node.node_type)}
              </Typography>
              <Typography
                variant="subtitle2"
                sx={{
                  fontWeight: 600,
                  flex: 1,
                  minWidth: 0,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                }}
              >
                {node.title || `Work item #${index + 1}`}
              </Typography>
              <Chip
                label={meta.label}
                size="small"
                sx={{
                  backgroundColor: meta.color,
                  color: '#fff',
                  fontWeight: 500
                }}
              />
              {timestamp && (
                <Typography
                  variant="caption"
                  sx={{ color: 'var(--jp-ui-font-color2)', ml: 0.75 }}
                >
                  {timestamp}
                </Typography>
              )}
            </AccordionSummary>
            <AccordionDetails
              sx={{
                display: 'flex',
                flexDirection: 'column',
                gap: 1,
                px: 1.5,
                pb: 1.5
              }}
            >
              {node.body && (
                <Typography
                  variant="body2"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    color: 'var(--jp-ui-font-color1)'
                  }}
                >
                  {node.body}
                </Typography>
              )}
              <Divider />
              <Stack
                direction="row"
                spacing={1}
                sx={{ color: 'var(--jp-ui-font-color2)', flexWrap: 'wrap' }}
              >
                {node.step_id && (
                  <Typography variant="caption">Step: {node.step_id}</Typography>
                )}
              </Stack>
              {metadataEntries.length > 0 && (
                <Box
                  sx={{
                    border: '1px solid var(--jp-border-color2)',
                    borderRadius: 1,
                    p: 1,
                    backgroundColor: 'var(--jp-layout-color0)'
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{
                      display: 'block',
                      color: 'var(--jp-ui-font-color2)',
                      mb: 0.5,
                      textTransform: 'uppercase',
                      letterSpacing: 0.5
                    }}
                  >
                    Metadata
                  </Typography>
                  <Stack spacing={0.5}>
                    {metadataEntries.map(([key, value]) => {
                      const rendered =
                        typeof value === 'string'
                          ? value
                          : JSON.stringify(value, null, 2);
                      return (
                        <Typography
                          key={key}
                          variant="caption"
                          sx={{ color: 'var(--jp-ui-font-color1)' }}
                        >
                          <strong>{key}:</strong> {rendered}
                        </Typography>
                      );
                    })}
                  </Stack>
                </Box>
              )}
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Stack>
  );
}
