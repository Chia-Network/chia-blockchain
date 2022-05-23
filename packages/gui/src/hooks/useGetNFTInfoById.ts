import React, { useMemo } from 'react';
import type { NFTInfo } from '@chia/api';
import { useLoadNFTInfoMutation } from '@chia/api-react';
import { launcherIdFromNFTId } from '../util/nfts';

export default function useGetNFTInfoById(
  nftId: string | undefined,
): NFTInfo | undefined {
  const [loadNFTInfo] = useLoadNFTInfoMutation();
  const nft = useMemo(async () => {
    if (!nftId) {
      return undefined;
    }

    const launcherId = launcherIdFromNFTId(nftId);

    if (!launcherId) {
      return undefined;
    }

    const { data, isLoading, error } = await loadNFTInfo({
      coinId: launcherId,
    });
    console.log('data:');
    console.log(data);
    console.log('isLoading:');
    console.log(isLoading);
    console.log('error:');
    console.log(error);

    const nft = data ? { ...data, id: nftId } : undefined;

    return nft;
  }, [nftId]);

  return nft;
}
