import { big_int_to_array, hex_to_array, arr_to_hex, sha256 } from "./utils";
/* global BigInt */

export async function hash_header(header) {
  var buf = big_int_to_array(BigInt(header.data.height), 4);
  buf = buf.concat(hex_to_array(header.data.prev_header_hash));
  buf = buf.concat(big_int_to_array(BigInt(header.data.timestamp), 8));
  buf = buf.concat(hex_to_array(header.data.filter_hash));
  buf = buf.concat(hex_to_array(header.data.proof_of_space_hash));
  buf = buf.concat(big_int_to_array(BigInt(header.data.weight), 16));
  buf = buf.concat(big_int_to_array(BigInt(header.data.total_iters), 8));
  buf = buf.concat(hex_to_array(header.data.additions_root));
  buf = buf.concat(hex_to_array(header.data.removals_root));
  buf = buf.concat(hex_to_array(header.data.coinbase.parent_coin_info));
  buf = buf.concat(hex_to_array(header.data.coinbase.puzzle_hash));
  buf = buf.concat(big_int_to_array(BigInt(header.data.coinbase.amount), 8));
  buf = buf.concat(hex_to_array(header.data.coinbase_signature.sig));
  buf = buf.concat(hex_to_array(header.data.fees_coin.parent_coin_info));
  buf = buf.concat(hex_to_array(header.data.fees_coin.puzzle_hash));
  buf = buf.concat(big_int_to_array(BigInt(header.data.fees_coin.amount), 8));

  // TODO: handle no aggsig
  if (
    header.data.aggregated_signature === undefined ||
    header.data.aggregated_signature === null
  ) {
    buf.push(0);
  } else {
    buf.push(1);
    let agg_sig_bytes = hex_to_array(header.data.aggregated_signature.sig);
    buf = buf.concat(agg_sig_bytes);
  }
  buf = buf.concat(big_int_to_array(BigInt(header.data.cost), 8));
  buf = buf.concat(hex_to_array(header.data.extension_data));
  buf = buf.concat(hex_to_array(header.data.generator_hash));
  buf = buf.concat(hex_to_array(header.harvester_signature));

  let hash = await sha256(buf);
  return arr_to_hex(hash);
}
