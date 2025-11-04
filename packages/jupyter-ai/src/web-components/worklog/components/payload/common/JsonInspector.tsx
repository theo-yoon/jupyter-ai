import React from 'react';
import { Box, Button, Collapse } from '@mui/material';

import { JsonBlock } from './JsonBlock';

type JsonInspectorProps = {
  data: unknown;
  label?: string;
};

export const JsonInspector: React.FC<JsonInspectorProps> = ({
  data,
  label = 'Raw response'
}) => {
  const [expanded, setExpanded] = React.useState(false);
  const toggle = React.useCallback(() => setExpanded(prev => !prev), []);

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
        {expanded
          ? `Hide ${label.toLowerCase()}`
          : `Show ${label.toLowerCase()}`}
      </Button>
      <Collapse in={expanded} timeout="auto" unmountOnExit>
        <Box sx={{ mt: 0.5 }}>
          <JsonBlock value={data} />
        </Box>
      </Collapse>
    </Box>
  );
};
