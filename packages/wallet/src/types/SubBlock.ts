type SubBlock = {
  challenge_block_info_hash: string;
  challenge_vdf_output: {
    a: string;
  };
  deficit: number;
  farmer_puzzle_hash: string;
  fees: null | string;
  finished_challenge_slot_hashes: string | null;
  finished_infused_challenge_slot_hashes: string[] | null;
  finished_reward_slot_hashes: string[] | null;
  header_hash: string;
  height: number;
  infused_challenge_vdf_output: {
    a: string;
  };
  overflow: boolean;
  pool_puzzle_hash: string;
  prev_block_hash: string | null;
  prev_hash: string | null;
  required_iters: string;
  reward_claims_incorporated: unknown;
  reward_infusion_new_challenge: string;
  signage_point_index: number;
  sub_epoch_summary_included: unknown;
  sub_slot_iters: string;
  timestamp: number | null;
  total_iters: string;
  weight: string;
  foliage_transaction_block?: {
    timestamp: string;
  };
};

export default SubBlock;
