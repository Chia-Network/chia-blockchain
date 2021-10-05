import React, { useMemo, ReactElement } from 'react';
import { Trans } from '@lingui/macro';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import getWalletHumanValue from '../../../util/getWalletHumanValue';

type Props = {
  walletId: number;
  tooltip?: ReactElement<any>;
};

export default function WalletCardSpendableBalance(props: Props) {
  const { walletId, tooltip } = props;
  const { wallet, loading, unit } = useWallet(walletId);

  const isLoading = loading || !wallet?.wallet_balance;
  const value = wallet?.wallet_balance?.spendable_balance;

  const humanValue = useMemo(() => wallet && value !== undefined && unit
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
    />
  );
}
