export default async function getPoolInfo(poolUrl: string): Object {
  const url = `${poolUrl}/pool_info`;
  const response = await fetch(url);
  return response.json();
}

