import React from 'react';
import NotesOutlinedIcon from '@mui/icons-material/NotesOutlined';

import { PayloadCard, TextBlock } from '../common';
import { registerPayloadRenderer } from '../registry';

type ToolDisplayTextViewProps = {
  title?: string;
  text: string;
  format?: 'plain' | 'markdown' | 'ansi';
  sectionKey?: string;
  sectionGroup?: string;
};

export const ToolDisplayTextView: React.FC<ToolDisplayTextViewProps> = ({
  title,
  text,
  format = 'plain',
  sectionKey,
  sectionGroup
}) => (
  <PayloadCard
    title={title ?? 'Tool notes'}
    icon={<NotesOutlinedIcon fontSize="small" />}
    collapsible
    defaultExpanded
    stateKey={sectionKey}
    stateGroup={sectionGroup}
  >
    <TextBlock text={text} format={format} maxHeight={360} />
  </PayloadCard>
);

registerPayloadRenderer('tool-display:text', ToolDisplayTextView);
