import type PoolInfo from '../types/PoolInfo';

export default async function getPoolInfo(poolUrl: string): PoolInfo {
  const url = `${poolUrl}/pool_info`;
  const response = await fetch(url);
  return response.json();
}
