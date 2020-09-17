import type SpendBundle from '../types/SpendBundle';
import type Coin from '../types/Coin';
import type Transaction from '../types/Transaction';

export default function createTransaction(
  confirmed_at_index: number,
  created_at_time: number,
  to_address: string,
  amount: number,
  fee_amount: number,
  incoming: boolean,
  confirmed: boolean,
  sent: number,
  spend_bundle: SpendBundle,
  additions: Coin[],
  removals: Coin[],
  wallet_id: number,
): Transaction {
  return {
    confirmed_at_index,
    created_at_time,
    to_address,
    amount,
    fee_amount,
    incoming,
    confirmed,
    sent,
    spend_bundle,
    additions,
    removals,
    wallet_id
  };
}
