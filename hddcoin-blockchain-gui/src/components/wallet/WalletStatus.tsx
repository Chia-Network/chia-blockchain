import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { State, StateIndicator } from '@hddcoin/core';
import { Typography } from '@material-ui/core';
import type { RootState } from '../../modules/rootReducer';
import getWalletSyncingStatus from '../../util/getWalletSyncingStatus';
import SyncingStatus from '../../constants/SyncingStatus';
import WalletStatusHeight from './WalletStatusHeight';

type Props = {
  variant?: string;
  indicator?: boolean;
  height?: boolean;
};

export default function WalletStatus(props: Props) {
  const { variant, height, indicator } = props;

  const walletState = useSelector((state: RootState) => state.wallet_state);

  const syncingStatus = getWalletSyncingStatus(walletState);

  return (
    <Typography variant={variant}>
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
