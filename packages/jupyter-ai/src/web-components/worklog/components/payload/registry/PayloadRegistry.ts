import React from 'react';

export type PayloadRendererProps = Record<string, unknown> & {
  sectionKey?: string;
};
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

type RenderPayloadSectionOptions = {
  stateKey?: string;
  stateGroup?: string;
  reactKey?: string;
};

export const renderPayloadSection = (
  key: string,
  props: Record<string, unknown>,
  fallback: React.ReactNode,
  options: RenderPayloadSectionOptions = {}
): React.ReactNode => {
  const Renderer = getPayloadRenderer(key);
  if (!Renderer) {
    return fallback;
  }
  const elementKey = options.reactKey ?? key;
  return React.createElement(Renderer, {
    ...props,
    sectionKey: options.stateKey,
    sectionGroup: options.stateGroup,
    key: elementKey
  });
};
