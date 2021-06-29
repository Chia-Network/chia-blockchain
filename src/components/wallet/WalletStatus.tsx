import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { State, StateIndicator } from '@chia/core';
import { Typography } from '@material-ui/core';
import type { RootState } from '../../modules/rootReducer';
import getWalletSyncingStatus from '../../util/getWalletSyncingStatus';
import SyncingStatus from '../../constants/SyncingStatus';


type Props = {
  variant?: string;
  indicator?: boolean;
  height?: boolean;
};

export default function WalletStatus(props: Props) {
  const { variant, height, indicator } = props;

  const walletState = useSelector(
    (state: RootState) => state.wallet_state,
  );

  const currentHeight = walletState?.status?.height;

  const syncingStatus = getWalletSyncingStatus(walletState);

  return (
    <Typography variant={variant}>
      {syncingStatus === SyncingStatus.NOT_SYNCED && (
        <StateIndicator state={State.WARNING} indicator={indicator}>
          <Trans>Not Synced</Trans>
          {height ? ` (${currentHeight})` : ''}
        </StateIndicator>
      )}
      {syncingStatus === SyncingStatus.SYNCED && (
        <StateIndicator state={State.SUCCESS} indicator={indicator}>
          <Trans>Synced</Trans>
          {height ? ` (${currentHeight})` : ''}
        </StateIndicator>
      )}
      {syncingStatus === SyncingStatus.SYNCING && (
        <StateIndicator state={State.WARNING} indicator={indicator}>
          <Trans>Syncing</Trans>
          {height ? ` (${currentHeight})` : ''}
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
