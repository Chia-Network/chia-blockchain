import TransactionType from '../constants/TransactionType';
import type Wallet from '../types/Wallet';

export default function computeStatistics(
  wallets: Wallet[],
): {
  totalChia: BigInt;
  biggestHeight: number;
  biggestRewardHeight: number;
  poolCoins: BigInt;
  farmerCoins: BigInt;
  totalBlockRewards: BigInt;
  userTransactionFees: BigInt;
  blockRewards: BigInt;
} {
  let totalChia = BigInt(0);
  let biggestHeight = 0;
  let biggestRewardHeight = 0;
  let poolCoins = BigInt(0);
  let farmerCoins = BigInt(0);

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
        poolCoins += BigInt(amount);
      } else if (type === TransactionType.FEE_REWARD) {
        farmerCoins += BigInt(amount);
      }

      if (confirmedAtHeight > biggestHeight) {
        biggestHeight = confirmedAtHeight;
      }

      if (isFromReward && confirmedAtHeight > biggestRewardHeight) {
        biggestRewardHeight = confirmedAtHeight;
      }
    });
  });

  const totalBlockRewards = poolCoins * BigInt(8 / 7);
  const userTransactionFees = farmerCoins - BigInt(1 / 8) * totalBlockRewards;
  const blockRewards = poolCoins + farmerCoins - userTransactionFees;

  return {
    totalChia,
    biggestHeight,
    biggestRewardHeight,
    poolCoins,
    farmerCoins,
    totalBlockRewards,
    userTransactionFees,
    blockRewards,
  };
}
