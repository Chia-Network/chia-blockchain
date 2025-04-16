from __future__ import annotations

import pytest
from chia_rs import AugSchemeMPL, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.hash import std_hash
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


def test_debug_spend_bundle(capsys: pytest.CaptureFixture[str]) -> None:
    sk = PrivateKey.from_bytes(bytes([1] * 32))
    pk = sk.get_g1()
    msg = bytes(32)
    sig = AugSchemeMPL.sign(sk, msg)
    ACS = Program.to(15).curry(Program.to("hey").curry("now")).curry("brown", "cow")
    ACS_PH = ACS.get_tree_hash()
    coin: Coin = Coin(bytes32.zeros, ACS_PH, uint64(3))
    child_coin: Coin = Coin(coin.name(), ACS_PH, uint64(0))
    coin_bad_reveal: Coin = Coin(bytes32.zeros, bytes32.zeros, uint64(0))
    solution = Program.to(
        [
            [ConditionOpcode.AGG_SIG_UNSAFE, pk, msg],
            [ConditionOpcode.REMARK],
            [ConditionOpcode.CREATE_COIN, ACS_PH, 0],
            [ConditionOpcode.CREATE_COIN, bytes32.zeros, 1],
            [ConditionOpcode.CREATE_COIN, bytes32.zeros, 2, [b"memo", b"memo", b"memo"]],
            [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, None],
            [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, bytes32.zeros],
            [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, std_hash(coin.name())],
            [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, b"hey"],
            [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, None],
            [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, bytes32.zeros],
            [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, std_hash(coin.puzzle_hash)],
            [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, b"hey"],
        ]
    )

    capsys.readouterr()

    debug_spend_bundle(
        WalletSpendBundle(
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

    stdout, _ = capsys.readouterr()

    assert (
        stdout
        == """================================================================================
consuming coin (0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 ())
  with id f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b


brun -y main.sym '(a (q 2 (q . 15) (c (q 2 (q . "hey") (c (q . "now") 1)) 1)) (c (q . "brown") (c (q . "cow") 1)))' '()'

--- Uncurried Args ---
- <curried puzzle>
  - Layer 1:
    - Mod hash: 507414e217dc45d6dbb923077c48641c9d2ba8430c92df9c49660480f398b133
    - "brown"
    - "cow"
  - Layer 2:
    - Mod hash: 24255ef5d941493b9978f3aabb0ed07d084ade196d23f463ff058954cbf6e9b6
    - <curried puzzle>
      - Layer 1:
        - Mod hash: 7ee93c7e6fde43b6ac75100244fd294b8247362f22724b2ef0099bf7ab083def
        - "now"

*** BAD PUZZLE REVEAL
3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 vs 0000000000000000000000000000000000000000000000000000000000000000
********************************************************************************

consuming coin (0x0000000000000000000000000000000000000000000000000000000000000000 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 3)
  with id f61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f


brun -y main.sym '(a (q 2 (q . 15) (c (q 2 (q . "hey") (c (q . "now") 1)) 1)) (c (q . "brown") (c (q . "cow") 1)))' '((49 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000) (q) (51 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ()) (51 0x0000000000000000000000000000000000000000000000000000000000000000 1) (51 0x0000000000000000000000000000000000000000000000000000000000000000 2 ("memo" "memo" "memo")) (60 ()) (61 0x0000000000000000000000000000000000000000000000000000000000000000) (61 0x98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4) (60 "hey") (62 ()) (63 0x0000000000000000000000000000000000000000000000000000000000000000) (63 0xfb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5) (62 "hey"))'

--- Uncurried Args ---
- <curried puzzle>
  - Layer 1:
    - Mod hash: 507414e217dc45d6dbb923077c48641c9d2ba8430c92df9c49660480f398b133
    - "brown"
    - "cow"
  - Layer 2:
    - Mod hash: 24255ef5d941493b9978f3aabb0ed07d084ade196d23f463ff058954cbf6e9b6
    - <curried puzzle>
      - Layer 1:
        - Mod hash: 7ee93c7e6fde43b6ac75100244fd294b8247362f22724b2ef0099bf7ab083def
        - "now"

((AGG_SIG_UNSAFE 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000) (REMARK) (CREATE_COIN 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ()) (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 1) (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 2 ("memo" "memo" "memo")) (CREATE_COIN_ANNOUNCEMENT ()) (ASSERT_COIN_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000) (ASSERT_COIN_ANNOUNCEMENT 0x98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4) (CREATE_COIN_ANNOUNCEMENT "hey") (CREATE_PUZZLE_ANNOUNCEMENT ()) (ASSERT_PUZZLE_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000) (ASSERT_PUZZLE_ANNOUNCEMENT 0xfb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5) (CREATE_PUZZLE_ANNOUNCEMENT "hey"))

grouped conditions:

  (AGG_SIG_UNSAFE 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000)

  (REMARK)

  (CREATE_COIN 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ())
  (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 1)
  (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 2 ("memo" "memo" "memo"))

  (CREATE_COIN_ANNOUNCEMENT ())
  (CREATE_COIN_ANNOUNCEMENT "hey")

  (ASSERT_COIN_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000)
  (ASSERT_COIN_ANNOUNCEMENT 0x98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4)

  (CREATE_PUZZLE_ANNOUNCEMENT ())
  (CREATE_PUZZLE_ANNOUNCEMENT "hey")

  (ASSERT_PUZZLE_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000)
  (ASSERT_PUZZLE_ANNOUNCEMENT 0xfb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5)


-------
consuming coin (0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ())
  with id a6f9255571f8a910057476920a960ae7be70034677303a944b28a47550b9a5e4


brun -y main.sym '(a (q 2 (q . 15) (c (q 2 (q . "hey") (c (q . "now") 1)) 1)) (c (q . "brown") (c (q . "cow") 1)))' '()'

--- Uncurried Args ---
- <curried puzzle>
  - Layer 1:
    - Mod hash: 507414e217dc45d6dbb923077c48641c9d2ba8430c92df9c49660480f398b133
    - "brown"
    - "cow"
  - Layer 2:
    - Mod hash: 24255ef5d941493b9978f3aabb0ed07d084ade196d23f463ff058954cbf6e9b6
    - <curried puzzle>
      - Layer 1:
        - Mod hash: 7ee93c7e6fde43b6ac75100244fd294b8247362f22724b2ef0099bf7ab083def
        - "now"

()

(no output conditions generated)

-------

spent coins
  (0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 ())
      => spent coin id f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b
  (0x0000000000000000000000000000000000000000000000000000000000000000 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 3)
      => spent coin id f61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f

created coins
  (0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f 0x0000000000000000000000000000000000000000000000000000000000000000 1)
      => created coin id 041ca97661e2ab59c4d85848092229b00bae000573927b6ab9af4e2becd765c5
  (0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f 0x0000000000000000000000000000000000000000000000000000000000000000 2)
      => created coin id d3f6dc7e6c0a81d22ebebd5559962bab95fa7798ad4b0bcbb42da214215e5e98

ephemeral coins
  (0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f 0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307 ())
      => created coin id a6f9255571f8a910057476920a960ae7be70034677303a944b28a47550b9a5e4
created coin announcements
  ['0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f', '0x686579'] =>
      17577cbab71385b4ee009c792f5ed2d954fbd3a31fede834150184519e0ac3fe
  ['0xf61c4154a3541d84bf6ed0f05ac8a062ab08022b48e53daf7f5603fc8eb7ed1f', '0x'] =>
      98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4
created puzzle announcements
  ['0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307', '0x686579'] =>
      73f660046d0c542a49db3410b64f12770fc23707bbf1f082d35d9af71f89edd2
  ['0x3c4f5a82fc6548a256f5959430704623fa7ac291f45e1da47e2f91f0e6c30307', '0x'] =>
      fb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5


zero_coin_set = [<bytes32: a6f9255571f8a910057476920a960ae7be70034677303a944b28a47550b9a5e4>]

created  coin announcements = ['17577cbab71385b4ee009c792f5ed2d954fbd3a31fede834150184519e0ac3fe', '98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4']

asserted coin announcements = ['0000000000000000000000000000000000000000000000000000000000000000', '98442bcc931fc4c94a2a1b17dafb8959a867097bd3aa73871ca9cfc8327346b4']

symdiff of coin announcements = ['0000000000000000000000000000000000000000000000000000000000000000', '17577cbab71385b4ee009c792f5ed2d954fbd3a31fede834150184519e0ac3fe']

created  puzzle announcements = ['73f660046d0c542a49db3410b64f12770fc23707bbf1f082d35d9af71f89edd2', 'fb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5']

asserted puzzle announcements = ['0000000000000000000000000000000000000000000000000000000000000000', 'fb4c79668bee67977af996dc2f42071735a819b4221d3f5c9e8e9f43c30c2bc5']

symdiff of puzzle announcements = ['0000000000000000000000000000000000000000000000000000000000000000', '73f660046d0c542a49db3410b64f12770fc23707bbf1f082d35d9af71f89edd2']


================================================================================

aggregated signature check pass: True
pks: [<G1Element aa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1>]
msgs: ['0000000000000000000000000000000000000000000000000000000000000000']
add_data: ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb
signature: a458f8f379a4bec00f36cd38e36790210f0b7c4ee772417c0cd20513d75c7505a0532d220ab03a471e9e255e2c54472a03abd31a9feb56d551bf482e31e48747b04fe90f4e3c2af98a2de0d11f869cde360f93b8efa37ec1c28950aa52bfbacd
"""  # noqa: E501
    )
