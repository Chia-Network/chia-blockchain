from typing import List

from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle_conditions import Spend, SpendBundleConditions
from chia.util.generator_tools import tx_removals_and_additions, tx_removals_additions_and_hints
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint32

coin_ids = [std_hash(i.to_bytes(4, "big")) for i in range(10)]
phs = [std_hash(i.to_bytes(4, "big")) for i in range(10)]
spends: List[Spend] = [
    Spend(
        coin_ids[0],
        phs[0],
        None,
        uint64(5),
        [
            (phs[2], uint64(123), b""),
            (phs[3], uint64(0), b"1" * 300),
            (phs[4], uint64(0), b"1" * 300),
        ],
        [],
    ),
    Spend(
        coin_ids[1],
        phs[0],
        None,
        uint64(2),
        [
            (phs[5], uint64(123), b""),
            (phs[6], uint64(0), b"1" * 300),
            (phs[7], uint64(0), b"1" * 300),
        ],
        [],
    ),
]


class TestGeneratorTools:
    def test_tx_removals_and_additions(self) -> None:
        conditions = SpendBundleConditions(spends, uint64(0), uint32(0), uint64(0), [], uint64(0))
        expected_rems = [coin_ids[0], coin_ids[1]]
        expected_additions = []
        for spend in spends:
            for puzzle_hash, am, _ in spend.create_coin:
                expected_additions.append(Coin(spend.coin_id, puzzle_hash, am))
        rems, adds = tx_removals_and_additions(conditions)
        assert rems == expected_rems
        assert adds == expected_additions

    def test_empty_conditions(self) -> None:
        assert tx_removals_and_additions(None) == ([], [])

    def test_tx_removals_additions_and_hints(self) -> None:
        conditions = SpendBundleConditions(spends, uint64(0), uint32(0), uint64(0), [], uint64(0))
        expected_rems = [(coin_ids[0], phs[0]), (coin_ids[1], phs[0])]
        expected_additions = []
        for spend in spends:
            for puzzle_hash, am, hint in spend.create_coin:
                expected_additions.append((Coin(spend.coin_id, puzzle_hash, am), hint))
        assert tx_removals_additions_and_hints(conditions) == (expected_rems, expected_additions)

    def test_empty_tx_removals_additions_and_hints(self) -> None:
        assert tx_removals_additions_and_hints(None) == ([], [])
