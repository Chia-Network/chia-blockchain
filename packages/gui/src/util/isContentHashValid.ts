import computeHash from './computeHash';

export default function isContentHashValid(
  content: string,
  hash: string,
): boolean {
  const computedHash = computeHash(content);
  let otherHash = hash.toLowerCase();
  if (otherHash.startsWith('0x')) {
    otherHash = otherHash.substring(2);
  }
  return computedHash === otherHash;
}
