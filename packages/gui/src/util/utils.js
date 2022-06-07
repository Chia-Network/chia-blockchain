export function hex_to_array(hexString) {
  if (hexString.slice(0, 2) === '0x' || hexString.slice(0, 2) === '0X') {
    hexString = hexString.slice(2);
  }
  const arr = [];
  for (let i = 0; i < hexString.length; i += 2) {
    arr.push(Number.parseInt(hexString.substr(i, 2), 16));
  }
  return arr;
}

export function stripHexPrefix(hexString) {
  if (hexString.startsWith('0x') || hexString.startsWith('0X')) {
    return hexString.slice(2);
  }
  return hexString;
}

export function arr_to_hex(buffer) {
  // buffer is an ArrayBuffer
  return Array.prototype.map
    .call(new Uint8Array(buffer), (x) => `00${x.toString(16)}`.slice(-2))
    .join('');
}

export async function sha256(buf) {
  return await window.crypto.subtle.digest('SHA-256', new Uint8Array(buf));
}
