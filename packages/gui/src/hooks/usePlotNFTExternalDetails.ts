import { useMemo } from 'react';
import type { Plot, PlotNFTExternal } from '@chia/api';
import { useIsWalletSynced } from '@chia/wallets';
import usePlotNFTName from './usePlotNFTName';

export default function usePlotNFTExternalDetails(nft: PlotNFTExternal): {
  isSynced: boolean;
  humanName: string;
  plots?: Plot[];
  isSelfPooling: boolean;
} {
  const isWalletSynced = useIsWalletSynced()

  const humanName = usePlotNFTName(nft);
  const details = useMemo(() => {
    const {
      poolState: {
        poolConfig: { poolUrl },
      },
    } = nft;

    const isSelfPooling = !poolUrl;

    return {
      isSelfPooling,
      isSynced: isWalletSynced,
      humanName,
    };
  }, [nft, isWalletSynced, humanName]);

  return details;
}
