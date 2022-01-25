
from chia.wallet.puzzles.cc_loader import CC_MOD


def get_cat_puzzle_hash(asset_id: str, xch_puzzle_hash: str) -> str:
  tail_hash = bytes.fromhex(asset_id.lstrip("0x"))
  xch_puzzle_hash = bytes.fromhex(xch_puzzle_hash.lstrip("0x"))
  cat_puzzle_hash = CC_MOD.curry(CC_MOD.get_tree_hash(), tail_hash, xch_puzzle_hash).get_tree_hash(xch_puzzle_hash)
  return "0x" + cat_puzzle_hash.hex()
