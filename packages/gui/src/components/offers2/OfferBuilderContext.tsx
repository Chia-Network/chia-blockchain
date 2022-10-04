import { createContext } from 'react';

export interface OfferBuilderContextData {
  readOnly: boolean;
  usedAssetIds: string[];
  isExpanded: (name: string) => boolean;
  expand: (name: string, expanded: boolean) => void;
}

const OfferBuilderContext = createContext<OfferBuilderContextData | undefined>(
  undefined,
);

export default OfferBuilderContext;
