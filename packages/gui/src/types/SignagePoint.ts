type SignagePoint = {
  challenge_hash: string;
  challenge_chain_sp: string;
  reward_chain_sp: string;
  difficulty: number;
  sub_slot_iters: number;
  signage_point_index: number;
};

export default SignagePoint;
