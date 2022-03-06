import React, { ReactElement } from 'react';
import { Trans } from '@lingui/macro';
import { useGetWalletBalanceQuery } from '@chia/api-react';
import { CardSimple } from '@chia/core';
import useWallet from '../../hooks/useWallet';
import useWalletHumanValue from '../../hooks/useWalletHumanValue';

type Props = {
  walletId: number;
  tooltip?: ReactElement<any>;
};

export default function WalletCardPendingChange(props: Props) {
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
  const value = walletBalance?.pendingChange;

  const humanValue = useWalletHumanValue(wallet, value, unit);

  return (
    <CardSimple
      loading={isLoading}
      valueColor="secondary"
      title={<Trans>Pending Change</Trans>}
      tooltip={tooltip}
      value={humanValue}
      error={error}
    />
  );
}
