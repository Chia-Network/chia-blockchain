import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { State, StateTypography } from '@chia/core';
import type { RootState } from '../../modules/rootReducer';
import getWalletSyncingStatus from '../../util/getWalletSyncingStatus';
import SyncingStatus from '../../constants/SyncingStatus';


type Props = {
  variant?: string;
};

export default function WalletStatus(props: Props) {
  const { variant } = props;

  const walletState = useSelector(
    (state: RootState) => state.wallet_state,
  );

  const walletSyncingHeight = useSelector(
    (state: RootState) => state.wallet_state.status.height,
  );

  const syncingStatus = getWalletSyncingStatus(walletState);
  const isSynced = syncingStatus === SyncingStatus.SYNCED;

  return (
    <StateTypography 
      variant={variant}
      state={!isSynced && State.WARNING}
    >
      {syncingStatus === SyncingStatus.NOT_SYNCED && (
        <Trans>Not Synced</Trans>
      )}
      {syncingStatus === SyncingStatus.SYNCED && (
        <Trans>Synced</Trans>
      )}
      {syncingStatus === SyncingStatus.SYNCING && (
        <Trans>Syncing. Height: {walletSyncingHeight}</Trans>
      )}
    </StateTypography>
  );
}

WalletStatus.defaultProps = {
  variant: 'body1',
};