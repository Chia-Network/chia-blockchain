import { useMemo } from 'react';
import { WalletType, type Wallet } from '@chia/api';
import { orderBy } from 'lodash';
import { useGetWalletsQuery, useGetStrayCatsQuery, useGetCatListQuery, useAddCATTokenMutation } from '@chia/api-react';
import useHiddenWallet from './useHiddenWallet';

type ListItem = {
  type: 'WALLET' | 'STRAY_CAT' | 'CAT_LIST';
  walletType: WalletType;
  hidden: boolean;
  name: string;
  walletId?: number; // walletId or assetId
  assetId?: string;
};

function getWalletTypeOrder(item: ListItem) {
  switch (item.walletType) {
    case WalletType.STANDARD_WALLET:
      return 0;
    default:
      return 1;
  }
}

function getTypeOrder(item: ListItem) {
  switch (item.type) {
    case 'WALLET':
      return 0;
    case 'STRAY_CAT':
      return 1;
    default:
      return 3;
  }
}

export default function useWalletsList(): {
  list?: ListItem[];
  isLoading: boolean;
  hide: (walletId: number) => void;
  show: (id: number | string) => Promise<void>;
} {
  const { data: wallets, isLoading: isLoadingGetWallets } = useGetWalletsQuery();
  const { data: catList, isLoading: isLoadingGetCatList } = useGetCatListQuery();
  const { data: strayCats, isLoading: isLoadingGetStrayCats } = useGetStrayCatsQuery();
  const { hidden, isHidden, show, hide } = useHiddenWallet();
  const [addCATToken] = useAddCATTokenMutation();

  const isLoading = isLoadingGetWallets || isLoadingGetStrayCats || isLoadingGetCatList;

  const walletAssetIds = useMemo(() => {
    const ids = new Set<string>();
    if (wallets) {
      wallets.forEach((wallet) => {
        if (wallet.type === WalletType.CAT) {
          ids.add(wallet.meta?.assetId);
        }
      });
    }
    return ids;
  }, [wallets]);

  const knownCatAssetIds = useMemo(() => {
    const ids = new Set<string>();
    if (catList) {
      catList.forEach((cat) => ids.add(cat.assetId));
    }

    return ids;
  }, [catList]);

  const strayCatAssetIds = useMemo(() => {
    const ids = new Set<string>();
    if (strayCats) {
      strayCats.forEach((cat) => ids.add(cat.assetId));
    }
    return ids;
  }, [strayCats]);

  function hasCatAssignedWallet(assetId: string) {
    return knownCatAssetIds.has(assetId) || strayCatAssetIds.has(assetId);
  }

  function hasCatAssignedWallet(assetId: string) {
    return walletAssetIds.has(assetId);
  }

  const list = useMemo(() => {
    if (isLoading) {
      return undefined;
    }

    // hidden by default because they are not known
    const nonAddedKnownCats = catList?.filter(
      (cat) => !hasCatAssignedWallet(cat.assetId),
    );
    // hidden by default
    const nonAddedStrayCats = strayCats?.filter(
      (strayCat) => !hasCatAssignedWallet(strayCat.assetId),
    );

    const tokens = [
      ...wallets.map((wallet) => ({
        type: 'WALLET',
        walletType: wallet.type,
        hidden: isHidden(wallet.id),
        walletId: wallet.id,
        assetId: wallet.meta?.assetId,
        name: wallet.name,
      })),
      ...nonAddedKnownCats.map((cat) => ({
        type: 'CAT_LIST',
        walletType: WalletType.CAT,
        hidden: true,
        assetId: cat.assetId,
        name: cat.name ?? cat.assetId,
      })),
      ...nonAddedStrayCats.map((strayCat) => ({
        type: 'STRAY_CAT',
        walletType: WalletType.CAT,
        hidden: true,
        assetId: strayCat.assetId,
        name: strayCat.name ?? strayCat.assetId,
      })),
    ];

    return orderBy(tokens, [getWalletTypeOrder, getTypeOrder, 'name'], ['asc', 'asc', 'asc']);
  }, [isLoading, wallets, catList, strayCats, hidden]);


  async function handleShow(id: number | string) {
    if (typeof id === 'number') {
      show(id);
      return;
    }

    if (typeof id === 'string') {
      // assign wallet for CAT

      const cat = catList.find((cat) => cat.assetId === id);
      if (cat) {
        await addCATToken({
          name: cat.name,
          assetId: cat.assetId,
          fee: '0',
        }).unwrap();
      }

      // assign stray cat
      const strayCat = strayCats.find((cat) => cat.assetId === id);
      if (strayCat) {
        await addCATToken({
          name: strayCat.name,
          assetId: strayCat.assetId,
          fee: '0',
        }).unwrap();
      }
    }
  }

  return {
    list,
    hide,
    show: handleShow,
    isLoading,
  };
}
