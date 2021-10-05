import React, { useMemo, ReactElement } from 'react';
import { Trans } from '@lingui/macro';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import getWalletHumanValue from '../../../util/getWalletHumanValue';

type Props = {
  walletId: number;
  tooltip?: ReactElement<any>;
};

export default function WalletCardPendingBalance(props: Props) {
  const { walletId, tooltip } = props;
  const { wallet, unit, loading } = useWallet(walletId);

  const isLoading = loading || !wallet?.wallet_balance;
  const value = wallet?.wallet_balance?.balance_pending;

  const humanValue = useMemo(() => wallet && value !== undefined && unit
      ? `${getWalletHumanValue(wallet, value)} ${unit}`
      : ''
  ,[value, wallet, unit]);

  return (
    <FarmCard
      loading={isLoading}
      valueColor="secondary"
      title={<Trans>Pending Balance</Trans>}
      tooltip={tooltip}
      value={humanValue}
    />
  );
}
