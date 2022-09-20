import React, { useMemo } from 'react';
import { t } from '@lingui/macro';
import { Wallet, WalletType } from '@chia/api';
import { useGetWalletsQuery } from '@chia/api-react';
import { Flex, Loading, getColorModeValue } from '@chia/core';
import { Offering, Requesting } from '@chia/icons';
import { Theme, useTheme } from '@mui/material';
import { OfferBuilderMode } from './OfferBuilder';
import OfferBuilderHeader from './OfferBuilderHeader';
import OfferBuilderFeeSection from './OfferBuilderFeeSection';
import OfferBuilderNFTSection from './OfferBuilderNFTSection';
import OfferBuilderTokensSection from './OfferBuilderTokensSection';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';
import OfferBuilderXCHSection from './OfferBuilderXCHSection';

type HeaderStrings = {
  title: string;
  subtitle: string;
};

function getHeaderStrings(side: OfferBuilderTradeSide): HeaderStrings {
  switch (side) {
    case OfferBuilderTradeSide.Offering:
      return {
        title: t`Offering`,
        subtitle: t`Assets I own that I'd like to trade for`,
      };
    case OfferBuilderTradeSide.Requesting:
      return {
        title: t`Requesting`,
        subtitle: t`Assets I'd like to trade for`,
      };
  }
}

type OfferBuilderTradeColumnStyle = {
  container: any;
  headerIcon: any;
};

function getStyle(theme: Theme): OfferBuilderTradeColumnStyle {
  return {
    container: {
      border: `1px solid ${getColorModeValue(theme, 'border')}`,
      borderRadius: '16px',
      p: '8px',
    },
    headerIcon: {
      width: '100%',
      height: '100%',
      p: '16px',
    },
  };
}

function getHeaderIcon(
  side: OfferBuilderTradeSide,
  style: any,
): React.ReactNode {
  switch (side) {
    case OfferBuilderTradeSide.Offering:
      return <Offering sx={style} />;
    case OfferBuilderTradeSide.Requesting:
      return <Requesting sx={style} />;
  }
}

type WalletMapping = {
  xch: Wallet;
  tokens: Wallet[];
  nfts: Wallet[];
};

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

type Props = {
  mode: OfferBuilderMode;
  side: OfferBuilderTradeSide;
  formNamePrefix: string;
};

export default function OfferBuilderTradeColumn(props: Props): JSX.Element {
  const { mode, side, formNamePrefix } = props;
  const { data: wallets, isLoading: isLoadingWallets } = useGetWalletsQuery();
  const theme = useTheme();
  const style = getStyle(theme);
  const { title, subtitle } = getHeaderStrings(side);
  const headerIcon = getHeaderIcon(side, style.headerIcon);
  const editable = mode === OfferBuilderMode.Building;
  const includeFee =
    (mode === OfferBuilderMode.Building &&
      side === OfferBuilderTradeSide.Offering) ||
    (mode === OfferBuilderMode.Viewing &&
      side === OfferBuilderTradeSide.Requesting);

  const walletMapping = useMemo(() => {
    if (isLoadingWallets || !wallets) {
      return undefined;
    }

    return mapWallets(wallets);
  }, [wallets, isLoadingWallets]);

  return (
    <>
      {isLoadingWallets ? (
        <Loading center />
      ) : (
        <Flex flexDirection="column" gap={3}>
          <OfferBuilderHeader
            icon={headerIcon}
            title={title}
            subtitle={subtitle}
          />
          <Flex
            flexDirection="column"
            flexGrow={1}
            gap={1}
            sx={style.container}
          >
            <OfferBuilderXCHSection
              wallet={walletMapping?.xch}
              formNamePrefix={formNamePrefix}
              editable={editable}
              side={side}
            />
            <OfferBuilderTokensSection side={side} />
            <OfferBuilderNFTSection side={side} />
            {includeFee && <OfferBuilderFeeSection side={side} />}
          </Flex>
        </Flex>
      )}
    </>
  );
}
