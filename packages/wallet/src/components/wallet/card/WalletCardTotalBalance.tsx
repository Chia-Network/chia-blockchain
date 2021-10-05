import React, { useMemo, ReactElement } from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import WalletGraph from '../WalletGraph';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import getWalletHumanValue from '../../../util/getWalletHumanValue';

const StyledGraphContainer = styled.div`
  margin-left: -1rem;
  margin-right: -1rem;
  margin-top: 1rem;
  margin-bottom: -1rem;
`;

type Props = {
  walletId: number;
  tooltip?: ReactElement<any>;
};

export default function WalletCardTotalBalance(props: Props) {
  const { walletId, tooltip } = props;
  const { wallet, loading, unit = '' } = useWallet(walletId);

  const isLoading = loading || !wallet?.wallet_balance;
  const value = wallet?.wallet_balance?.confirmed_wallet_balance;
  const humanValue = useMemo(() => wallet && value !== undefined
    ? `${getWalletHumanValue(wallet, value)} ${unit}`
    : ''
  ,[value, wallet, unit]);

  return (
    <FarmCard
      loading={isLoading}
      title={<Trans>Total Balance</Trans>}
      tooltip={tooltip}
      value={humanValue} 
      description={
        <StyledGraphContainer>
          <WalletGraph walletId={walletId} height={114} />
        </StyledGraphContainer>
      }
    />
  );
}
