import { uniq } from 'lodash';
import React, { ReactNode, useState, useMemo, useCallback } from 'react';
import { useWatch } from 'react-hook-form';
import OfferBuilderContext from './OfferBuilderContext';

export type OfferBuilderProviderProps = {
  children: ReactNode;
  readOnly?: boolean;
};

export default function OfferBuilderProvider(props: OfferBuilderProviderProps) {
  const { children, readOnly = false } = props;
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

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

  const isExpanded = useCallback(
    (name: string) => {
      return expanded[name] ?? false;
    },
    [expanded],
  );

  const expand = useCallback((name: string, expanded: boolean) => {
    setExpanded((prevExpanded) => {
      if (prevExpanded[name] === expanded) {
        return prevExpanded;
      }

      return {
        ...prevExpanded,
        [name]: expanded,
      };
    });
  }, []);

  const context = useMemo(
    () => ({
      isExpanded,
      expand,
      readOnly,
      usedAssetIds,
    }),
    [isExpanded, expand, readOnly, usedAssetIds],
  );

  return (
    <OfferBuilderContext.Provider value={context}>
      {children}
    </OfferBuilderContext.Provider>
  );
}
