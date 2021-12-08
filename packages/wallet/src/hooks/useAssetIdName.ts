import { useMemo } from 'react';
import { useGetCatListQuery, useGetWalletsQuery } from '@chia/api-react';
import { CATToken, Wallet } from '@chia/core';
import WalletType from '../constants/WalletType';

type AssetIdMapEntry = {
  walletId: number;
  walletType: WalletType;
  name: string;
  symbol?: string;
  displayName: string;
};

export default function useAssetIdName() {
  const { data: wallets, isLoading } = useGetWalletsQuery();
  const { data: catList = [], isLoading: isCatListLoading } = useGetCatListQuery();

  const assetIdNameMapping = useMemo(() => {
    const mapping = new Map<string, AssetIdMapEntry>();

    if (isLoading || isCatListLoading) {
      return mapping;
    }

    wallets.map((wallet: Wallet) => {
      const walletId: number = wallet.id;
      const walletType: WalletType = wallet.type;
      let assetId: string | undefined;
      let name: string | undefined;
      let symbol: string | undefined;

      if (walletType === WalletType.STANDARD_WALLET) {
        assetId = 'xch';
        name = 'Chia';
        symbol = 'XCH';
      }
      else if (walletType === WalletType.CAT) {
        const lowercaseTail = wallet.meta.tail.toLowerCase();
        const cat = catList.find((cat: CATToken) => cat.assetId.toLowerCase() === lowercaseTail);

        assetId = lowercaseTail;
        name = wallet.name

        if (cat) {
          symbol = cat.symbol;
        }
      }

      if (assetId && name) {
        const displayName = symbol ? symbol : name;
        mapping.set(assetId, { walletId, walletType, name, symbol, displayName });
      }
    });

    return mapping;
  }, [catList, wallets, isCatListLoading, isLoading]);

  function lookupAssetId(assetId: string): AssetIdMapEntry | undefined {
    return assetIdNameMapping.get(assetId.toLowerCase());
  }

  return lookupAssetId;
}
