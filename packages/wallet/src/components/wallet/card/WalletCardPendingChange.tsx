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

export default function WalletCardPendingChange(props: Props) {
  const { wallet_id } = props;

  const { wallet, loading } = useWallet(wallet_id);
  const currencyCode = useCurrencyCode();

  const value = wallet?.wallet_balance?.pending_change;

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
      title={<Trans>Pending Change</Trans>}
      tooltip={
        <Trans>
          This is the pending change, which are change coins which you have sent
          to yourself, but have not been confirmed yet.
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
