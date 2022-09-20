import { OfferBuilderExpandedSections } from './OfferBuilderContext';
import OfferBuilderSectionType from './OfferBuilderSectionType';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';

export function isOpposingSectionExpanded(
  ourSide: OfferBuilderTradeSide,
  section: OfferBuilderSectionType,
  expandedSections: OfferBuilderExpandedSections,
): boolean {
  const opposingSide =
    ourSide === OfferBuilderTradeSide.Offering
      ? OfferBuilderTradeSide.Requesting
      : OfferBuilderTradeSide.Offering;

  return expandedSections[opposingSide]?.includes(section) ?? false;
}
