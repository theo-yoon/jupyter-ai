import React, { useCallback, useEffect, useState } from 'react';
import { Box, Button, Collapse } from '@mui/material';

import { JsonBlock } from './JsonBlock';

type JsonInspectorProps = {
  data: unknown;
  label?: React.ReactNode;
  buttonLabel?: string;
  defaultExpanded?: boolean;
  stateKey?: string;
  stateGroup?: string;
};

export const JsonInspector: React.FC<JsonInspectorProps> = ({
  data,
  label = 'Raw response',
  buttonLabel,
  defaultExpanded = false,
  stateKey,
  stateGroup
}) => {
  const [expanded, setExpanded] = useState<boolean>(() => {
    if (stateKey && inspectorStateStore.has(stateKey)) {
      return inspectorStateStore.get(stateKey) as boolean;
    }
    return defaultExpanded;
  });
  const toggle = useCallback(() => setExpanded(prev => !prev), []);

  const labelForButton =
    buttonLabel ??
    (typeof label === 'string' ? label.toLowerCase() : 'details');
  const isStringLabel = typeof label === 'string';

  useEffect(() => {
    if (stateKey && inspectorStateStore.has(stateKey)) {
      const stored = inspectorStateStore.get(stateKey) as boolean;
      if (expanded !== stored) {
        setExpanded(stored);
      }
      return;
    }
    if (stateGroup) {
      const groupEntry = inspectorGroupStore.get(stateGroup);
      if (groupEntry && expanded !== groupEntry.expanded) {
        setExpanded(groupEntry.expanded);
        return;
      }
    }
    if (!stateKey && !stateGroup && expanded !== defaultExpanded) {
      setExpanded(defaultExpanded);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultExpanded, stateKey, stateGroup]);

  useEffect(() => {
    if (stateKey) {
      inspectorStateStore.set(stateKey, expanded);
    }
    if (stateGroup) {
      inspectorGroupStore.set(stateGroup, {
        key: stateKey ?? stateGroup,
        expanded
      });
    }
  }, [expanded, stateKey, stateGroup]);

  return (
    <Box sx={{ mt: 0.5 }}>
      <Button
        size="small"
        onClick={toggle}
        sx={{
          textTransform: 'none',
          px: 0,
          minWidth: 0,
          fontSize: '0.72rem',
          color: '#247BA0',
          '&:hover': { backgroundColor: 'rgba(36, 123, 160, 0.08)' }
        }}
      >
        {expanded ? `Hide ${labelForButton}` : `Show ${labelForButton}`}
      </Button>
      <Collapse in={expanded} timeout="auto" unmountOnExit>
        <Box sx={{ mt: 0.5 }}>
          {label ? (
            <Box
              sx={{
                mb: 0.5,
                ...(isStringLabel
                  ? {
                      fontSize: '0.75rem',
                      color: 'rgba(27, 37, 54, 0.6)',
                      letterSpacing: 0.25
                    }
                  : {
                      color: 'rgba(27, 37, 54, 0.72)',
                      fontSize: '0.78rem',
                      fontWeight: 500
                    })
              }}
            >
              {label}
            </Box>
          ) : null}
          <JsonBlock value={data} />
        </Box>
      </Collapse>
    </Box>
  );
};

const inspectorStateStore = new Map<string, boolean>();
const inspectorGroupStore = new Map<
  string,
  { key: string; expanded: boolean }
>();
