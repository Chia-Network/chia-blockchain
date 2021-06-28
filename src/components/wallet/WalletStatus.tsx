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
};

export default function WalletStatus(props: Props) {
  const { variant, indicator } = props;

  const walletState = useSelector(
    (state: RootState) => state.wallet_state,
  );

  const syncingStatus = getWalletSyncingStatus(walletState);

  return (
    <Typography 
      variant={variant}
    >
      {syncingStatus === SyncingStatus.NOT_SYNCED && (
        <StateIndicator state={State.WARNING} indicator={indicator}>
          <Trans>Not Synced</Trans>
        </StateIndicator>
      )}
      {syncingStatus === SyncingStatus.SYNCED && (
        <StateIndicator state={State.SUCCESS} indicator={indicator}>
          <Trans>Synced</Trans>
        </StateIndicator>
      )}
      {syncingStatus === SyncingStatus.SYNCING && (
        <StateIndicator state={State.WARNING} indicator={indicator}>
          <Trans>Syncing</Trans>
        </StateIndicator>
      )}
    </Typography>
  );
}

WalletStatus.defaultProps = {
  variant: 'body1',
  indicator: false,
};
