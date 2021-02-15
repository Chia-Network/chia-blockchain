import type Transaction from './Transaction';
import type WalletType from '../constants/WalletType';

interface Wallet {
  id: number;
  name: string;
  type: WalletType;
  data: Object;
  balance_total: number;
  balance_pending: number;
  balance_spendable: number;
  balance_frozen: number;
  balance_change: number;
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
}

export default Wallet;
