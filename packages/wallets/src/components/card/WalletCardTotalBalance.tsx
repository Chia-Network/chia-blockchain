import React, { useMemo, ReactElement } from 'react';
import { Trans } from '@lingui/macro';
import { useGetWalletBalanceQuery } from '@chia/api-react';
import styled from 'styled-components';
import WalletGraph from '../WalletGraph';
import { CardSimple } from '@chia/core';
import useWallet from '../../hooks/useWallet';
import useWalletHumanValue from '../../hooks/useWalletHumanValue';

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

  const { 
    data: walletBalance, 
    isLoading: isLoadingWalletBalance,
    error,
  } = useGetWalletBalanceQuery({
    walletId,
  }, {
    pollingInterval: 10000,
  });

  const { wallet, unit = '', loading } = useWallet(walletId);

  const isLoading = loading || isLoadingWalletBalance;
  const value = walletBalance?.confirmedWalletBalance;

  const humanValue = useWalletHumanValue(wallet, value, unit);

  return (
    <CardSimple
      loading={isLoading}
      title={<Trans>Total Balance</Trans>}
      tooltip={tooltip}
      value={humanValue}
      error={error}
      description={
        <StyledGraphContainer>
          <WalletGraph walletId={walletId} height={114} />
        </StyledGraphContainer>
      }
    />
  );
}
