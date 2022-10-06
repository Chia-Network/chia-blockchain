import { createContext } from 'react';

export interface OfferBuilderContextData {
  readOnly: boolean;
  usedAssetIds: string[];
}

const OfferBuilderContext = createContext<OfferBuilderContextData | undefined>(
  undefined,
);

export default OfferBuilderContext;
