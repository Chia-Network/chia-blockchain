import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { AlertDialog } from '@chia/core';
import type Group from '../types/Group';
import type { RootState } from '../modules/rootReducer';
import useOpenDialog from './useOpenDialog';
import useGroupClaimRewards from './useGroupClaimRewards';

export default function usePoolJoin(group: Group) {
  const { state, balance } = group;

  const openDialog = useOpenDialog();
  const [claimRewards] = useGroupClaimRewards(group);

  const isWalletSyncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );

  const isPooling = state === 'FREE' || state === 'POOLING';

  async function handleJoin() {
    if (isWalletSyncing) {
      await openDialog(
        <AlertDialog>
          <Trans>Please wait for synchronization</Trans>
        </AlertDialog>,
      );
      return;
    }
    if (!isPooling) {
      await openDialog(
        <AlertDialog>
          <Trans>You are not pooling</Trans>
        </AlertDialog>,
      );
      return;
    }

    if (balance) {
      await claimRewards();
    }

    // TODO add rpc for pool join
  }

  return [handleJoin];
}
