import React from 'react';
import { Trans } from '@lingui/macro';
import { useDispatch } from 'react-redux';
import { AlertDialog, ConfirmDialog, UnitFormat } from '@chia/core';
import type PlotNFT from '../types/PlotNFT';
import { pwAbsorbRewards } from '../modules/plotNFT';
import useOpenDialog from './useOpenDialog';
import usePlotNFTDetails from './usePlotNFTDetails';
import PlotNFTState from '../constants/PlotNFTState';

export default function useAbsorbRewards(nft: PlotNFT) {
  const openDialog = useOpenDialog();
  const dispatch = useDispatch();
  const { isPending, isSynced, walletId, state, balance } =
    usePlotNFTDetails(nft);

  async function handleAbsorbRewards(fee?: string) {
    if (!isSynced) {
      await openDialog(
        <AlertDialog>
          <Trans>Please wait for synchronization</Trans>
        </AlertDialog>,
      );
      return;
    }
    if (isPending) {
      await openDialog(
        <AlertDialog>
          <Trans>You are in pending state. Please wait for confirmation</Trans>
        </AlertDialog>,
      );
      return;
    }
    if (state !== PlotNFTState.SELF_POOLING) {
      await openDialog(
        <AlertDialog>
          <Trans>You are not self pooling</Trans>
        </AlertDialog>,
      );
      return;
    }

    const canAbsorbRewards = await openDialog<boolean>(
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

    if (canAbsorbRewards) {
      await dispatch(pwAbsorbRewards(walletId, fee));
    }
  }

  return handleAbsorbRewards;
}
