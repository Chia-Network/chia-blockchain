type PoolInfo = {
  name: string;
  description: string;
  pool_url: string;
  fee: string;
  logo_url: string;
  minimum_difficulty: number;
  protocol_version: string;
  relative_lock_height: number;
  target_puzzle_hash: string;
};

export default PoolInfo;
