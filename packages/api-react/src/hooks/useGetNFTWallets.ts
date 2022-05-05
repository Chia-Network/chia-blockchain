import { useMemo } from 'react';
import { useGetWalletsQuery } from '../services';
import { Wallet, WalletType } from '@chia/api';

export default function useGetNFTWallets() {
  const { data, isLoading } = useGetWalletsQuery();
  const nftWallets = useMemo(() => {
    if (!data || isLoading) {
      return [];
    }

    return data.filter((wallet: Wallet) => wallet.type === WalletType.NFT);
  }, [data]);

  return { wallets: nftWallets, isLoading };
}
