import React from 'react';
import { VerifiedUser as VerifiedUserIcon, VerifiedUserProps } from '@material-ui/icons';
import styled from 'styled-components';
import Wallet from '../../types/Wallet';
import WalletType from '../../constants/WalletType';
import Tokens from '../../constants/Tokens';

const StyledSmallBadge = styled(VerifiedUserIcon)`
  font-size: 1rem;
`;

type Props = VerifiedUserProps & {
  wallet: Wallet;
};

export default function WalletBadge(props: Props) {
  const { wallet, ...rest } = props;

  if (wallet.type === WalletType.CAT) {
    const token = Tokens.find((token) => token.tail === wallet.colour);
    if (token) {
      return <StyledSmallBadge {...rest} />
    }
  }

  return null;
}
