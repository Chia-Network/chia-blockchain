type Group = {
  id: string;
  self: boolean;
  name: string;
  poolUrl?: string;
  poolName?: string;
  poolDescription?: string;
  state: 'NOT_CREATED' | 'FREE' | 'POOLING' | 'ESCAPING';
  targetState?: 'FREE' | 'POOLING' | 'ESCAPING';
  balance: number;
  address: string;

  p2_singleton_puzzle_hash: string;
  points_found_since_start: number;
  points_found_24h: number[];
  points_acknowledged_since_start: number;
  points_acknowledged_24h: number[];
  current_points_balance: number;
  current_difficulty: number;
  pool_errors_24h: string[];
  pool_info: {
    pool_name: string;
    pool_description: string;
  };
  pool_config: {
    owner_public_key: string;
    pool_puzzle_hash: string;
    pool_url: string;
    singleton_genesis: string;
    target: string;
    target_signature: string;
  };
};

export default Group;
