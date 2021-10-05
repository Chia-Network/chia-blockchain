import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import type { RootState } from '../modules/rootReducer';
import WalletType from '../constants/WalletType';

export default function useCATWallet(tail: string) {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  const wallet = useMemo(() => {
    return wallets?.find((item) => item.type === WalletType.CAT && item.colour === tail);
  }, [wallets, name]);

  return { wallet, loading: !wallets };
}
