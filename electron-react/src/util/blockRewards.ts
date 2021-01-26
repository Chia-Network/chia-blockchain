/* global BigInt */

/* DEPRECATED
export function calculate_block_reward(height) {
  if (height === 0) {
    return BigInt(500000000000000000);
  }
  return BigInt(14000000000000);
}

export function calculate_base_fee(height) {
  return BigInt(2000000000000);
}
*/

export function calculatePoolReward(height: number): BigInt {
  if (height === 0) {
    return BigInt(500000000000000000);
  } 
  if (height < 2000) {
    return BigInt(875000000000);
  } 
  if (height < 4000) {
    return BigInt(875000000000);
  } 
  if (height < 6000) {
    return BigInt(875000000000);
  }
  
  return BigInt(875000000000);
}

export function calculateBaseFarmerReward(height: number): BigInt {
  if (height < 2000) {
    return BigInt(125000000000);
  } 
  if (height < 4000) {
    return BigInt(125000000000);
  } 
  if (height < 6000) {
    return BigInt(125000000000)
  }
  
  return BigInt(125000000000)
}
