import TransactionType from '../constants/TransactionType';
import type Wallet from '../types/Wallet';

export default function computeStatistics(
  wallets: Wallet[],
): {
  totalChia: BigInt;
  biggestHeight: number;
  coinbaseRewards: BigInt;
  feesReward: BigInt;
} {
  let totalChia = BigInt(0);
  let biggestHeight = 0;
  let coinbaseRewards = BigInt(0);
  let feesReward = BigInt(0);

  wallets.forEach((wallet) => {
    if (!wallet) {
      return;
    }

    wallet.transactions.forEach((tx) => {
      if (tx.additions.length === 0) {
        return;
      }

      totalChia += BigInt(tx.amount);

      if (tx.type === TransactionType.OUTGOING) {
        totalChia -= BigInt(tx.amount);
      } else if (tx.type === TransactionType.COINBASE_REWARD) {
        coinbaseRewards += BigInt(tx.amount);
      } else if (tx.type === TransactionType.FEE_REWARD) {
        feesReward += BigInt(tx.amount);
      }

      if (tx.confirmed_at_index > biggestHeight) {
        biggestHeight = tx.confirmed_at_index;
      }
    });
  });

  return {
    totalChia,
    biggestHeight,
    coinbaseRewards,
    feesReward,
  };
}
