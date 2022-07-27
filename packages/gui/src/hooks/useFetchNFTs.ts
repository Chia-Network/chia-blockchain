import { useMemo } from 'react';
import type { NFTInfo } from '@chia/api';
import { useGetNFTsQuery } from '@chia/api-react';

type UseFetchNFTsResult = {
  nfts: NFTInfo[];
  isLoading: boolean;
};

export default function useFetchNFTs(walletIds: number[]): UseFetchNFTsResult {
  const {
    data,
    isLoading,
  }: { data: { [walletId: number]: NFTInfo[] }; isLoading: boolean } =
    useGetNFTsQuery({ walletIds });
  const nfts = useMemo(() => {
    // Convert [ { <wallet_id>: IncompleteNFTInfo[] }, { <wallet_id>: IncompleteNFTInfo[] } ] to NFTInfo[]
    return Object.entries(data ?? []).flatMap(([walletId, nfts]) => {
      return nfts.map((nft) => ({
        ...nft,
        walletId: Number(walletId), // Add in the source wallet id
      }));
    });
  }, [data, isLoading]);

  return { isLoading, nfts };
}
