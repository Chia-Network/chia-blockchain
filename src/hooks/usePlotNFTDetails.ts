import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import seedrandom from 'seedrandom';
import { uniqueNamesGenerator, adjectives, colors, animals } from 'unique-names-generator';
import type PlotNFT from '../types/PlotNFT';
import type Plot from '../types/Plot';
import type PlotNFTState from '../constants/PlotNFTState';
import type { RootState } from '../modules/rootReducer';
import usePlots from './usePlots';

export default function usePlotNFTDetails(nft: PlotNFT): {
  isPending: boolean;
  state: PlotNFTState;
  walletId: number;
  isSynced: boolean;
  balance: number;
  humanName: string;
  plots?: Plot[];
} {
  const isWalletSynced = useSelector(
    (state: RootState) => state.wallet_state.status.synced,
  );

  const { plots } = usePlots();

  const details = useMemo(() => {
    const {
      pool_state: {
        p2_singleton_puzzle_hash,
      },
      pool_wallet_status: {
        current: {
          state,
        },
        target,
        wallet_id,
      },
      wallet_balance: {
        confirmed_wallet_balance,
      },
    } = nft;

    const poolContractPuzzleHash = `0x${p2_singleton_puzzle_hash}`;
    const isPending = !!target && target !== state;

    const generator = seedrandom(p2_singleton_puzzle_hash);
    const seed = generator.int32();

    const humanName = uniqueNamesGenerator({
        dictionaries: [colors, animals, adjectives], // colors can be omitted here as not used
        length: 2,
        seed,
        separator: ' ',
        style: 'capital',
      });

    return {
      isPending,
      state,
      walletId: wallet_id,
      isSynced: isWalletSynced,
      balance: confirmed_wallet_balance,
      canEdit: isWalletSynced && !isPending,
      humanName,
      plots: plots && plots.filter(plot => plot.pool_contract_puzzle_hash === poolContractPuzzleHash),
    };
  }, [nft, isWalletSynced, plots]);

  return details;
}
