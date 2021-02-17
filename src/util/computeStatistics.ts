import TransactionType from '../constants/TransactionType';
import type Wallet from '../types/Wallet';

export default function computeStatistics(
  wallets: Wallet[],
): {
  totalChia: BigInt;
  biggestHeight: number;
  biggestRewardHeight: number;
  coinbaseRewards: BigInt;
  feesReward: BigInt;
} {
  let totalChia = BigInt(0);
  let biggestHeight = 0;
  let biggestRewardHeight = 0;
  let coinbaseRewards = BigInt(0);
  let feesReward = BigInt(0);

  wallets.forEach((wallet) => {
    if (!wallet) {
      return;
    }

    wallet.transactions.forEach((tx) => {
      const {
        additions,
        type,
        amount,
        confirmed_at_height: confirmedAtHeight,
      } = tx;
      if (additions.length === 0) {
        return;
      }

      const isFromReward = [
        TransactionType.COINBASE_REWARD,
        TransactionType.FEE_REWARD,
      ].includes(tx.type);

      totalChia += BigInt(amount);

      if (type === TransactionType.OUTGOING) {
        totalChia -= BigInt(amount);
      } else if (type === TransactionType.COINBASE_REWARD) {
        coinbaseRewards += BigInt(amount);
      } else if (type === TransactionType.FEE_REWARD) {
        feesReward += BigInt(amount);
      }

      if (confirmedAtHeight > biggestHeight) {
        biggestHeight = confirmedAtHeight;
      }

      if (isFromReward && confirmedAtHeight > biggestRewardHeight) {
        biggestRewardHeight = confirmedAtHeight;
      }
    });
  });

  return {
    totalChia,
    biggestHeight,
    biggestRewardHeight,
    coinbaseRewards,
    feesReward,
  };
}
