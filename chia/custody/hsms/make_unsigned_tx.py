import hashlib

from hsms.atoms.hexbytes import hexbytes
from hsms.streamables import Coin, CoinSpend, Program
from hsms.multisig.pst import PartiallySignedTransaction

from clvm_tools.binutils import assemble


PAY_TO_AGGSIG_ME_PROG = """(q (50
     0x8ba79a9ccd362086d552a6f56da7fe612959b0dd372350ad798c77c2170de2163a00e499928cc40547a7a8a5e2cde6be
     0x4bf5122f344554c53bde2ebb8cd2b7e3d1600ad631c385a5d7cce23c7785459a))"""

PAY_TO_AGGSIG_ME = Program.to(assemble(PAY_TO_AGGSIG_ME_PROG))


def make_coin():
    parent_id = hashlib.sha256(bytes([1] * 32)).digest()
    puzzle_hash = PAY_TO_AGGSIG_ME.tree_hash()
    coin = Coin(parent_id, puzzle_hash, 10000)
    return coin


def make_coin_spends():
    coin = make_coin()
    coin_spend = CoinSpend(coin, PAY_TO_AGGSIG_ME, Program.to(0))
    return [coin_spend]


def main():
    coin_spends = make_coin_spends()
    print(coin_spends)

    print(bytes(coin_spends).hex())

    d = PartiallySignedTransaction(
        coin_spends=list(coin_spends),
        sigs=[],
        delegated_solution=Program.to(0),
        hd_hints={
            bytes.fromhex("c34eb867"): {
                "hd_fingerprint": bytes.fromhex("0b92dcdd"),
                "index": 0,
            }
        },
    )

    t = bytes(d)
    print()
    print(t.hex())


def round_trip():
    coin_spends = make_coin_spends()
    d = PartiallySignedTransaction(
        coin_spends=coin_spends,
        sigs=[],
        delegated_solution=Program.to(0),
        hd_hints={
            1253746868: {
                "hd_fingerprint": 194174173,
                "index": [1, 5, 19],
            }
        },
    )

    breakpoint()
    print(coin_spends[0].puzzle_reveal)

    b = hexbytes(d)
    breakpoint()
    d1 = PartiallySignedTransaction.from_bytes(b)
    b1 = hexbytes(d1)
    print(b)
    print(b1)

    assert b == b1


round_trip()
