import React from 'react';
import { Box, Button, Collapse, Stack, Typography } from '@mui/material';

type WorklogErrorPanelProps = {
  message?: string;
  errorType?: string;
  trace?: string;
  showTrace: boolean;
  onToggleTrace: () => void;
};

export function WorklogErrorPanel({
  message,
  errorType,
  trace,
  showTrace,
  onToggleTrace
}: WorklogErrorPanelProps) {
  if (!message) {
    return null;
  }

  return (
    <Box
      sx={{
        border: '1px solid var(--jp-error-color1)',
        backgroundColor: 'rgba(235, 87, 87, 0.08)',
        borderRadius: 1.5,
        px: 1.5,
        py: 1
      }}
    >
      <Stack spacing={0.6}>
        <Typography variant="subtitle2" color="error" sx={{ fontWeight: 600 }}>
          작업이 실패했습니다
        </Typography>
        <Typography
          variant="body2"
          color="error"
          sx={{ whiteSpace: 'pre-wrap' }}
        >
          {errorType ? `${errorType}: ` : ''}
          {message}
        </Typography>
        {trace && (
          <Box>
            <Button
              size="small"
              variant="text"
              sx={{ px: 0, minWidth: 'auto', alignSelf: 'flex-start' }}
              onClick={onToggleTrace}
            >
              {showTrace ? '오류 세부정보 숨기기' : '오류 세부정보 보기'}
            </Button>
            <Collapse in={showTrace} timeout="auto" unmountOnExit>
              <Box
                component="pre"
                sx={{
                  fontFamily: 'var(--jp-code-font-family)',
                  fontSize: '0.75rem',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  m: 0,
                  maxHeight: 260,
                  overflow: 'auto',
                  backgroundColor: 'rgba(0,0,0,0.04)',
                  borderRadius: 1,
                  px: 1,
                  py: 0.75
                }}
              >
                {trace}
              </Box>
            </Collapse>
          </Box>
        )}
      </Stack>
    </Box>
  );
}
