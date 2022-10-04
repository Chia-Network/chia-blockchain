import React, { ReactNode, useState, useMemo, useCallback } from 'react';
import OfferBuilderContext from './OfferBuilderContext';

export type OfferBuilderProviderProps = {
  children: ReactNode;
  readOnly?: boolean;
};

export default function OfferBuilderProvider(props: OfferBuilderProviderProps) {
  const { children, readOnly = false } = props;
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

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
    }),
    [isExpanded, expand, readOnly],
  );

  return (
    <OfferBuilderContext.Provider value={context}>
      {children}
    </OfferBuilderContext.Provider>
  );
}
