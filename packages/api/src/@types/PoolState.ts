import type PoolInfo from './PoolInfo';

type PoolState = {
  p2_singleton_puzzle_hash: string;
  points_found_since_start: number;
  points_found_24h: [number, number][];
  points_acknowledged_since_start: number;
  points_acknowledged_24h: [number, number][];
  current_points: number;
  current_difficulty: number;
  plotCount: number;
  pool_errors_24h: {
    current_difficulty: number;
    error_code: number;
    error_message: string;
  }[];
  pool_info: PoolInfo;
  pool_config: {
    authentication_key_info_signature: string;
    authentication_public_key: string;
    authentication_public_key_timestamp: number;
    owner_public_key: string;
    pool_puzzle_hash: string;
    pool_url: string;
    launcher_id: string;
    target: string;
    target_signature: string;
    payout_instructions: string;
    target_puzzle_hash: string;
  };
};

export default PoolState;
