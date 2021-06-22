import { useSelector } from 'react-redux';
import Wallet from '../types/Wallet';
import type { RootState } from '../modules/rootReducer';
import WalletType from '../constants/WalletType';

export default function useStandardWallet(): {
  loading: boolean;
  wallet?: Wallet;
} {
  const wallets = useSelector(
    (state: RootState) => state.wallet_state.wallets,
  );

  const standardWallet = wallets?.find((wallet) => wallet?.type === WalletType.STANDARD_WALLET);

  return {
    loading: !wallets,
    wallet: standardWallet,
  };
}
