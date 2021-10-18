import React from 'react';
import { Logo } from '@chia/core';
import styled from 'styled-components';
import Wallet from '../../types/Wallet';
import WalletType from '../../constants/WalletType';
import Tokens from '../../constants/Tokens';
import { Typography } from '@material-ui/core';

const StyledSymbol = styled(Typography)`
  font-size: 1rem;
  font-weight: 600;
`;

type Props = {
  wallet: Wallet;
};

export default function WalletIcon(props: Props) {
  const { wallet } = props;

  if (wallet.type === WalletType.STANDARD_WALLET) {
    return <Logo width={32} />;
  }

  if (wallet.type === WalletType.CAT) {
    const token = Tokens.find((token) => token.tail === wallet.meta?.tail);
    if (token) {
      return <StyledSymbol color="primary">{token.symbol}</StyledSymbol>;
      // return <token.icon fontSize="large" />
    }
  }

  return null;
}
