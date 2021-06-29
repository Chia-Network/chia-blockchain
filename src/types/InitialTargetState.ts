type InitialTargetState =
  | {
      state: 'SELF_POOLING';
    }
  | {
      state: 'FARMING_TO_POOL';
      pool_url: string;
      relative_lock_height: number;
      target_puzzle_hash: string;
    };

export default InitialTargetState;
