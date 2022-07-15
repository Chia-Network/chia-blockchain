import { bech32m } from 'bech32';

export function removePrefix(value: string, prefix: string): string {
  if (value.startsWith(prefix)) {
    return value.slice(prefix.length);
  }

  return value;
}

export default function toBech32m(value: string, prefix: string): string {
  if (value.startsWith(prefix)) {
    return value;
  }

  const pureHash = removePrefix(value, '0x');
  const words = bech32m.toWords(Buffer.from(pureHash, 'hex'));
  return bech32m.encode(prefix, words);
}

export function fromBech32m(value: string): string {
  const data = bech32m.decode(value);
  return Buffer.from(bech32m.fromWords(data.words)).toString('hex');
}

export function decodeBech32m(value: string): string {
  const { words, prefix } = bech32m.decode(value);
  const data = Buffer.from(bech32m.fromWords(words)).toString('hex');

  return { prefix, data };
}
