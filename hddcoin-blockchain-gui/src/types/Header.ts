type Header = {
  data: {
    additions_root: string;
    aggregated_signature: string;
    cost: string;
    extension_data: string;
    farmer_rewards_puzzle_hash: string;
    filter_hash: string;
    finish_time: number;
    finished: boolean;
    generator_hash: string;
    header_hash: string;
    height: number;
    pool_target: {
      max_height: 0;
      puzzle_hash: string;
    };
    prev_header_hash: string;
    proof_of_space_hash: string;
    removals_root: string;
    timestamp: string;
    total_iters: string;
    total_transaction_fees: string;
    weight: string;
  };
  plot_signature: string;
};

export default Header;
