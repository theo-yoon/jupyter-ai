import React from 'react';
import { Box, Button, Collapse } from '@mui/material';

import { JsonBlock } from './JsonBlock';

type JsonInspectorProps = {
  data: unknown;
  label?: React.ReactNode;
  buttonLabel?: string;
  defaultExpanded?: boolean;
};

export const JsonInspector: React.FC<JsonInspectorProps> = ({
  data,
  label = 'Raw response',
  buttonLabel,
  defaultExpanded = false
}) => {
  const [expanded, setExpanded] = React.useState(defaultExpanded);
  const toggle = React.useCallback(() => setExpanded(prev => !prev), []);

  const labelForButton =
    buttonLabel ??
    (typeof label === 'string' ? label.toLowerCase() : 'details');
  const isStringLabel = typeof label === 'string';

  return (
    <Box sx={{ mt: 0.5 }}>
      <Button
        size="small"
        onClick={toggle}
        sx={{
          textTransform: 'none',
          px: 0,
          minWidth: 0,
          fontSize: '0.72rem'
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
                      textTransform: 'uppercase',
                      color: 'var(--jp-ui-font-color2)',
                      letterSpacing: 0.5
                    }
                  : {
                      color: 'var(--jp-ui-font-color2)',
                      fontSize: '0.8rem'
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
