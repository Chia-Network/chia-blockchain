import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { AlertDialog, ConfirmDialog, Flex, UnitFormat } from '@chia/core';
import type Group from '../types/Group';
import type { RootState } from '../modules/rootReducer';
import useOpenDialog from './useOpenDialog';

export default function useGroupClaimRewards(group: Group) {
  const { state, balance, address } = group;

  const openDialog = useOpenDialog();

  const isWalletSyncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );

  const isPooling = state === 'FREE' || state === 'POOLING';

  async function handleClaimRewards() {
    if (isWalletSyncing) {
      await openDialog(
        <AlertDialog>
          <Trans>Please wait for synchronization</Trans>
        </AlertDialog>,
      );
      return;
    } if (!isPooling) {
      await openDialog(
        <AlertDialog>
          <Trans>You are not pooling</Trans>
        </AlertDialog>,
      );
      return;
    }

    const canClaimRewards = await openDialog(
      <ConfirmDialog
        title={<Trans>Please Confirm</Trans>}
        confirmTitle={<Trans>Confirm</Trans>}
        confirmColor="primary"
      >
        <Trans>
          You will recieve <UnitFormat value={balance} display="inline" /> to{' '}
          {address}
        </Trans>
      </ConfirmDialog>,
    );

    if (canClaimRewards) {
      // TODO add claim functionality here
    }
  }

  return [handleClaimRewards];
}
