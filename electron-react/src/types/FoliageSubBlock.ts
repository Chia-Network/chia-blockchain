type FoliageSubBlock = {
  foliage_block_hash: string;
  foliage_block_signature: string;
  foliage_sub_block_data: {
    extension_data: string;
    farmer_reward_puzzle_hash: string;
    pool_signature: string;
    pool_target: {
      max_height: number;
      puzzle_hash: string;
    };
    unfinished_reward_block_hash: string;
  };
  foliage_sub_block_signature: string;
  prev_sub_block_hash: string;
  reward_block_hash: string;
};

export default FoliageSubBlock;
