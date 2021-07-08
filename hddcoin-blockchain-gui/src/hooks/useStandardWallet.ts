import { useSelector } from 'react-redux';
import Wallet from '../types/Wallet';
import type { RootState } from '../modules/rootReducer';
import WalletType from '../constants/WalletType';

export default function useStandardWallet(): {
  loading: boolean;
  wallet?: Wallet;
  balance?: number;
} {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  const wallet = wallets?.find(
    (wallet) => wallet?.type === WalletType.STANDARD_WALLET,
  );

  const balance = wallet?.wallet_balance?.confirmed_wallet_balance;

  return {
    loading: !wallets,
    wallet,
    balance,
  };
}
