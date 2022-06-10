import crypto from 'crypto';

export default function computeHash(
  content: string,
  options: { hash?: string; encoding?: string },
): string {
  const { hash, encoding } = options;
  return crypto
    .createHash(hash ?? 'sha256')
    .update(content, (encoding ?? 'binary') as crypto.Encoding)
    .digest('hex');
}
