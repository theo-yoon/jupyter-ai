import React from 'react';
import { Stack } from '@mui/material';

import { TimelineNode } from './TimelineNode';

export type TimelineItem = {
  id: string;
  title: string;
  titleColor: string;
  titleWeight: number;
  subtitle?: string;
  meta?: React.ReactNode[];
  statusIndicator?: React.ReactNode;
  icon: React.ReactNode;
  iconColor: string;
  iconGlow?: Record<string, unknown>;
  expandable: boolean;
  expanded: boolean;
  onToggle: () => void;
  details: React.ReactNode[];
};

type TimelineProps = {
  items: TimelineItem[];
};

export const Timeline: React.FC<TimelineProps> = ({ items }) => (
  <Stack spacing={1}>
    {items.map((item, index) => (
      <TimelineNode
        key={item.id}
        id={item.id}
        title={item.title}
        titleColor={item.titleColor}
        titleWeight={item.titleWeight}
        subtitle={item.subtitle}
        meta={item.meta}
        statusIndicator={item.statusIndicator}
        icon={item.icon}
        iconColor={item.iconColor}
        iconGlow={item.iconGlow}
        isFirst={index === 0}
        isLast={index === items.length - 1}
        expandable={item.expandable}
        expanded={item.expanded}
        onToggle={item.onToggle}
        details={item.details}
      />
    ))}
  </Stack>
);
