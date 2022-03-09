import BigNumber from 'bignumber.js';
import TransactionType from '../constants/TransactionType';
import type Wallet from '../types/Wallet';

// deprecated
export default function computeStatistics(wallets: Wallet[]): {
  totalChiaFarmed: BigNumber;
  biggestHeight: number;
  biggestRewardHeight: number;
  poolCoins: BigNumber;
  farmerCoins: BigNumber;
  totalBlockRewards: BigNumber;
  userTransactionFees: BigNumber;
  blockRewards: BigNumber;
} {
  let biggestHeight = 0;
  let biggestRewardHeight = 0;
  let poolCoins = new BigNumber(0);
  let farmerCoins = new BigNumber(0);

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

      if (type === TransactionType.COINBASE_REWARD) {
        poolCoins = poolCoins.plus(amount);
      } else if (type === TransactionType.FEE_REWARD) {
        farmerCoins = farmerCoins.plus(amount);
      }

      if (confirmedAtHeight > biggestHeight) {
        biggestHeight = confirmedAtHeight;
      }

      if (isFromReward && confirmedAtHeight > biggestRewardHeight) {
        biggestRewardHeight = confirmedAtHeight;
      }
    });
  });

  const totalChiaFarmed = poolCoins.plus(farmerCoins);
  const totalBlockRewards = new BigNumber(poolCoins).times(7).div(8);
  const userTransactionFees = new BigNumber(farmerCoins).minus(
    new BigNumber(totalBlockRewards).div(8),
  );
  const blockRewards = new BigNumber(poolCoins)
    .plus(farmerCoins)
    .minus(userTransactionFees);

  return {
    totalChiaFarmed,
    biggestHeight,
    biggestRewardHeight,
    poolCoins,
    farmerCoins,
    totalBlockRewards,
    userTransactionFees,
    blockRewards,
  };
}
