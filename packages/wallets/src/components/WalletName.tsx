import { Typography, type TypographyProps } from '@mui/material';
import React from 'react';
import useWallet from '../hooks/useWallet';
import getWalletPrimaryTitle from '../utils/getWalletPrimaryTitle';

export type WalletNameProps = TypographyProps & {
  walletId: number;
};


export default function WalletName(props: WalletNameProps) {
  const { walletId, ...rest } = props;
  const { wallet, loading } = useWallet(walletId);

  if (loading || !wallet) {
    return null;
  }

  const primaryTitle = getWalletPrimaryTitle(wallet);

  return (
    <Typography {...rest}>
      {primaryTitle}
    </Typography>
  );
}