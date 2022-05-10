import computeHash from './computeHash';

export default function isContentHashValid(content: string, hash: string): boolean {
  const computedHash = computeHash(content);
  return computedHash === hash;
}
