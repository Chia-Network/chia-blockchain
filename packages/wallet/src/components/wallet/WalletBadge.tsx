import React from 'react';
import { Trans } from '@lingui/macro';
import { Tooltip } from '@chia/core'
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
  const { wallet, tooltip, ...rest } = props;

  if (wallet.type === WalletType.CAT) {
    const token = Tokens.find((token) => token.tail === wallet.meta?.tail);
    if (token) {
      return (
        <Tooltip title={<Trans>This access token is whitelisted</Trans>}>
          <StyledSmallBadge {...rest} />
        </Tooltip>
      );
    }
  }

  return null;
}

