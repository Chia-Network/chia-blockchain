import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import type PlotNFTExternal from '../types/PlotNFTExternal';
import type Plot from '../types/Plot';
import type { RootState } from '../modules/rootReducer';
import usePlots from './usePlots';
import usePlotNFTName from './usePlotNFTName';

export default function usePlotNFTExternalDetails(nft: PlotNFTExternal): {
  isSynced: boolean;
  humanName: string;
  plots?: Plot[];
  isSelfPooling: boolean;
} {
  const isWalletSynced = useSelector(
    (state: RootState) => state.wallet_state.status.synced,
  );

  const { plots } = usePlots();
  const humanName = usePlotNFTName(nft);
  const details = useMemo(() => {
    const {
      pool_state: {
        p2_singleton_puzzle_hash,
        pool_config: { pool_url },
      },
    } = nft;

    const isSelfPooling = !pool_url;
    const poolContractPuzzleHash = `0x${p2_singleton_puzzle_hash}`;

    return {
      isSelfPooling,
      isSynced: isWalletSynced,
      humanName,
      plots:
        plots &&
        plots.filter(
          (plot) => plot.pool_contract_puzzle_hash === poolContractPuzzleHash,
        ),
    };
  }, [nft, isWalletSynced, plots, humanName]);

  return details;
}
