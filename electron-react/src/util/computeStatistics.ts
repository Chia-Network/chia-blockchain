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

  await Promise.all(
    wallets.map(async (wallet) => {
      if (!wallet) {
        return;
      }

      await Promise.all(
        wallet.transactions.map(async (tx) => {
          if (tx.additions.length === 0) {
            return;
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

            if (tx.type === TransactionType.COINBASE_REWARD) {
              coinbaseRewards += BigInt(tx.amount);
            } else if (tx.type === TransactionType.FEE_REWARD) {
              feesReward += BigInt(tx.amount);
            }

            if (tx.confirmed_at_index > biggestHeight) {
              biggestHeight = tx.confirmed_at_index;
            }
          }
        }),
      );
    }),
  );

  return {
    totalChia,
    biggestHeight,
    coinbaseRewards,
    feesReward,
  };
}
