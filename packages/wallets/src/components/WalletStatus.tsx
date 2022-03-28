import React from 'react';
import { Trans } from '@lingui/macro';
import { Loading, State, StateIndicator } from '@chia/core';
import { useGetSyncStatusQuery } from '@chia/api-react';
import { Typography } from '@mui/material';
import getWalletSyncingStatus from '../utils/getWalletSyncingStatus';
import { SyncingStatus } from '@chia/api';
import WalletStatusHeight from './WalletStatusHeight';

type Props = {
  variant?: string;
  indicator?: boolean;
  height?: boolean;
};

export default function WalletStatus(props: Props) {
  const { variant, height, indicator } = props;
  const { data: walletState, isLoading } = useGetSyncStatusQuery({}, {
    pollingInterval: 10000,
  });

  if (isLoading || !walletState) {
    return (
      <Loading />
    );
  }

  const syncingStatus = getWalletSyncingStatus(walletState);

  return (
    <Typography component='div' variant={variant}>
      {syncingStatus === SyncingStatus.NOT_SYNCED && (
        <StateIndicator state={State.WARNING} indicator={indicator}>
          <Trans>Not Synced</Trans> {height && <WalletStatusHeight />}
        </StateIndicator>
      )}
      {syncingStatus === SyncingStatus.SYNCED && (
        <StateIndicator state={State.SUCCESS} indicator={indicator}>
          <Trans>Synced</Trans> {height && <WalletStatusHeight />}
        </StateIndicator>
      )}
      {syncingStatus === SyncingStatus.SYNCING && (
        <StateIndicator state={State.WARNING} indicator={indicator}>
          <Trans>Syncing</Trans> {height && <WalletStatusHeight />}
        </StateIndicator>
      )}
    </Typography>
  );
}

WalletStatus.defaultProps = {
  variant: 'body1',
  indicator: false,
  height: false,
};
