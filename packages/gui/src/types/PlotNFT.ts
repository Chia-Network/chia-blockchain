import type PoolState from './PoolState';
import type PoolWalletStatus from './PoolWalletStatus';
import type WalletBalance from './WalletBalance';

type PlotNFT = {
  pool_state: PoolState;
  wallet_balance: WalletBalance;
  pool_wallet_status: PoolWalletStatus;
};

export default PlotNFT;
