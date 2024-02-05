from __future__ import annotations

import sys
from io import StringIO

from chia_rs import AugSchemeMPL, PrivateKey

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle


def test_debug_spend_bundle() -> None:
    sk = PrivateKey.from_bytes(bytes([1] * 32))
    pk = sk.get_g1()
    msg = bytes(32)
    sig = AugSchemeMPL.sign(sk, msg)
    ACS = Program.to(15).curry(Program.to("hey").curry("now")).curry("brown", "cow")
    ACS_PH = ACS.get_tree_hash()
    coin: Coin = Coin(bytes32([0] * 32), ACS_PH, 3)
    child_coin: Coin = Coin(coin.name(), ACS_PH, 0)
    coin_bad_reveal: Coin = Coin(bytes32([0] * 32), bytes32([0] * 32), 0)
    solution = Program.to(
        [
            [ConditionOpcode.AGG_SIG_UNSAFE, pk, msg],
            [ConditionOpcode.REMARK],
            [ConditionOpcode.CREATE_COIN, ACS_PH, 0],
            [ConditionOpcode.CREATE_COIN, bytes32([0] * 32), 1],
            [ConditionOpcode.CREATE_COIN, bytes32([0] * 32), 2, [b"memo", b"memo", b"memo"]],
            [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, None],
            [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, bytes32([0] * 32)],
            [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, std_hash(coin.name())],
            [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, b"hey"],
            [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, None],
            [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, bytes32([0] * 32)],
            [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, std_hash(coin.puzzle_hash)],
            [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, b"hey"],
        ]
    )

    result = StringIO()
    sys.stdout = result

    debug_spend_bundle(
        SpendBundle(
            [
                make_spend(
                    coin_bad_reveal,
                    ACS,
                    Program.to(None),
                ),
                make_spend(
                    coin,
                    ACS,
                    solution,
                ),
                make_spend(
                    child_coin,
                    ACS,
                    Program.to(None),
                ),
            ],
            sig,
        )
    )

    assert (
        result.getvalue()
        == '================================================================================\nconsuming coin (0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 ())\n  with id f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b\n\n\nbrun -y main.sym \'(a (q 2 (q . 15) (c (q 2 (q . "hey") (c (q . "now") 1)) 1)) (c (q . "brown") (c (q . "cow") 1)))\' \'()\'\n\n--- Uncurried Args ---\n- <curried puzzle>\n  - Layer 1:\n    - Mod hash: 507414e217dc45d6dbb923077c48641c9d2ba8430c92df9c49660480f398b133\n    - "brown"\n    - "cow"\n  - Layer 2:\n    - Mod hash: 24255ef5d941493b9978f3aabb0ed07d084ade196d23f463ff058954cbf6e9b6\n    - <curried puzzle>\n      - Layer 1:\n        - Mod hash: 7ee93c7e6fde43b6ac75100244fd294b8247362f22724b2ef0099bf7ab083def\n        - "now"\n\n*** BAD PUZZLE REVEAL\n3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 vs 0000000000000000000000000000000000000000000000000000000000000000\n********************************************************************************\n\nconsuming coin (0x0000000000000000000000000000000000000000000000000000000000000000 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 3)\n  with id f61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f\n\n\nbrun -y main.sym \'(a (q 2 (q . 15) (c (q 2 (q . "hey") (c (q . "now") 1)) 1)) (c (q . "brown") (c (q . "cow") 1)))\' \'((49 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000) (q) (51 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ()) (51 0x0000000000000000000000000000000000000000000000000000000000000000 1) (51 0x0000000000000000000000000000000000000000000000000000000000000000 2 ("memo" "memo" "memo")) (60 ()) (61 0x0000000000000000000000000000000000000000000000000000000000000000) (61 0x98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4) (60 "hey") (62 ()) (63 0x0000000000000000000000000000000000000000000000000000000000000000) (63 0xfb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5) (62 "hey"))\'\n\n--- Uncurried Args ---\n- <curried puzzle>\n  - Layer 1:\n    - Mod hash: 507414e217dc45d6dbb923077c48641c9d2ba8430c92df9c49660480f398b133\n    - "brown"\n    - "cow"\n  - Layer 2:\n    - Mod hash: 24255ef5d941493b9978f3aabb0ed07d084ade196d23f463ff058954cbf6e9b6\n    - <curried puzzle>\n      - Layer 1:\n        - Mod hash: 7ee93c7e6fde43b6ac75100244fd294b8247362f22724b2ef0099bf7ab083def\n        - "now"\n\n((AGG_SIG_UNSAFE 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000) (REMARK) (CREATE_COIN 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ()) (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 1) (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 2 ("memo" "memo" "memo")) (CREATE_COIN_ANNOUNCEMENT ()) (ASSERT_COIN_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000) (ASSERT_COIN_ANNOUNCEMENT 0x98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4) (CREATE_COIN_ANNOUNCEMENT "hey") (CREATE_PUZZLE_ANNOUNCEMENT ()) (ASSERT_PUZZLE_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000) (ASSERT_PUZZLE_ANNOUNCEMENT 0xfb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5) (CREATE_PUZZLE_ANNOUNCEMENT "hey"))\n\ngrouped conditions:\n\n  (AGG_SIG_UNSAFE 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000)\n\n  (REMARK)\n\n  (CREATE_COIN 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ())\n  (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 1)\n  (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 2 ("memo" "memo" "memo"))\n\n  (CREATE_COIN_ANNOUNCEMENT ())\n  (CREATE_COIN_ANNOUNCEMENT "hey")\n\n  (ASSERT_COIN_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000)\n  (ASSERT_COIN_ANNOUNCEMENT 0x98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4)\n\n  (CREATE_PUZZLE_ANNOUNCEMENT ())\n  (CREATE_PUZZLE_ANNOUNCEMENT "hey")\n\n  (ASSERT_PUZZLE_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000)\n  (ASSERT_PUZZLE_ANNOUNCEMENT 0xfb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5)\n\n\n-------\nconsuming coin (0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ())\n  with id a6f9255571f8a910057476920a960ae7be70034677303a944b28a47550b9a5e4\n\n\nbrun -y main.sym \'(a (q 2 (q . 15) (c (q 2 (q . "hey") (c (q . "now") 1)) 1)) (c (q . "brown") (c (q . "cow") 1)))\' \'()\'\n\n--- Uncurried Args ---\n- <curried puzzle>\n  - Layer 1:\n    - Mod hash: 507414e217dc45d6dbb923077c48641c9d2ba8430c92df9c49660480f398b133\n    - "brown"\n    - "cow"\n  - Layer 2:\n    - Mod hash: 24255ef5d941493b9978f3aabb0ed07d084ade196d23f463ff058954cbf6e9b6\n    - <curried puzzle>\n      - Layer 1:\n        - Mod hash: 7ee93c7e6fde43b6ac75100244fd294b8247362f22724b2ef0099bf7ab083def\n        - "now"\n\n()\n\n(no output conditions generated)\n\n-------\n\nspent coins\n  (0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 ())\n      => spent coin id f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b\n  (0x0000000000000000000000000000000000000000000000000000000000000000 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 3)\n      => spent coin id f61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f\n\ncreated coins\n  (0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f 0x0000000000000000000000000000000000000000000000000000000000000000 1)\n      => created coin id 041ca97661e2ab59c4d85848092229b00bae000573927b6ab9af4e2becd765c5\n  (0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f 0x0000000000000000000000000000000000000000000000000000000000000000 2)\n      => created coin id d3f6dc7e6c0a81d22ebebd5559962bab95fa7798ad4b0bcbb42da214215e5e98\n\nephemeral coins\n  (0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ())\n      => created coin id a6f9255571f8a910057476920a960ae7be70034677303a944b28a47550b9a5e4\ncreated coin announcements\n  [\'0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f\', \'0x686579\'] =>\n      17577cbab71385b4ee009c792f5ed2d954fbd3a31fede834150184519e0ac3fe\n  [\'0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f\', \'0x\'] =>\n      98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4\ncreated puzzle announcements\n  [\'0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307\', \'0x686579\'] =>\n      73f660046d0c542a49db3410b64f12770fc23707bbf1f082d35d9af71f89edd2\n  [\'0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307\', \'0x\'] =>\n      fb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5\n\n\nzero_coin_set = [b\'\\xa6\\xf9%Uq\\xf8\\xa9\\x10\\x05tv\\x92\\n\\x96\\n\\xe7\\xbep\\x03Fw0:\\x94K(\\xa4uP\\xb9\\xa5\\xe4\']\n\ncreated  coin announcements = [\'17577cbab71385b4ee009c792f5ed2d954fbd3a31fede834150184519e0ac3fe\', \'98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4\']\n\nasserted coin announcements = [\'0000000000000000000000000000000000000000000000000000000000000000\', \'98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4\']\n\nsymdiff of coin announcements = [\'0000000000000000000000000000000000000000000000000000000000000000\', \'17577cbab71385b4ee009c792f5ed2d954fbd3a31fede834150184519e0ac3fe\']\n\ncreated  puzzle announcements = [\'73f660046d0c542a49db3410b64f12770fc23707bbf1f082d35d9af71f89edd2\', \'fb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5\']\n\nasserted puzzle announcements = [\'0000000000000000000000000000000000000000000000000000000000000000\', \'fb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5\']\n\nsymdiff of puzzle announcements = [\'0000000000000000000000000000000000000000000000000000000000000000\', \'73f660046d0c542a49db3410b64f12770fc23707bbf1f082d35d9af71f89edd2\']\n\n\n================================================================================\n\naggregated signature check pass: True\npks: [<G1Element aa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1>]\nmsgs: [\'0000000000000000000000000000000000000000000000000000000000000000\']\nadd_data: ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb\nsignature: a458f8f379a4bec00f36cd38e36790210f0b7c4ee772417c0cd20513d75c7505a0532d220ab03a471e9e255e2c54472a03abd31a9feb56d551bf482e31e48747b04fe90f4e3c2af98a2de0d11f869cde360f93b8efa37ec1c28950aa52bfbacd\n'  # noqa
    )
