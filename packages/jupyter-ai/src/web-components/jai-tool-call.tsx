import React from 'react';

import {
  ToolCallCardBase,
  ToolCallCardProps,
  ToolCallRenderContext,
  registerJupyterApp
} from './tool-call-card/base';
import { getToolCallCard, ToolCallCardConstructor } from './tool-call-card/registry';

class DefaultToolCallCard extends ToolCallCardBase<ToolCallCardProps> {
  protected renderContent(context: ToolCallRenderContext): JSX.Element {
    return this.renderDefaultContent(context);
  }
}

export function JaiToolCall(props: ToolCallCardProps): JSX.Element | null {
  const CardCtor: ToolCallCardConstructor<ToolCallCardProps> | undefined =
    getToolCallCard<ToolCallCardProps>(props.function_name);
  const CardComponent =
    CardCtor ?? DefaultToolCallCard;
  return <CardComponent {...props} />;
}

export { registerJupyterApp };
