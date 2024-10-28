from __future__ import annotations

import pytest
from chia_rs import G2Element

from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.wallet.conditions import CreateCoin
from chia.wallet.puzzles import p2_singleton_via_delegated_puzzle_safe as dp_safe
from chia.wallet.util.curry_and_treehash import shatree_atom

ACS = Program.to(1)
ACS_HASH = ACS.get_tree_hash()

MOCK_SINGLETON_MOD = Program.to([2, 5, 7])  # (a 5 11) - (mod (_ PUZZLE . solution) (a PUZZLE solution))
MOCK_SINGLETON_MOD_HASH = MOCK_SINGLETON_MOD.get_tree_hash()
MOCK_SINGLETON_LAUNCHER_ID = bytes32([0] * 32)
MOCK_SINGLETON_LAUNCHER_HASH = bytes32([1] * 32)
MOCK_SINGLETON = MOCK_SINGLETON_MOD.curry(
    Program.to((MOCK_SINGLETON_MOD_HASH, (MOCK_SINGLETON_LAUNCHER_ID, MOCK_SINGLETON_LAUNCHER_HASH))),
    ACS,
)
MOCK_SINGLETON_HASH = MOCK_SINGLETON.get_tree_hash()
dp_safe.PRE_HASHED_HASHES[MOCK_SINGLETON_MOD_HASH] = shatree_atom(MOCK_SINGLETON_MOD_HASH)
dp_safe.PRE_HASHED_HASHES[MOCK_SINGLETON_LAUNCHER_HASH] = shatree_atom(MOCK_SINGLETON_LAUNCHER_HASH)


@pytest.mark.anyio
async def test_dp_safe_lifecycle(cost_logger: CostLogger) -> None:
    P2_SINGLETON = dp_safe.construct(MOCK_SINGLETON_LAUNCHER_ID, MOCK_SINGLETON_MOD_HASH, MOCK_SINGLETON_LAUNCHER_HASH)
    P2_SINGLETON_HASH = dp_safe.construct_hash(
        MOCK_SINGLETON_LAUNCHER_ID, MOCK_SINGLETON_MOD_HASH, MOCK_SINGLETON_LAUNCHER_HASH
    )
    assert dp_safe.match(P2_SINGLETON) is not None
    assert dp_safe.match(ACS) is None
    assert dp_safe.match(MOCK_SINGLETON) is None

    async with sim_and_client() as (sim, sim_client):
        await sim.farm_block(P2_SINGLETON_HASH)
        await sim.farm_block(MOCK_SINGLETON_HASH)
        p2_singleton = (await sim_client.get_coin_records_by_puzzle_hash(P2_SINGLETON_HASH, include_spent_coins=False))[
            0
        ].coin
        singleton = (await sim_client.get_coin_records_by_puzzle_hash(MOCK_SINGLETON_HASH, include_spent_coins=False))[
            0
        ].coin

        dp = Program.to(1)
        dp_hash = dp.get_tree_hash()
        bundle = cost_logger.add_cost(
            "p2_singleton_w_mock_singleton",
            SpendBundle(
                [
                    make_spend(
                        p2_singleton,
                        P2_SINGLETON,
                        dp_safe.solve(
                            ACS_HASH,
                            dp,
                            Program.to([CreateCoin(bytes32([0] * 32), uint64(0)).to_program()]),
                            p2_singleton.name(),
                        ),
                    ),
                    make_spend(
                        singleton,
                        MOCK_SINGLETON,
                        Program.to([dp_safe.required_announcement(dp_hash, p2_singleton.name()).to_program()]),
                    ),
                ],
                G2Element(),
            ),
        )
        result = await sim_client.push_tx(bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        checkpoint = sim.block_height
        await sim.farm_block()

        assert len(await sim_client.get_coin_records_by_puzzle_hash(bytes32([0] * 32), include_spent_coins=False)) == 1

        await sim.rewind(checkpoint)

        result = await sim_client.push_tx(
            SpendBundle(
                [
                    make_spend(
                        p2_singleton,
                        P2_SINGLETON,
                        dp_safe.solve(
                            ACS_HASH,
                            dp,
                            Program.to([CreateCoin(bytes32([0] * 32), uint64(0)).to_program()]),
                            bytes32([0] * 32),
                        ),
                    ),
                    make_spend(
                        singleton,
                        MOCK_SINGLETON,
                        Program.to([dp_safe.required_announcement(dp_hash, p2_singleton.name()).to_program()]),
                    ),
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_MY_COIN_ID_FAILED)

        result = await sim_client.push_tx(
            SpendBundle(
                [
                    make_spend(
                        p2_singleton,
                        P2_SINGLETON,
                        dp_safe.solve(
                            ACS_HASH,
                            dp,
                            Program.to([CreateCoin(bytes32([0] * 32), uint64(0)).to_program()]),
                            p2_singleton.name(),
                        ),
                    ),
                    make_spend(
                        singleton,
                        MOCK_SINGLETON,
                        Program.to([]),
                    ),
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

        result = await sim_client.push_tx(
            SpendBundle(
                [
                    make_spend(
                        p2_singleton,
                        P2_SINGLETON,
                        dp_safe.solve(
                            ACS_HASH,
                            dp,
                            Program.to([CreateCoin(bytes32([0] * 32), uint64(0)).to_program()]),
                            p2_singleton.name(),
                        ),
                    ),
                    make_spend(
                        singleton,
                        MOCK_SINGLETON,
                        Program.to([dp_safe.required_announcement(dp_hash, bytes32([0] * 32)).to_program()]),
                    ),
                ],
                G2Element(),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)
