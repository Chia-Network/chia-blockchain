import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { AlertDialog } from '@chia/core';
import type PoolGroup from '../types/PoolGroup';
import type { RootState } from '../modules/rootReducer';
import useOpenDialog from './useOpenDialog';
import usePoolClaimRewards from './usePoolClaimRewards';

export default function usePoolJoin(pool: PoolGroup) {
  const { 
    state,
    balance,
  } = pool;

  const openDialog = useOpenDialog();
  const [claimRewards] = usePoolClaimRewards(pool);

  const isWalletSyncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );

  const isPooling = state === 'FREE' || state === 'POOLING';

  async function handleJoin() {
    if (isWalletSyncing) {
      await openDialog((
        <AlertDialog>
          <Trans>
            Please wait for synchronization
          </Trans>
        </AlertDialog>
      ));
      return;
    } else if (!isPooling) {
      await openDialog((
        <AlertDialog>
          <Trans>
            You are not pooling
          </Trans>
        </AlertDialog>
      ));
      return;
    }

    if (balance) {
      await claimRewards();
    }

    // TODO add rpc for pool join
  }

  return [handleJoin];
}
