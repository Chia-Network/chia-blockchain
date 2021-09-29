import React from 'react';
import { Trans } from '@lingui/macro';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import { mojo_to_chia_string, mojo_to_colouredcoin_string } from '../../../util/chia';
import getCatUnit from '../../../util/getCatUnit';
import WalletType from '../../../constants/WalletType';

type Props = {
  wallet_id: number;
};

export default function WalletCardPendingBalance(props: Props) {
  const { wallet_id } = props;

  const { wallet, loading } = useWallet(wallet_id);
  const currencyCode = useCurrencyCode();

  const value = wallet?.wallet_balance?.balance_pending;

  const formatedValue = wallet?.type === WalletType.CAT
    ? mojo_to_colouredcoin_string(value)
    : mojo_to_chia_string(value);

  const formatedCurrencyCode = wallet?.type === WalletType.CAT
    ? getCatUnit(wallet?.name)
    : currencyCode;

  return (
    <FarmCard
      loading={loading}
      valueColor="secondary"
      title={<Trans>Pending Balance</Trans>}
      tooltip={
        <Trans>
          This is the sum of the incoming and outgoing pending transactions (not
          yet included into the blockchain). This does not include farming
          rewards.
        </Trans>
      }
      value={
        <span>
          {formatedValue} {formatedCurrencyCode}
        </span>
      }
    />
  );
}
