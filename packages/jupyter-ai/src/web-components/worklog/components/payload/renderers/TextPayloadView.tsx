import React from 'react';

import { TextBlock } from '../common';
import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type TextPayloadViewProps = {
  text: string;
  format?: 'plain' | 'markdown' | 'ansi';
};

export const TextPayloadView: React.FC<TextPayloadViewProps> = ({
  text,
  format = 'plain'
}) => <TextBlock text={text} format={format} />;

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
