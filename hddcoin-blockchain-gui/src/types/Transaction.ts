import type Coin from './Coin';
import type SpendBundle from './SpendBundle';
import type TransactionType from '../constants/TransactionType';

type Transaction = {
  confirmed_at_height: number;
  created_at_time: number;
  to_address: string;
  to_puzzle_hash?: string;
  amount: number;
  sent: number;
  fee_amount: number;
  incoming: boolean;
  confirmed: boolean;
  spend_bundle?: SpendBundle;
  additions: Coin[];
  removals: Coin[];
  wallet_id: number;
  trade_id?: number;
  name?: string;
  sent_to?: string[];
  type: TransactionType;
};

export default Transaction;
