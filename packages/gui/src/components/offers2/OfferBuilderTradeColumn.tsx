import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { Offering, Requesting } from '@chia/icons';
import OfferBuilderHeader from './OfferBuilderHeader';
import OfferBuilderFeeSection from './OfferBuilderFeeSection';
import OfferBuilderNFTSection from './OfferBuilderNFTSection';
import OfferBuilderTokensSection from './OfferBuilderTokensSection';
import OfferBuilderXCHSection from './OfferBuilderXCHSection';
import useOfferBuilderContext from '../../hooks/useOfferBuilderContext';

/*
function mapWallets(wallets: Wallet[]): WalletMapping {
  const xchWallet = wallets.find(
    (wallet) => wallet.type === WalletType.STANDARD_WALLET,
  );
  const tokenWallets = wallets.filter(
    (wallet) => wallet.type === WalletType.CAT,
  );
  const nftWallets = wallets.filter((wallet) => wallet.type === WalletType.NFT);

  return {
    xch: xchWallet,
    tokens: tokenWallets,
    nfts: nftWallets,
  };
}
*/

export type OfferBuilderTradeColumnProps = {
  name: string;
  offering?: boolean;
};

export default function OfferBuilderTradeColumn(
  props: OfferBuilderTradeColumnProps,
) {
  const { name, offering = false } = props;

  const showFeeSection = offering;

  return (
    <Flex flexDirection="column" gap={3}>
      <OfferBuilderHeader
        icon={
          offering ? (
            <Offering fontSize="large" />
          ) : (
            <Requesting fontSize="large" />
          )
        }
        title={offering ? <Trans>Offering</Trans> : <Trans>Requesting</Trans>}
        subtitle={
          offering ? (
            <Trans>Assets I own that I&apos;d like to trade for</Trans>
          ) : (
            <Trans>Assets I&apos;d like to trade for</Trans>
          )
        }
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
        <OfferBuilderXCHSection name={`${name}.xch`} />
        <OfferBuilderTokensSection name={`${name}.tokens`} />
        <OfferBuilderNFTSection name={`${name}.nfts`} offering={offering} />
        {showFeeSection && <OfferBuilderFeeSection name={`${name}.fee`} />}
      </Flex>
    </Flex>
  );
}
