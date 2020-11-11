import TransactionType from '../constants/TransactionType';
import type Wallet from '../types/Wallet';
import { big_int_to_array, arr_to_hex, sha256 } from './utils';

export default async function computeStatistics(
  wallets: Wallet[],
): Promise<{
  totalChia: BigInt;
  biggestHeight: number;
  coinbaseRewards: BigInt;
  feesReward: BigInt;
}> {
  let totalChia = BigInt(0);
  let biggestHeight = 0;
  let coinbaseRewards = BigInt(0);
  let feesReward = BigInt(0);

  for (const wallet of wallets) {
    if (!wallet) {
      continue;
    }

    for (const tx of wallet.transactions) {
      if (tx.additions.length === 0) {
        continue;
      }

      // Height here is filled into the whole 256 bits (32 bytes) of the parent
      const hexHeight = arr_to_hex(
        big_int_to_array(BigInt(tx.confirmed_at_index), 32),
      );
      // Height is a 32 bit int so hashing it requires serializing it to 4 bytes
      const hexHeightHashBytes = await sha256(
        big_int_to_array(BigInt(tx.confirmed_at_index), 4),
      );
      const hexHeightDoubleHashBytes = await sha256(hexHeightHashBytes);
      const hexHeightDoubleHash = arr_to_hex(hexHeightDoubleHashBytes);

      if (
        hexHeight === tx.additions[0].parent_coin_info ||
        hexHeight === tx.additions[0].parent_coin_info.slice(2) ||
        hexHeightDoubleHash === tx.additions[0].parent_coin_info ||
        hexHeightDoubleHash === tx.additions[0].parent_coin_info.slice(2)
      ) {
        totalChia += BigInt(tx.amount);

        switch (tx.type) {
          case TransactionType.COINBASE_REWARD:
            coinbaseRewards += BigInt(tx.amount);
            break;
          case TransactionType.FEE_REWARD:
            feesReward += BigInt(tx.amount);
            break;
        }

        if (tx.confirmed_at_index > biggestHeight) {
          biggestHeight = tx.confirmed_at_index;
        }
      }
    }
  }

  return {
    totalChia,
    biggestHeight,
    coinbaseRewards,
    feesReward,
  };
}
