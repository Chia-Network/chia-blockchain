import { store, walletApi } from '@chia/api-react';
import BigNumber from 'bignumber.js';

export default async function hasSpendableBalance(
  walletId: number,
  amount: BigNumber,
) {
  // Adding a cache subscription
  const resultPromise = store.dispatch(
    walletApi.endpoints.getWalletBalance.initiate({
      walletId,
    }),
  );

  const result = await resultPromise;

  // Removing the corresponding cache subscription
  resultPromise.unsubscribe();

  if (result.error) {
    throw result.error;
  }

  const walletBalance = result.data;
  if (!walletBalance || !('spendableBalance' in walletBalance)) {
    throw new Error('Wallet balance not found');
  }

  const spendableBalance = new BigNumber(walletBalance.spendableBalance);

  return spendableBalance.gte(amount);
}
