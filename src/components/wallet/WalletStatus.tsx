import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { State, StateTypography } from '@chia/core';
import type { RootState } from '../../modules/rootReducer';

type Props = {
  variant?: string;
};

export default function WalletStatus(props: Props) {
  const { variant } = props;

  const isWalletSyncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );
  const walletSyncingHeight = useSelector(
    (state: RootState) => state.wallet_state.status.height,
  );

  return (
    <StateTypography 
      variant={variant}
      state={isWalletSyncing && State.WARNING}
    >
      {isWalletSyncing 
        ? <Trans>Syncing. Height: {walletSyncingHeight}</Trans>
        : <Trans>Synced</Trans>
      }
    </StateTypography>
  );
}

WalletStatus.defaultProps = {
  variant: 'body1',
};