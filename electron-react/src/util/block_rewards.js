/* global BigInt */

export function calculate_block_reward(height) {
  if (height === 0) {
    return BigInt(500000000000000000);
  }
  return BigInt(14000000000000);
}

export function calculate_base_fee(height) {
  return BigInt(2000000000000);
}
