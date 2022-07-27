import { decodeBech32m } from '@chia/api';

export default function validAddress(address: string, allowedPrefixes?: string[]) {
  const response = decodeBech32m(address);
  const prefix = response.prefix.toLowerCase();

  if (allowedPrefixes && !allowedPrefixes.includes(prefix)) {
    throw new Error(`Invalid address: ${address}. Valid addresses must contain one of the following prefixes: ${allowedPrefixes.join(', ')}`);
  }
}
