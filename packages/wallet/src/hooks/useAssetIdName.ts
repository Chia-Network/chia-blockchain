import { useMemo } from 'react';
import { useGetCatListQuery, useGetWalletsQuery } from '@chia/api-react';
import { CATToken, Wallet } from '@chia/core';
import WalletType from '../constants/WalletType';

export type AssetIdMapEntry = {
  walletId: number;
  walletType: WalletType;
  isVerified: boolean;
  name: string;
  symbol?: string;
  displayName: string;
};

export default function useAssetIdName() {
  const { data: wallets, isLoading } = useGetWalletsQuery();
  const { data: catList = [], isLoading: isCatListLoading } = useGetCatListQuery();

  const { assetIdNameMapping, walletIdNameMapping } = useMemo(() => {
    const assetIdNameMapping = new Map<string, AssetIdMapEntry>();
    const walletIdNameMapping = new Map<number, AssetIdMapEntry>();

    if (isLoading || isCatListLoading) {
      return { assetIdNameMapping, walletIdNameMapping };
    }

    wallets.map((wallet: Wallet) => {
      const walletId: number = wallet.id;
      const walletType: WalletType = wallet.type;
      let assetId: string | undefined;
      let name: string | undefined;
      let symbol: string | undefined;
      let isVerified: boolean = false;

      if (walletType === WalletType.STANDARD_WALLET) {
        assetId = 'xch';
        name = 'Chia';
        symbol = 'XCH';
        isVerified = true;
      }
      else if (walletType === WalletType.CAT) {
        const lowercaseTail = wallet.meta.tail.toLowerCase();
        const cat = catList.find((cat: CATToken) => cat.assetId.toLowerCase() === lowercaseTail);

        assetId = lowercaseTail;
        name = wallet.name

        if (cat) {
          symbol = cat.symbol;
          isVerified = true;
        }
      }

      if (assetId && name) {
        const displayName = symbol ? symbol : name;
        const entry: AssetIdMapEntry = { walletId, walletType, name, symbol, displayName, isVerified };
        assetIdNameMapping.set(assetId, entry);
        walletIdNameMapping.set(walletId, entry);
      }
    });

    catList.map((cat: CATToken) => {
      if (assetIdNameMapping.has(cat.assetId)) {
        return;
      }

      const assetId = cat.assetId;
      const name = cat.name;
      const symbol = cat.symbol;
      const displayName = symbol ? symbol : name;
      const entry: AssetIdMapEntry = { walletId: 0, walletType: WalletType.CAT, name, symbol, displayName, isVerified: true };
      assetIdNameMapping.set(assetId, entry);
    });

    return { assetIdNameMapping, walletIdNameMapping } ;
  }, [catList, wallets, isCatListLoading, isLoading]);

  function lookupByAssetId(assetId: string): AssetIdMapEntry | undefined {
    return assetIdNameMapping.get(assetId.toLowerCase());
  }

  function lookupByWalletId(walletId: number | string): AssetIdMapEntry | undefined {
    return walletIdNameMapping.get(Number(walletId));
  }

  return { lookupByAssetId, lookupByWalletId };
}
