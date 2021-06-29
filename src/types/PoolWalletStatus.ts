import PlotNFTState from '../constants/PlotNFTState';

type PoolWalletStatus = {
  current: {
    owner_pubkey: string;
    pool_url: string;
    relative_lock_height: number;
    state: PlotNFTState;
    target_puzzle_hash: string;
    version: number;
  };
  current_inner: string;
  launcher_coin: {
    amount: number;
    parent_coin_info: string;
    puzzle_hash: string;
  };
  launcher_id: string;
  p2_singleton_puzzle_hash: string;
  tip_singleton_coin_id: string;
  wallet_id: number;
  target: null | {
    owner_pubkey: string;
    pool_url: string;
    relative_lock_height: number;
    state: PlotNFTState;
    target_puzzle_hash: string;
    version: number;
  };
};

export default PoolWalletStatus;
