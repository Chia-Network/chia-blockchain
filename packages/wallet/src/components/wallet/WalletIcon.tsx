import React from 'react';
import { Logo } from '@chia/core';
import Wallet from '../../types/Wallet';
import WalletType from '../../constants/WalletType';
import Tokens from '../../constants/Tokens';

type Props = {
  wallet: Wallet;
};

export default function WalletIcon(props: Props) {
  const { wallet } = props;

  if (wallet.type === WalletType.STANDARD_WALLET) {
    return <Logo width={32} />;
  }

  if (wallet.type === WalletType.CAT) {
    const token = Tokens.find((token) => token.tail === wallet.colour);
    if (token) {
      return <token.icon fontSize="large" />
    }
  }

  return null;
}
