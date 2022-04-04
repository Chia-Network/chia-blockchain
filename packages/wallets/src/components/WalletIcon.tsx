import React from 'react';
import { useCurrencyCode } from '@chia/core';
import styled from 'styled-components';
import { useGetCatListQuery } from '@chia/api-react';
import { WalletType, type Wallet } from '@chia/api';
import { Typography, type TypographyProps } from '@mui/material';

const StyledSymbol = styled(Typography)`
  font-size: 1rem;
`;

export type WalletIconProps = TypographyProps & {
  wallet: Wallet;
  color?: string;
};

export default function WalletIcon(props: WalletIconProps) {
  const { wallet, color = 'primary', ...rest } = props;
  const { data: catList = [], isLoading } = useGetCatListQuery();
  const currencyCode = useCurrencyCode();

  if (wallet.type === WalletType.STANDARD_WALLET) {
    return <StyledSymbol color={color} {...rest}>{currencyCode}</StyledSymbol>;
  }

  if (!isLoading && wallet.type === WalletType.CAT) {
    const token = catList.find((token) => token.assetId === wallet.meta?.assetId);
    if (token) {
      return <StyledSymbol color={color} {...rest}>{token.symbol}</StyledSymbol>;
    }
  }

  return null;
}
