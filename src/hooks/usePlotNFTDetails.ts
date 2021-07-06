import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import type PlotNFT from '../types/PlotNFT';
import type Plot from '../types/Plot';
import PlotNFTState from '../constants/PlotNFTState';
import type { RootState } from '../modules/rootReducer';
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
  const isWalletSynced = useSelector(
    (state: RootState) => state.wallet_state.status.synced,
  );

  const { plots } = usePlots();
  const humanName = usePlotNFTName(nft);

  const details = useMemo(() => {
    const {
      pool_state: { p2_singleton_puzzle_hash },
      pool_wallet_status: {
        current: { state },
        target,
        wallet_id,
      },
      wallet_balance: { confirmed_wallet_balance },
    } = nft;

    const poolContractPuzzleHash = `0x${p2_singleton_puzzle_hash}`;
    const isPending = !!target && target.state !== state;
    const isLeavingPool = state === PlotNFTState.LEAVING_POOL;
    const isSelfPooling = state === PlotNFTState.SELF_POOLING;

    return {
      isPending,
      state,
      walletId: wallet_id,
      isSynced: isWalletSynced,
      balance: confirmed_wallet_balance,
      canEdit: isWalletSynced && (!isPending || isLeavingPool),
      humanName,
      isSelfPooling,
      plots:
        plots &&
        plots.filter(
          (plot) => plot.pool_contract_puzzle_hash === poolContractPuzzleHash,
        ),
    };
  }, [nft, isWalletSynced, plots, humanName]);

  return details;
}
