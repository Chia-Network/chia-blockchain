import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useGetWalletBalanceQuery } from '@chia/api-react';
import { FormatLargeNumber, mojoToChia } from '@chia/core';
import { useWallet } from '@chia/wallets';

export type OfferBuilderWalletBalanceProps = {
  walletId: number;
};

export default function OfferBuilderWalletBalance(
  props: OfferBuilderWalletBalanceProps,
) {
  const { walletId } = props;
  const { data: walletBalance, isLoading: isLoadingWalletBalance } =
    useGetWalletBalanceQuery({
      walletId,
    });

  const { unit, loading } = useWallet(walletId);

  const isLoading = isLoadingWalletBalance || loading;

  const xchBalance = useMemo(() => {
    if (walletBalance && 'confirmedWalletBalance' in walletBalance) {
      return mojoToChia(walletBalance.confirmedWalletBalance);
    }

    return undefined;
  }, [walletBalance?.confirmedWalletBalance]);

  if (!isLoading && xchBalance === undefined) {
    return null;
  }

  return (
    <Trans>
      Spendable Balance:{' '}
      {isLoading ? (
        'Loading...'
      ) : (
        <>
          <FormatLargeNumber value={xchBalance} />
          &nbsp;
          {unit?.toUpperCase()}
        </>
      )}
    </Trans>
  );
}
