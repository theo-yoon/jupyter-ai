import React from 'react';

export type PayloadRendererProps = Record<string, unknown>;
export type PayloadRenderer = React.ComponentType<any>;

const rendererRegistry = new Map<string, PayloadRenderer>();

export const registerPayloadRenderer = (
  key: string,
  renderer: PayloadRenderer
): void => {
  rendererRegistry.set(key, renderer);
};

export const getPayloadRenderer = (key: string): PayloadRenderer | undefined =>
  rendererRegistry.get(key);

export const getRegisteredPayloadKeys = (): string[] => [
  ...rendererRegistry.keys()
];

export const renderPayloadSection = (
  key: string,
  props: Record<string, unknown>,
  fallback: React.ReactNode
): React.ReactNode => {
  const Renderer = getPayloadRenderer(key);
  return Renderer ? React.createElement(Renderer, { ...props, key }) : fallback;
};
