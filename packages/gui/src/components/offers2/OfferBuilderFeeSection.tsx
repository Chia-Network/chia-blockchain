import React from 'react';
import { Trans } from '@lingui/macro';
import { FullNode } from '@chia/icons';
import OfferBuilderSection from './OfferBuilderSection';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';
import OfferBuilderSectionType from './OfferBuilderSectionType';

type OfferBuilderFeeSectionProps = {
  side: OfferBuilderTradeSide;
};

export default function OfferBuilderFeeSection(
  props: OfferBuilderFeeSectionProps,
): JSX.Element {
  const { side, ...rest } = props;

  return (
    <OfferBuilderSection
      icon={<FullNode />}
      title={<Trans>Fee</Trans>}
      subtitle={
        <Trans>Optional network fee to expedite acceptance of your offer</Trans>
      }
      side={side}
      sectionType={OfferBuilderSectionType.Fee}
      {...rest}
    />
  );
}
