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

export default function WalletCardSpendableBalance(props: Props) {
  const { wallet_id } = props;

  const { wallet, loading } = useWallet(wallet_id);
  const currencyCode = useCurrencyCode();

  const value = wallet?.wallet_balance?.spendable_balance;

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
      title={<Trans>Spendable Balance</Trans>}
      tooltip={
        <Trans>
          This is the amount of Chia that you can currently use to make
          transactions. It does not include pending farming rewards, pending
          incoming transactions, and Chia that you have just spent but is not
          yet in the blockchain.
        </Trans>
      }
      value={
        <>
          {formatedValue} {formatedCurrencyCode}
        </>
      }
    />
  );
}
