import { useMemo } from 'react';
import type { Plot, PlotNFTExternal } from '@chia/api';
import usePlots from './usePlots';
import { useIsWalletSynced } from '@chia/wallets';
import usePlotNFTName from './usePlotNFTName';

export default function usePlotNFTExternalDetails(nft: PlotNFTExternal): {
  isSynced: boolean;
  humanName: string;
  plots?: Plot[];
  isSelfPooling: boolean;
} {
  const isWalletSynced = useIsWalletSynced()

  const { plots } = usePlots();
  const humanName = usePlotNFTName(nft);
  const details = useMemo(() => {
    const {
      poolState: {
        p2SingletonPuzzleHash,
        poolConfig: { poolUrl },
      },
    } = nft;

    const isSelfPooling = !poolUrl;
    const poolContractPuzzleHash = `0x${p2SingletonPuzzleHash}`;

    return {
      isSelfPooling,
      isSynced: isWalletSynced,
      humanName,
      plots:
        plots &&
        plots.filter(
          (plot) => plot.poolContractPuzzleHash === poolContractPuzzleHash,
        ),
    };
  }, [nft, isWalletSynced, plots, humanName]);

  return details;
}
