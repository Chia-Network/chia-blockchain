import { useCallback } from 'react';
import { useLocalStorage } from '@chia/core';

export default function useHiddenWallet(): {
  hide: (walletId: number) => void;
  show: (walletId: number) => void;
  isHidden: (walletId: number) => boolean;
  hidden: number[];
} {
  const [hiddenWalletIds, setHiddenWalletIds] = useLocalStorage<number[]>(
    'hiddenWallets',
    [],
  );

  const hide = useCallback((walletId: number) => {
    setHiddenWalletIds((items) => [...items, walletId]);
  }, [setHiddenWalletIds]);

  const show = useCallback((walletId: number) => {
    setHiddenWalletIds((items) => items.filter((id) => id !== walletId));
  }, [setHiddenWalletIds]);

  const isHidden = useCallback((walletId: number) => {
    return hiddenWalletIds.includes(walletId);
  }, [hiddenWalletIds]);

  return {
    hidden: hiddenWalletIds,
    hide,
    show,
    isHidden,
  };
}
