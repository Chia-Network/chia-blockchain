import React from 'react';
import { useHistory } from 'react-router';
import { Trans } from '@lingui/macro';
import { AlertDialog } from '@chia/core';
import type PlotNFT from '../../types/PlotNFT';
import usePlotNFTDetails from '../../hooks/usePlotNFTDetails';
import useOpenDialog from '../../hooks/useOpenDialog';

type Props = {
  nft: PlotNFT;
  children: (data: {
    join: () => Promise<void>;
    disabled: boolean;
  }) => JSX.Element;
};

export default function PoolJoin(props: Props) {
  const {
    children,
    nft,
    nft: {
      pool_state: { p2_singleton_puzzle_hash },
    },
  } = props;
  const { canEdit, balance, isSelfPooling } = usePlotNFTDetails(nft);
  const history = useHistory();
  const openDialog = useOpenDialog();

  async function handleJoinPool() {
    if (isSelfPooling && balance) {
      await openDialog(
        <AlertDialog>
          <Trans>You need to claim your rewards first</Trans>
        </AlertDialog>,
      );
      return;
    }

    history.push(`/dashboard/pool/${p2_singleton_puzzle_hash}/change-pool`);
  }

  return children({
    join: handleJoinPool,
    disabled: !canEdit,
  });
}
