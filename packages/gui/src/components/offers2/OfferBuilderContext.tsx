import React, { createContext, useMemo } from 'react';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';
import OfferBuilderSectionType from './OfferBuilderSectionType';

export type OfferBuilderExpandedSections = {
  [key in OfferBuilderTradeSide]: OfferBuilderSectionType[];
};

export interface OfferBuilderContextData {
  expandedSections: OfferBuilderExpandedSections;
  updateExpandedSections: (
    side: OfferBuilderTradeSide,
    section: OfferBuilderSectionType,
    expanded: boolean,
  ) => void;
}

export const OfferBuilderContext = createContext<
  OfferBuilderContextData | undefined
>(undefined);

export type OfferBuilderProviderProps = {
  children: React.ReactNode;
};

export default function OfferBuilderProvider(props: OfferBuilderProviderProps) {
  const { children } = props;
  const [expandedSections, setExpandedSections] =
    React.useState<OfferBuilderExpandedSections>({
      [OfferBuilderTradeSide.Offering]: [],
      [OfferBuilderTradeSide.Requesting]: [],
    });

  function updateExpandedSections(
    side: OfferBuilderTradeSide,
    section: OfferBuilderSectionType,
    expanded: boolean,
  ) {
    setExpandedSections((prevExpandedSections) => {
      const prevExpanded = prevExpandedSections[side];
      const nextExpanded = expanded
        ? [...prevExpanded, section]
        : prevExpanded.filter((s) => s !== section);

      return {
        ...prevExpandedSections,
        [side]: nextExpanded,
      };
    });
  }

  const context = useMemo(
    () => ({
      expandedSections,
      updateExpandedSections,
    }),
    [expandedSections],
  );

  return (
    <OfferBuilderContext.Provider value={context}>
      {children}
    </OfferBuilderContext.Provider>
  );
}
