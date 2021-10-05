import React, { useMemo, ReactElement } from 'react';
import { Trans } from '@lingui/macro';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import getWalletHumanValue from '../../../util/getWalletHumanValue';

type Props = {
  walletId: number;
  tooltip?: ReactElement<any>;
};

export default function WalletCardPendingChange(props: Props) {
  const { walletId, tooltip } = props;
  const { wallet, loading, unit } = useWallet(walletId);

  const isLoading = loading || !wallet?.wallet_balance;
  const value = wallet?.wallet_balance?.pending_change;

  const humanValue = useMemo(() => wallet && value !== undefined && unit
    ? `${getWalletHumanValue(wallet, value)} ${unit}`
    : ''
  ,[value, wallet, unit]);


  return (
    <FarmCard
      loading={isLoading}
      valueColor="secondary"
      title={<Trans>Pending Change</Trans>}
      tooltip={tooltip}
      value={humanValue}
    />
  );
}
