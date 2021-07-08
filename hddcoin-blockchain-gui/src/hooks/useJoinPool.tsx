import React from 'react';
import { Trans } from '@lingui/macro';
import { useDispatch } from 'react-redux';
import { AlertDialog } from '@hddcoin/core';
import type PlotNFT from '../types/PlotNFT';
import { pwJoinPool } from '../modules/plotNFT';
import useOpenDialog from './useOpenDialog';
import useAbsorbRewards from './useAbsorbRewards';
import usePlotNFTDetails from './usePlotNFTDetails';
import PlotNFTState from '../constants/PlotNFTState';

export default function usePoolJoin(nft: PlotNFT) {
  const dispatch = useDispatch();
  const openDialog = useOpenDialog();
  const absorbRewards = useAbsorbRewards(nft);
  const { isPending, isSynced, walletId, balance, state } =
    usePlotNFTDetails(nft);

  async function handleJoin(
    poolUrl: string,
    relativeLockHeight: number,
    targetPuzzlehash?: string,
  ) {
    if (!isSynced) {
      await openDialog(
        <AlertDialog>
          <Trans>Please wait for wallet synchronization</Trans>
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

    if (balance && state === PlotNFTState.SELF_POOLING) {
      await absorbRewards(walletId);
    }

    await dispatch(
      pwJoinPool(walletId, poolUrl, relativeLockHeight, targetPuzzlehash),
    );
  }

  return handleJoin;
}
