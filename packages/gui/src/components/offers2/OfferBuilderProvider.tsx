import { uniq } from 'lodash';
import React, { ReactNode, useMemo } from 'react';
import { useWatch } from 'react-hook-form';
import OfferBuilderContext from './OfferBuilderContext';

export type OfferBuilderProviderProps = {
  children: ReactNode;
  readOnly?: boolean;
};

export default function OfferBuilderProvider(props: OfferBuilderProviderProps) {
  const { children, readOnly = false } = props;

  const offeredTokens = useWatch({
    name: 'offered.tokens',
  });

  const requestedTokens = useWatch({
    name: 'requested.tokens',
  });

  const usedAssetIds = useMemo(() => {
    const used: string[] = [];

    offeredTokens?.forEach(({ assetId }: { assetId: string }) => {
      if (assetId) {
        used.push(assetId);
      }
    });
    requestedTokens?.forEach(({ assetId }: { assetId: string }) => {
      if (assetId) {
        used.push(assetId);
      }
    });

    return uniq(used);
  }, [offeredTokens, requestedTokens]);

  const context = useMemo(
    () => ({
      readOnly,
      usedAssetIds,
    }),
    [readOnly, usedAssetIds],
  );

  return (
    <OfferBuilderContext.Provider value={context}>
      {children}
    </OfferBuilderContext.Provider>
  );
}
