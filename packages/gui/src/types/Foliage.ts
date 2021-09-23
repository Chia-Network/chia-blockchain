type Foliage = {
  foliage_transaction_block_hash: string;
  foliage_block_data_signature: string;
  foliage_block_data: {
    extension_data: string;
    farmer_reward_puzzle_hash: string;
    pool_signature: string;
    pool_target: {
      max_height: number;
      puzzle_hash: string;
    };
    unfinished_reward_block_hash: string;
  };
  prev_block_hash: string;
  reward_block_hash: string;
};

export default Foliage;
