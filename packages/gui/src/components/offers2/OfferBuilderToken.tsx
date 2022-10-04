import React from 'react';
import { Trans } from '@lingui/macro';
import { Grid } from '@mui/material';
import type { Wallet } from '@chia/api';
import { useGetWalletsQuery } from '@chia/api-react';
import { useWatch } from 'react-hook-form';
import OfferBuilderValue from './OfferBuilderValue';
import OfferBuilderWalletAmount from './OfferBuilderWalletAmount';

export type OfferBuilderTokenProps = {
  name: string;
  onRemove?: () => void;
  usedAssets?: string[];
  hideBalance?: boolean;
};

export default function OfferBuilderToken(props: OfferBuilderTokenProps) {
  const { name, onRemove, usedAssets, hideBalance } = props;

  const assetIdFieldName = `${name}.assetId`;
  const assetId = useWatch({
    name: assetIdFieldName,
  });

  const { data: wallets } = useGetWalletsQuery();
  const wallet = wallets?.find(
    (wallet: Wallet) => wallet.meta?.assetId?.toLowerCase() === assetId,
  );

  return (
    <Grid spacing={3} container>
      <Grid xs={12} md={5} item>
        <OfferBuilderWalletAmount
          name={`${name}.amount`}
          walletId={wallet?.id}
          label={<Trans>Amount</Trans>}
          showAmountInMojos={false}
          hideBalance={hideBalance}
        />
      </Grid>
      <Grid xs={12} md={7} item>
        <OfferBuilderValue
          name={assetIdFieldName}
          type="token"
          label={<Trans>Asset Type</Trans>}
          usedAssets={usedAssets}
          onRemove={onRemove}
        />
      </Grid>
    </Grid>
  );
}
