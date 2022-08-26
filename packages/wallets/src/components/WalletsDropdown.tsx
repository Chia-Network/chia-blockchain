import React, { useMemo } from 'react';
import { ListItemIcon, ListItemText, Typography } from '@mui/material';
import { Dropdown, Flex, Loading, useTrans } from '@chia/core';
import { useGetWalletsQuery } from '@chia/api-react';
import { WalletType, type Wallet } from '@chia/api';
import { useNavigate } from 'react-router';
import WalletName from '../constants/WalletName';
import WalletIcon from './WalletIcon';
import WalletBadge from './WalletBadge';

function getPrimaryTitle(wallet: Wallet): string {
  switch (wallet.type) {
    case WalletType.STANDARD_WALLET:
      return 'Chia';
    default:
      return wallet.name;
  }
}

type Props = {
};

export default function WalletsDropdown(props: Props) {
  const navigate = useNavigate();
  const trans = useTrans();
  const { data: wallets, isLoading } = useGetWalletsQuery();

  const options = useMemo(() => {
    if (isLoading) {
      return [];
    }

    return wallets
      .filter(wallet => ![WalletType.POOLING_WALLET, WalletType.DATA_LAYER].includes(wallet.type))
      .map((wallet) => {
        const primaryTitle = getPrimaryTitle(wallet);
        const secondaryTitle = trans(WalletName[wallet.type]);
        const hasSameTitle = primaryTitle.toLowerCase() === secondaryTitle.toLowerCase();

        return {
          wallet,
          value: wallet.id,
          label: (
            <>
              <ListItemIcon>
                <WalletIcon wallet={wallet} />
              </ListItemIcon>
              <ListItemText
                primary={(
                  <Flex gap={1} alignItems="center">
                    <Typography>{primaryTitle}</Typography>
                    <WalletBadge wallet={wallet} fontSize="small" tooltip />
                  </Flex>
                )}
                secondary={!hasSameTitle ? secondaryTitle: undefined}
                secondaryTypographyProps={{
                  variant: 'caption',
                }}
              />
            </>
          ),
        };
      });
  }, [wallets, isLoading]);

  function handleSelectWallet(walletId: number) {
    navigate(`/dashboard/wallets/${walletId}`);
  }

  if (isLoading) {
    return (
      <Loading size="small" />
    );
  }

  return (
    <Dropdown 
      options={options}
      selected={1}
      onSelect={handleSelectWallet}
    >
      {(option) => !!option?.wallet && (
        <Flex gap={1} alignItems="center">
          <Typography>{getPrimaryTitle(option.wallet)}</Typography>
          <WalletBadge wallet={option.wallet} fontSize="small" />
        </Flex>
      )}
    </Dropdown>
  );
}
