import React, { useMemo, ReactElement } from 'react';
import { Trans } from '@lingui/macro';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import getWalletHumanValue from '../../../util/getWalletHumanValue';

type Props = {
  walletId: number;
  tooltip?: ReactElement<any>;
};

export default function WalletCardPendingTotalBalance(props: Props) {
  const { walletId, tooltip } = props;
  const { wallet, loading, unit = '' } = useWallet(walletId);

  const isLoading = loading || !wallet?.wallet_balance;

  const balance = wallet?.wallet_balance?.confirmed_wallet_balance;
  const balance_pending = wallet?.wallet_balance?.balance_pending;

  const value = balance + balance_pending;

  const humanValue = useMemo(() => wallet && value !== undefined
    ? `${getWalletHumanValue(wallet, value)} ${unit}`
    : ''
  ,[value, wallet, unit]);


  return (
    <FarmCard
      loading={isLoading}
      valueColor="secondary"
      title={<Trans>Pending Total Balance</Trans>}
      tooltip={tooltip}
      value={humanValue}
    />
  );
}
