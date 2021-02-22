import Big from 'big.js';
import TransactionType from '../constants/TransactionType';
import type Wallet from '../types/Wallet';

export default function computeStatistics(
  wallets: Wallet[],
): {
  totalChiaFarmed: Big;
  biggestHeight: number;
  biggestRewardHeight: number;
  poolCoins: Big;
  farmerCoins: Big;
  totalBlockRewards: Big;
  userTransactionFees: Big;
  blockRewards: Big;
} {
  let biggestHeight = 0;
  let biggestRewardHeight = 0;
  let poolCoins = Big(0);
  let farmerCoins = Big(0);

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
  const totalBlockRewards = Big(poolCoins).times(8).div(7);
  const userTransactionFees = Big(farmerCoins).minus(
    Big(totalBlockRewards).div(8),
  );
  const blockRewards = Big(poolCoins)
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
