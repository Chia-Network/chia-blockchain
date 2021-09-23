/* global BigInt */

export function unix_to_short_date(unix_timestamp) {
  const d = new Date(unix_timestamp * 1000);
  return `${d.toLocaleDateString('en-US', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })} ${d.toLocaleTimeString()}`;
}

export function get_query_variable(variable) {
  const query = global.location.search.slice(1);
  const vars = query.split('&');
  for (const var_ of vars) {
    const pair = var_.split('=');
    if (decodeURIComponent(pair[0]) === variable) {
      return decodeURIComponent(pair[1]);
    }
  }
}

export function big_int_to_array(x, num_bytes) {
  let truncated = BigInt.asUintN(num_bytes * 8, x);
  const arr = [];
  for (let i = 0; i < num_bytes; i++) {
    arr.splice(0, 0, Number(truncated & BigInt(255)));
    truncated >>= BigInt(8);
  }
  return arr;
}

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

export function arr_to_hex(buffer) {
  // buffer is an ArrayBuffer
  return Array.prototype.map
    .call(new Uint8Array(buffer), (x) => `00${x.toString(16)}`.slice(-2))
    .join('');
}

export async function sha256(buf) {
  return await window.crypto.subtle.digest('SHA-256', new Uint8Array(buf));
}
