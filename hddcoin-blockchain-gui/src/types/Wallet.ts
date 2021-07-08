import type Transaction from './Transaction';
import type WalletType from '../constants/WalletType';
import WalletBalance from './WalletBalance';

interface Wallet {
  id: number;
  name: string;
  type: WalletType;
  data: Object;
  transactions: Transaction[];
  address: string;
  colour: string;
  mydid: string;
  didcoin: string;
  backup_dids: string[];
  dids_num_req: number;
  did_attest: string;
  sending_transaction: boolean;
  send_transaction_result?: string | null;
  wallet_balance?: WalletBalance;
}

export default Wallet;
