import React from 'react';
import { Trans } from '@lingui/macro';
import { Tokens } from '@chia/icons';
import OfferBuilderSection, {
  OfferBuilderSectionProps,
} from './OfferBuilderSection';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';
import OfferBuilderSectionType from './OfferBuilderSectionType';

type OfferBuilderTokensSectionProps = OfferBuilderSectionProps & {
  side: OfferBuilderTradeSide;
};

export default function OfferBuilderTokensSection(
  props: OfferBuilderTokensSectionProps,
): JSX.Element {
  const { side, ...rest } = props;
  return (
    <OfferBuilderSection
      icon={<Tokens />}
      title={<Trans>Tokens</Trans>}
      subtitle={
        <Trans>Chia Asset Tokens (CATs) are tokens built on top of XCH</Trans>
      }
      side={side}
      sectionType={OfferBuilderSectionType.Tokens}
      {...rest}
    />
  );
}
