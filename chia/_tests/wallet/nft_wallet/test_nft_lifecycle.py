from __future__ import annotations

import itertools

import pytest
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.program import Program, run
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.cat_wallet.cat_utils import CATCorePuzzles, CATPuzzle
from chia.wallet.conditions import (
    AssertPuzzleAnnouncement,
    CreateCoin,
    CreatePuzzleAnnouncement,
    UnknownCondition,
)
from chia.wallet.nft_wallet.nft_puzzle_utils import (
    DefaultMetadataUpdater,
    DefaultTransferProgram,
    MetadataLayer,
    MetadataLayerSolution,
    NFTMetadata,
    OwnershipLayer,
    OwnershipLayerSolution,
    TransferProgramCondition,
    UpdateMetadataCondition,
)
from chia.wallet.puzzles.puzzle_drivers import ACSPuzzle, ACSSolution, UnknownPuzzle
from chia.wallet.puzzles.singleton_drivers import (
    SingletonCorePuzzles,
    SingletonPuzzle,
    SingletonStruct,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


@pytest.mark.anyio
@pytest.mark.parametrize("metadata_updater", ["default"])
async def test_state_layer(cost_logger: CostLogger, metadata_updater: str) -> None:
    async with sim_and_client() as (sim, sim_client):
        if metadata_updater == "default":
            METADATA = NFTMetadata(
                data_uris=["hey hey"],
                data_hash=bytes32.zeros,
                license_uris=["You have no permissions grr"],
                meta_uris=["This but off chain"],
                other_metadata={b"foo": ["can't update this"]},
            )
            METADATA_UPDATER = DefaultMetadataUpdater()
        else:
            # TODO: Add test for updateable
            return

        state_layer_puzzle = MetadataLayer(
            metadata=METADATA.as_program(), metadata_updater=METADATA_UPDATER, inner_puzzle=ACSPuzzle()
        )
        state_layer_ph = state_layer_puzzle.puzzle_hash
        await sim.farm_block(state_layer_ph)
        state_layer_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(state_layer_ph, include_spent_coins=False)
        )[0].coin

        generic_spend = make_spend(
            state_layer_coin,
            state_layer_puzzle.puzzle,
            MetadataLayerSolution(
                ACSSolution(conditions=[CreateCoin(puzzle_hash=ACS_PH, amount=uint64(1))])
            ).as_program(),
        )
        generic_bundle = cost_logger.add_cost(
            "State layer only coin - one child created", WalletSpendBundle([generic_spend], G2Element())
        )

        result = await sim_client.push_tx(generic_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()

        if metadata_updater == "default":
            metadata_updater_solutions: list[UpdateMetadataCondition] = [
                UpdateMetadataCondition(data_uri="update"),
                UpdateMetadataCondition(license_uri="update"),
                UpdateMetadataCondition(meta_uri="update"),
                UpdateMetadataCondition(other_update=("foo", "update")),
            ]
            expected_metadatas: list[NFTMetadata] = [
                NFTMetadata(
                    data_uris=["update", "hey hey"],
                    data_hash=bytes32.zeros,
                    license_uris=["You have no permissions grr"],
                    meta_uris=["This but off chain"],
                    other_metadata={b"foo": ["can't update this"]},
                ),
                NFTMetadata(
                    data_uris=["update", "hey hey"],
                    data_hash=bytes32.zeros,
                    license_uris=["update", "You have no permissions grr"],
                    meta_uris=["This but off chain"],
                    other_metadata={b"foo": ["can't update this"]},
                ),
                NFTMetadata(
                    data_uris=["update", "hey hey"],
                    data_hash=bytes32.zeros,
                    license_uris=["update", "You have no permissions grr"],
                    meta_uris=["update", "This but off chain"],
                    other_metadata={b"foo": ["can't update this"]},
                ),
                NFTMetadata(
                    data_uris=["update", "hey hey"],
                    data_hash=bytes32.zeros,
                    license_uris=["update", "You have no permissions grr"],
                    meta_uris=["update", "This but off chain"],
                    other_metadata={b"foo": ["can't update this"]},
                ),
            ]
        else:
            return

        for condition, metadata in zip(metadata_updater_solutions, expected_metadatas):
            state_layer_coin = (
                await sim_client.get_coin_records_by_parent_ids([state_layer_coin.name()], include_spent_coins=False)
            )[0].coin
            update_spend = make_spend(
                state_layer_coin,
                state_layer_puzzle.puzzle,
                MetadataLayerSolution(
                    ACSSolution(conditions=[CreateCoin(puzzle_hash=ACS_PH, amount=uint64(1)), condition])
                ).as_program(),
            )
            update_bundle = cost_logger.add_cost(
                "State layer only coin (metadata update) - one child created",
                WalletSpendBundle([update_spend], G2Element()),
            )
            result = await sim_client.push_tx(update_bundle)
            assert result == (MempoolInclusionStatus.SUCCESS, None)
            await sim.farm_block()
            state_layer_puzzle = MetadataLayer(
                metadata=metadata.as_program(), metadata_updater=METADATA_UPDATER, inner_puzzle=ACSPuzzle()
            )


@pytest.mark.anyio
async def test_ownership_layer(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        TARGET_OWNER = bytes32.zeros
        TARGET_TP = Program.to([8])  # (x)
        # (a (i 11 (q 4 19 (c 43 (q ()))) (q 8)) 1) or
        # (mod (_ _ solution) (if solution (list (f solution) (f (r solution)) ()) (x)))
        transfer_program = UnknownPuzzle(known_puzzle=Program.to([2, [3, 11, [1, 4, 19, [4, 43, [1, []]]], [1, 8]], 1]))

        ownership_puzzle = OwnershipLayer(
            current_owner=None, transfer_program=transfer_program, inner_puzzle=ACSPuzzle()
        )
        await sim.farm_block(ownership_puzzle.puzzle_hash)
        ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(ownership_puzzle.puzzle_hash, include_spent_coins=False)
        )[0].coin

        generic_spend = make_spend(
            ownership_coin,
            ownership_puzzle.puzzle,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().puzzle_hash, amount=uint64(1)),
                        UnknownCondition(opcode=Program.to(-10), args=[Program.NIL, Program.NIL]),
                    ]
                )
            ).as_program(),
        )
        generic_bundle = cost_logger.add_cost(
            "Ownership only coin - one child created", WalletSpendBundle([generic_spend], G2Element())
        )
        result = await sim_client.push_tx(generic_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(ownership_puzzle.puzzle_hash, include_spent_coins=False)
        )[0].coin

        skip_tp_spend = make_spend(
            ownership_coin,
            ownership_puzzle.puzzle,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[CreateCoin(puzzle_hash=ACSPuzzle().puzzle_hash, amount=uint64(1))]
                )
            ).as_program(),
        )
        skip_tp_bundle = WalletSpendBundle([skip_tp_spend], G2Element())

        result = await sim_client.push_tx(skip_tp_bundle)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
        with pytest.raises(ValueError, match="clvm raise"):
            run(skip_tp_spend.puzzle_reveal, Program.from_serialized(skip_tp_spend.solution))

        make_bad_announcement_spend = make_spend(
            ownership_coin,
            ownership_puzzle.puzzle,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().puzzle_hash, amount=uint64(1)),
                        UnknownCondition(opcode=Program.to(-10), args=[Program.to(TARGET_OWNER), TARGET_TP]),
                        CreatePuzzleAnnouncement(msg=b"\xad\x4c" + bytes32.zeros),
                    ]
                )
            ).as_program(),
        )
        make_bad_announcement_bundle = WalletSpendBundle([make_bad_announcement_spend], G2Element())

        result = await sim_client.push_tx(make_bad_announcement_bundle)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
        with pytest.raises(ValueError, match="clvm raise"):
            run(
                make_bad_announcement_spend.puzzle_reveal, Program.from_serialized(make_bad_announcement_spend.solution)
            )

        expected_announcement = AssertPuzzleAnnouncement(
            asserted_ph=ownership_puzzle.puzzle_hash,
            asserted_msg=b"\xad\x4c" + Program.to([TARGET_OWNER, TARGET_TP]).get_tree_hash(),
        )
        harmless_announcement = AssertPuzzleAnnouncement(
            asserted_ph=ownership_puzzle.puzzle_hash,
            asserted_msg=b"oy",
        )
        update_everything_spend = make_spend(
            ownership_coin,
            ownership_puzzle.puzzle,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().puzzle_hash, amount=uint64(1)),
                        UnknownCondition(opcode=Program.to(-10), args=[Program.to(TARGET_OWNER), TARGET_TP]),
                        expected_announcement,
                        # create and assert a harmless puzzle announcement
                        harmless_announcement.corresponding_creation(),
                        harmless_announcement,
                    ]
                )
            ).as_program(),
        )
        update_everything_bundle = cost_logger.add_cost(
            "Ownership only coin (update owner and TP) - one child + 3 announcements created",
            WalletSpendBundle([update_everything_spend], G2Element()),
        )
        result = await sim_client.push_tx(update_everything_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        assert (await sim_client.get_coin_records_by_parent_ids([ownership_coin.name()], include_spent_coins=False))[
            0
        ].coin.puzzle_hash == OwnershipLayer(
            current_owner=TARGET_OWNER,
            transfer_program=UnknownPuzzle(known_puzzle=TARGET_TP),
            inner_puzzle=ACSPuzzle(),
        ).puzzle_hash


@pytest.mark.anyio
async def test_default_transfer_program(cost_logger: CostLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    FAKE_SINGLETON_MOD = Program.to([2, 5, 11])  # (a 5 11) | (mod (_ INNER_PUZ inner_sol) (a INNER_PUZ inner_sol))
    FAKE_CAT_MOD = Program.to([2, 11, 23])  # (a 11 23) or (mod (_ _ INNER_PUZ inner_sol) (a INNER_PUZ inner_sol))
    FAKE_TAIL = bytes32([2] * 32)
    monkeypatch.setattr(
        SingletonStruct,
        "singleton_puzzles",
        SingletonCorePuzzles(
            singleton_mod=FAKE_SINGLETON_MOD,
            singleton_mod_hash_pre_computed=None,
            hash_of_quoted_mod_hash_pre_computed=None,
        ),
    )
    monkeypatch.setattr(
        CATPuzzle,
        "cat_puzzles",
        CATCorePuzzles(cat_mod=FAKE_CAT_MOD, cat_mod_hash_pre_computed=None, hash_of_quoted_mod_hash_pre_computed=None),
    )
    FAKE_SINGLETON = SingletonPuzzle(launcher_id=bytes32.zeros, inner_puzzle=ACSPuzzle())
    FAKE_CAT = CATPuzzle(tail_hash=FAKE_TAIL, inner_puzzle=ACSPuzzle())
    async with sim_and_client() as (sim, sim_client):
        # Now make the ownership coin

        ROYALTY_ADDRESS = bytes32([1] * 32)
        TRADE_PRICE_PERCENTAGE = 5000  # 50%
        transfer_program = DefaultTransferProgram(
            self_launcher_id=FAKE_SINGLETON.launcher_id,
            royalty_address=ROYALTY_ADDRESS,
            royalty_basis_points=TRADE_PRICE_PERCENTAGE,
        )
        ownership_puzzle = OwnershipLayer(
            current_owner=None,
            transfer_program=transfer_program,
            inner_puzzle=ACSPuzzle(),
        )
        await sim.farm_block(ownership_puzzle.puzzle_hash)
        ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(ownership_puzzle.puzzle_hash, include_spent_coins=False)
        )[0].coin

        BLOCK_HEIGHT = sim.block_height

        # Try a spend, no royalties, no owner update
        generic_spend = make_spend(
            ownership_coin,
            ownership_puzzle.puzzle,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[CreateCoin(puzzle_hash=ACSPuzzle().puzzle_hash, amount=uint64(1))]
                )
            ).as_program(),
        )
        generic_bundle = cost_logger.add_cost(
            "Ownership only coin (default NFT1 TP) - one child created", WalletSpendBundle([generic_spend], G2Element())
        )
        result = await sim_client.push_tx(generic_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        assert (
            len(
                await sim_client.get_coin_records_by_puzzle_hash(
                    ownership_puzzle.puzzle_hash, include_spent_coins=False
                )
            )
            > 0
        )
        await sim.rewind(BLOCK_HEIGHT)

        # Now try an owner update plus royalties
        await sim.farm_block(FAKE_SINGLETON.puzzle_hash)
        await sim.farm_block(FAKE_CAT.puzzle_hash)
        await sim.farm_block(ACS_PH)
        singleton_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(FAKE_SINGLETON.puzzle_hash, include_spent_coins=False)
        )[0].coin
        cat_coin = (await sim_client.get_coin_records_by_puzzle_hash(FAKE_CAT.puzzle_hash, include_spent_coins=False))[
            0
        ].coin
        xch_coin = (await sim_client.get_coin_records_by_puzzle_hash(ACS_PH, include_spent_coins=False))[0].coin

        ownership_spend = make_spend(
            ownership_coin,
            ownership_puzzle.puzzle,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().puzzle_hash, amount=uint64(1)),
                        TransferProgramCondition(
                            trade_prices_list={ACSPuzzle().puzzle_hash: 100, FAKE_CAT.puzzle_hash: 100},
                            new_owner=FAKE_SINGLETON,
                        ),
                    ]
                )
            ).as_program(),
        )

        did_announcement_spend = make_spend(
            singleton_coin,
            FAKE_SINGLETON.puzzle,
            Program.to(
                [ACSSolution(conditions=[CreatePuzzleAnnouncement(msg=FAKE_SINGLETON.launcher_id)]).as_program()]
            ),
        )

        expected_announcement_data = Program.to(
            (FAKE_SINGLETON.launcher_id, [[ROYALTY_ADDRESS, 50, [ROYALTY_ADDRESS]]])
        ).get_tree_hash()
        xch_announcement_spend = make_spend(
            xch_coin,
            ACS,
            ACSSolution(conditions=[CreatePuzzleAnnouncement(msg=expected_announcement_data)]).as_program(),
        )

        cat_announcement_spend = make_spend(
            cat_coin,
            FAKE_CAT.puzzle,
            Program.to(
                [ACSSolution(conditions=[CreatePuzzleAnnouncement(msg=expected_announcement_data)]).as_program()]
            ),
        )

        # Make sure every combo except all of them fail
        for i in range(1, 3):
            for announcement_combo in itertools.combinations(
                [did_announcement_spend, xch_announcement_spend, cat_announcement_spend], i
            ):
                result = await sim_client.push_tx(
                    WalletSpendBundle([ownership_spend, *announcement_combo], G2Element())
                )
                assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

        # Make sure all of them together pass
        full_bundle = cost_logger.add_cost(
            "Ownership only coin (default NFT1 TP) - one child created + update DID + offer CATs + offer XCH",
            WalletSpendBundle(
                [ownership_spend, did_announcement_spend, xch_announcement_spend, cat_announcement_spend], G2Element()
            ),
        )
        result = await sim_client.push_tx(full_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # Finally, make sure we can just clear the DID label off
        new_ownership_puzzle = OwnershipLayer(
            current_owner=FAKE_SINGLETON.launcher_id,
            transfer_program=transfer_program,
            inner_puzzle=ACSPuzzle(),
        )
        await sim.farm_block(new_ownership_puzzle.puzzle_hash)
        new_ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(
                new_ownership_puzzle.puzzle_hash, include_spent_coins=False
            )
        )[0].coin

        empty_spend = make_spend(
            new_ownership_coin,
            new_ownership_puzzle.puzzle,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().puzzle_hash, amount=uint64(1)),
                        TransferProgramCondition(trade_prices_list={}, new_owner=None),
                    ]
                )
            ).as_program(),
        )
        empty_bundle = cost_logger.add_cost(
            "Ownership only coin (default NFT1 TP) - one child created + clear DID",
            WalletSpendBundle([empty_spend], G2Element()),
        )
        result = await sim_client.push_tx(empty_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
