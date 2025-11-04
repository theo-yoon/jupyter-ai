import type { WorkNode } from '../../types';

export type WorkNodeListProps = {
  nodes: WorkNode[];
  virtualNode?: WorkNode | null;
  stateNamespace?: string;
};
