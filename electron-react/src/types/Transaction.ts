import type Coin from './Coin';
import type SpendBundle from './SpendBundle';

type Transaction = {
  confirmed_at_index: number,
  created_at_time: number,
  to_puzzle_hash: string,
  amount: number,
  fee_amount: number,
  incoming: boolean,
  confirmed: boolean,
  sent: number,
  spend_bundle?: SpendBundle,
  additions: Coin[],
  removals: Coin[],
  wallet_id: number,
};

export default Transaction;
