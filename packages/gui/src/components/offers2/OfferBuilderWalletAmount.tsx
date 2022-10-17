import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { useWallet } from '@chia/wallets';
import OfferBuilderValue from './OfferBuilderValue';
import OfferBuilderWalletBalance from './OfferBuilderWalletBalance';

export type OfferBuilderWalletAmountProps = {
  name: string;
  walletId: number;
  label?: ReactNode;
  onRemove?: () => void;
  showAmountInMojos?: boolean;
  hideBalance?: boolean;
};

export default function OfferBuilderWalletAmount(
  props: OfferBuilderWalletAmountProps,
) {
  const {
    walletId,
    name,
    onRemove,
    showAmountInMojos,
    hideBalance = false,
    label = <Trans>Amount</Trans>,
  } = props;

  const { unit = '' } = useWallet(walletId);

  return (
    <OfferBuilderValue
      name={name}
      label={label}
      type="amount"
      symbol={unit}
      showAmountInMojos={showAmountInMojos}
      caption={
        walletId !== undefined &&
        !hideBalance && <OfferBuilderWalletBalance walletId={walletId} />
      }
      onRemove={onRemove}
    />
  );
}
