import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { useWatch } from 'react-hook-form';
import { Offering, Requesting } from '@chia/icons';
import OfferBuilderHeader from './OfferBuilderHeader';
import OfferBuilderFeeSection from './OfferBuilderFeeSection';
import OfferBuilderNFTSection from './OfferBuilderNFTSection';
import OfferBuilderTokensSection from './OfferBuilderTokensSection';
import OfferBuilderXCHSection from './OfferBuilderXCHSection';
import useOfferBuilderContext from '../../hooks/useOfferBuilderContext';

function getTitle(offering = false, viewer = false, isMyOffer = false) {
  if (isMyOffer) {
    offering = !offering;
  }

  if (offering) {
    if (viewer) {
      return <Trans>You will give</Trans>;
    }

    return <Trans>Offering</Trans>;
  }

  if (viewer) {
    return <Trans>In exchange for</Trans>;
  }

  return <Trans>Requesting</Trans>;
}

function getSubTitle(offering = false, viewer = false, isMyOffer = false) {
  if (isMyOffer) {
    offering = !offering;
  }

  if (offering) {
    if (viewer) {
      return <Trans>Assets you will give</Trans>;
    }

    return <Trans>Assets I own that I&apos;d like to trade for</Trans>;
  }

  if (viewer) {
    return <Trans>Assets that will be added to your wallet</Trans>;
  }

  return <Trans>Assets I&apos;d like to trade for</Trans>;
}

function getIcon(offering = false, isMyOffer = false) {
  if (isMyOffer) {
    offering = !offering;
  }

  return offering ? (
    <Offering fontSize="large" />
  ) : (
    <Requesting fontSize="large" />
  );
}

export type OfferBuilderTradeColumnProps = {
  name: string;
  offering?: boolean;
  viewer?: boolean;
  isMyOffer?: boolean;
};

export default function OfferBuilderTradeColumn(
  props: OfferBuilderTradeColumnProps,
) {
  const { name, offering = false, viewer = false, isMyOffer = false } = props;
  const { readOnly } = useOfferBuilderContext();

  const xch = useWatch({
    name: `${name}.xch`,
  });

  const nfts = useWatch({
    name: `${name}.nfts`,
  });

  const tokens = useWatch({
    name: `${name}.tokens`,
  });

  const showXCH = !readOnly || !!xch.length;
  const showTokensSection = !readOnly || !!tokens.length;
  const showNFTSection = !readOnly || !!nfts.length;
  const showFeeSection = offering || viewer;

  const mutedXCH = nfts.length || tokens.length;
  const mutedTokens = xch.length || nfts.length;
  const mutedNFTs = xch.length || tokens.length;

  return (
    <Flex flexDirection="column" gap={3}>
      <OfferBuilderHeader
        icon={getIcon(offering, isMyOffer)}
        title={getTitle(offering, viewer, isMyOffer)}
        subtitle={getSubTitle(offering, viewer, isMyOffer)}
      />
      <Flex
        flexDirection="column"
        flexGrow={1}
        gap={1}
        sx={{
          borderRadius: 2,
          backgroundColor: 'action.hover',
          border: '1px solid',
          borderColor: 'divider',
          padding: 1,
        }}
      >
        {showXCH && (
          <OfferBuilderXCHSection
            name={`${name}.xch`}
            offering={offering}
            muted={mutedXCH}
          />
        )}

        {showTokensSection && (
          <OfferBuilderTokensSection
            name={`${name}.tokens`}
            offering={offering}
            muted={mutedTokens}
          />
        )}

        {showNFTSection && (
          <OfferBuilderNFTSection
            name={`${name}.nfts`}
            offering={offering}
            muted={mutedNFTs}
            viewer={viewer}
            isMyOffer={isMyOffer}
          />
        )}

        {showFeeSection && (
          <OfferBuilderFeeSection
            name={`${name}.fee`}
            offering={offering}
            viewer={viewer}
          />
        )}
      </Flex>
    </Flex>
  );
}
