import React from 'react';
import NotesOutlinedIcon from '@mui/icons-material/NotesOutlined';

import { PayloadCard, TextBlock } from '../common';
import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type TextPayloadViewProps = {
  text: string;
  format?: 'plain' | 'markdown' | 'ansi';
};

export const TextPayloadView: React.FC<TextPayloadViewProps> = ({
  text,
  format = 'plain'
}) => (
  <PayloadCard
    title="Text output"
    subtitle="긴 텍스트는 자동으로 접혀요."
    icon={<NotesOutlinedIcon fontSize="small" />}
    collapsible
    defaultExpanded={false}
  >
    <TextBlock text={text} format={format} maxHeight={220} />
  </PayloadCard>
);

registerContentAdapter('text', payload => {
  const textPayload = payload as Partial<{
    content: string;
    format?: 'plain' | 'markdown' | 'ansi';
  }>;
  return {
    sections: [
      {
        key: 'content:text',
        props: {
          text: textPayload.content ?? '',
          format: textPayload.format ?? 'plain'
        }
      }
    ]
  };
});

registerPayloadRenderer('content:text', TextPayloadView);
registerPayloadRenderer('fallback:text', TextPayloadView);
