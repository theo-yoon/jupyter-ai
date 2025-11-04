import React from 'react';

import { TextBlock } from '../common';

type TextPayloadViewProps = {
  text: string;
  format?: 'plain' | 'markdown' | 'ansi';
};

export const TextPayloadView: React.FC<TextPayloadViewProps> = ({
  text,
  format = 'plain'
}) => <TextBlock text={text} format={format} />;
