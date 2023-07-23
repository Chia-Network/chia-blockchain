from __future__ import annotations

import sys
from io import StringIO

from blspy import AugSchemeMPL, PrivateKey

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle


def test_debug_spend_bundle() -> None:
    sk = PrivateKey.from_bytes(bytes([1] * 32))
    pk = sk.get_g1()
    msg = bytes(32)
    sig = AugSchemeMPL.sign(sk, msg)
    ACS = Program.to(1)
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
                CoinSpend(
                    coin_bad_reveal,
                    ACS,
                    Program.to(None),
                ),
                CoinSpend(
                    coin,
                    ACS,
                    solution,
                ),
                CoinSpend(
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
        == "================================================================================\nconsuming coin (0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 ())\n  with id f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b\n\n\nbrun -y main.sym '1' '()'\n\n*** BAD PUZZLE REVEAL\n9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2 vs 0000000000000000000000000000000000000000000000000000000000000000\n********************************************************************************\n\nconsuming coin (0x0000000000000000000000000000000000000000000000000000000000000000 0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2 3)\n  with id adecf3df0cc0c64fb5e206407871645f61266152075628350a2b17fcca40bf6e\n\n\nbrun -y main.sym '1' '((49 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000) (q) (51 0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2 ()) (51 0x0000000000000000000000000000000000000000000000000000000000000000 1) (51 0x0000000000000000000000000000000000000000000000000000000000000000 2 (\"memo\" \"memo\" \"memo\")) (60 ()) (61 0x0000000000000000000000000000000000000000000000000000000000000000) (61 0xc89079367484570676f7b6aa90a45c476e1ecd83a94228ae17d9e738ee993f00) (60 \"hey\") (62 ()) (63 0x0000000000000000000000000000000000000000000000000000000000000000) (63 0x632f30a65e0ed212dc0af6ec22099acf689a70ad4fe28e4166cbf1f818889686) (62 \"hey\"))'\n\n((AGG_SIG_UNSAFE 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000) (REMARK) (CREATE_COIN 0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2 ()) (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 1) (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 2 (\"memo\" \"memo\" \"memo\")) (CREATE_COIN_ANNOUNCEMENT ()) (ASSERT_COIN_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000) (ASSERT_COIN_ANNOUNCEMENT 0xc89079367484570676f7b6aa90a45c476e1ecd83a94228ae17d9e738ee993f00) (CREATE_COIN_ANNOUNCEMENT \"hey\") (CREATE_PUZZLE_ANNOUNCEMENT ()) (ASSERT_PUZZLE_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000) (ASSERT_PUZZLE_ANNOUNCEMENT 0x632f30a65e0ed212dc0af6ec22099acf689a70ad4fe28e4166cbf1f818889686) (CREATE_PUZZLE_ANNOUNCEMENT \"hey\"))\n\ngrouped conditions:\n\n  (AGG_SIG_UNSAFE 0xaa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1 0x0000000000000000000000000000000000000000000000000000000000000000)\n\n  (REMARK)\n\n  (CREATE_COIN 0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2 ())\n  (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 1)\n  (CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000000 2 (\"memo\" \"memo\" \"memo\"))\n\n  (CREATE_COIN_ANNOUNCEMENT ())\n  (CREATE_COIN_ANNOUNCEMENT \"hey\")\n\n  (ASSERT_COIN_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000)\n  (ASSERT_COIN_ANNOUNCEMENT 0xc89079367484570676f7b6aa90a45c476e1ecd83a94228ae17d9e738ee993f00)\n\n  (CREATE_PUZZLE_ANNOUNCEMENT ())\n  (CREATE_PUZZLE_ANNOUNCEMENT \"hey\")\n\n  (ASSERT_PUZZLE_ANNOUNCEMENT 0x0000000000000000000000000000000000000000000000000000000000000000)\n  (ASSERT_PUZZLE_ANNOUNCEMENT 0x632f30a65e0ed212dc0af6ec22099acf689a70ad4fe28e4166cbf1f818889686)\n\n\n-------\nconsuming coin (0xadecf3df0cc0c64fb5e206407871645f61266152075628350a2b17fcca40bf6e 0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2 ())\n  with id aceb47c9b7fafb31e0e5ac55b5c936d5e25b8b967f32c2dd657cc037b21125e8\n\n\nbrun -y main.sym '1' '()'\n\n()\n\n(no output conditions generated)\n\n-------\n\nspent coins\n  (0x0000000000000000000000000000000000000000000000000000000000000000 0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2 3)\n      => spent coin id adecf3df0cc0c64fb5e206407871645f61266152075628350a2b17fcca40bf6e\n  (0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 ())\n      => spent coin id f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b\n\ncreated coins\n  (0xadecf3df0cc0c64fb5e206407871645f61266152075628350a2b17fcca40bf6e 0x0000000000000000000000000000000000000000000000000000000000000000 2)\n      => created coin id 558ce5bddc4ae39eaaa599bf86401e0fffa8ce1b5de984dd33b48f570b872aed\n  (0xadecf3df0cc0c64fb5e206407871645f61266152075628350a2b17fcca40bf6e 0x0000000000000000000000000000000000000000000000000000000000000000 1)\n      => created coin id b0c699f20944b2562c57b199613aadc27fe44c1d3beff4fb7bc0f13b7adbd04c\n\nephemeral coins\n  (0xadecf3df0cc0c64fb5e206407871645f61266152075628350a2b17fcca40bf6e 0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2 ())\n      => created coin id aceb47c9b7fafb31e0e5ac55b5c936d5e25b8b967f32c2dd657cc037b21125e8\ncreated coin announcements\n  ['0xadecf3df0cc0c64fb5e206407871645f61266152075628350a2b17fcca40bf6e', '0x686579'] =>\n      057e258d155c061e2754e13622b77ad131725cd6027a32b81a27ba63e859f92f\n  ['0xadecf3df0cc0c64fb5e206407871645f61266152075628350a2b17fcca40bf6e', '0x'] =>\n      c89079367484570676f7b6aa90a45c476e1ecd83a94228ae17d9e738ee993f00\ncreated puzzle announcements\n  ['0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2', '0x'] =>\n      632f30a65e0ed212dc0af6ec22099acf689a70ad4fe28e4166cbf1f818889686\n  ['0x9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2', '0x686579'] =>\n      b86970b74c8436d7694b27ac1c51176ef31eebcc85305d4e95f8b6d4f2f538bd\n\n\nzero_coin_set = [b'\\xac\\xebG\\xc9\\xb7\\xfa\\xfb1\\xe0\\xe5\\xacU\\xb5\\xc96\\xd5\\xe2[\\x8b\\x96\\x7f2\\xc2\\xdde|\\xc07\\xb2\\x11%\\xe8']\n\ncreated  coin announcements = ['057e258d155c061e2754e13622b77ad131725cd6027a32b81a27ba63e859f92f', 'c89079367484570676f7b6aa90a45c476e1ecd83a94228ae17d9e738ee993f00']\n\nasserted coin announcements = ['0000000000000000000000000000000000000000000000000000000000000000', 'c89079367484570676f7b6aa90a45c476e1ecd83a94228ae17d9e738ee993f00']\n\nsymdiff of coin announcements = ['0000000000000000000000000000000000000000000000000000000000000000', '057e258d155c061e2754e13622b77ad131725cd6027a32b81a27ba63e859f92f']\n\ncreated  puzzle announcements = ['632f30a65e0ed212dc0af6ec22099acf689a70ad4fe28e4166cbf1f818889686', 'b86970b74c8436d7694b27ac1c51176ef31eebcc85305d4e95f8b6d4f2f538bd']\n\nasserted puzzle announcements = ['0000000000000000000000000000000000000000000000000000000000000000', '632f30a65e0ed212dc0af6ec22099acf689a70ad4fe28e4166cbf1f818889686']\n\nsymdiff of puzzle announcements = ['0000000000000000000000000000000000000000000000000000000000000000', 'b86970b74c8436d7694b27ac1c51176ef31eebcc85305d4e95f8b6d4f2f538bd']\n\n\n================================================================================\n\naggregated signature check pass: True\npks: [<G1Element aa1a1c26055a329817a5759d877a2795f9499b97d6056edde0eea39512f24e8bc874b4471f0501127abb1ea0d9f68ac1>]\nmsgs: ['0000000000000000000000000000000000000000000000000000000000000000']\nadd_data: ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb\nsignature: a458f8f379a4bec00f36cd38e36790210f0b7c4ee772417c0cd20513d75c7505a0532d220ab03a471e9e255e2c54472a03abd31a9feb56d551bf482e31e48747b04fe90f4e3c2af98a2de0d11f869cde360f93b8efa37ec1c28950aa52bfbacd\n"  # noqa
    )
