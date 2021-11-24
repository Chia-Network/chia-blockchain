import React, { useMemo, ReactElement } from 'react';
import { Trans } from '@lingui/macro';
import { useGetWalletBalanceQuery } from '@chia/api-react';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import getWalletHumanValue from '../../../util/getWalletHumanValue';

type Props = {
  walletId: number;
  tooltip?: ReactElement<any>;
};

export default function WalletCardSpendableBalance(props: Props) {
  const { walletId, tooltip } = props;

  const { 
    data: walletBalance, 
    isLoading: isLoadingWalletBalance,
    error,
  } = useGetWalletBalanceQuery({
    walletId,
  });

  const { wallet, unit = '', loading } = useWallet(walletId);

  const isLoading = loading || isLoadingWalletBalance;
  const value = walletBalance?.spendableBalance;

  const humanValue = useMemo(() => wallet && value !== undefined
      ? `${getWalletHumanValue(wallet, value)} ${unit}`
      : ''
  ,[value, wallet, unit]);

  return (
    <FarmCard
      loading={isLoading}
      valueColor="secondary"
      title={<Trans>Spendable Balance</Trans>}
      tooltip={tooltip}
      value={humanValue}
      error={error}
    />
  );
}
