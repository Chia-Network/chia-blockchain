import { useMemo } from 'react';
import type { PlotNFT, Plot } from '@chia/api';
import { useIsWalletSynced } from '@chia/wallets';
import PlotNFTState from '../constants/PlotNFTState';
import usePlots from './usePlots';
import usePlotNFTName from './usePlotNFTName';

export default function usePlotNFTDetails(nft: PlotNFT): {
  isPending: boolean;
  state: PlotNFTState;
  walletId: number;
  isSynced: boolean;
  balance?: number;
  humanName: string;
  plots?: Plot[];
  canEdit: boolean;
  isSelfPooling: boolean;
} {
  const isWalletSynced = useIsWalletSynced();

  const { plots } = usePlots();
  const humanName = usePlotNFTName(nft);

  const details = useMemo(() => {
    const {
      poolState: { p2SingletonPuzzleHash },
      poolWalletStatus: {
        current: { state },
        target,
        walletId,
      },
      walletBalance: { confirmedWalletBalance },
    } = nft;

    const poolContractPuzzleHash = `0x${p2SingletonPuzzleHash}`;
    const isPending = !!target && target.state !== state;
    const isLeavingPool = state === PlotNFTState.LEAVING_POOL;
    const isSelfPooling = state === PlotNFTState.SELF_POOLING;

    return {
      isPending,
      state,
      walletId,
      isSynced: isWalletSynced,
      balance: confirmedWalletBalance,
      canEdit: isWalletSynced && (!isPending || isLeavingPool),
      humanName,
      isSelfPooling,
      plots:
        plots &&
        plots.filter(
          (plot) => plot.poolContractPuzzleHash === poolContractPuzzleHash,
        ),
    };
  }, [nft, isWalletSynced, plots, humanName]);

  return details;
}
