import crypto from 'crypto';

export default function computeHash(content: string, hash = 'sha256'): string {
  return crypto.createHash(hash).update(content, 'binary').digest('hex');
}
