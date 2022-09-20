import React from 'react';
import { Trans } from '@lingui/macro';
import { NFTs } from '@chia/icons';
import OfferBuilderSection from './OfferBuilderSection';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';
import OfferBuilderSectionType from './OfferBuilderSectionType';

type OfferBuilderNFTSectionProps = {
  side: OfferBuilderTradeSide;
};

export default function OfferBuilderNFTSection(
  props: OfferBuilderNFTSectionProps,
): JSX.Element {
  const { side, ...rest } = props;

  return (
    <OfferBuilderSection
      icon={<NFTs />}
      title={<Trans>NFT</Trans>}
      subtitle={<Trans>One-of-a-kind Collectible assets</Trans>}
      side={side}
      sectionType={OfferBuilderSectionType.NFTs}
      {...rest}
    />
  );
}
