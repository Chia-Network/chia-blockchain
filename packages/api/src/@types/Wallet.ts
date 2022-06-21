import type Transaction from './Transaction';
import type WalletType from '../constants/WalletType';
import WalletBalance from './WalletBalance';

interface Wallet {
  id: number;
  name: string;
  type: WalletType;
  data: unknown;
  transactions: Transaction[];
  address: string;
  colour: string;
  mydid: string;
  didcoin: string;
  backup_dids: string[];
  dids_num_req: number;
  did_rec_puzhash: string;
  did_rec_pubkey: string;
  sending_transaction: boolean;
  send_transaction_result?: string | null;
  wallet_balance?: WalletBalance;
}

export default Wallet;
