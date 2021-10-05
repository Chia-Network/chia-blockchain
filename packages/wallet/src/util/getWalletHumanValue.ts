import type Wallet from '../types/Wallet';
import WalletType from '../constants/WalletType';
import { mojo_to_colouredcoin_string, mojo_to_chia_string } from './chia';

export default function getWalletHumanValue(wallet: Wallet, value: number): string {
  return wallet.type === WalletType.CAT
    ? mojo_to_colouredcoin_string(value)
    : mojo_to_chia_string(value);
}
