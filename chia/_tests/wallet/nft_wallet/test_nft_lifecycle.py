from __future__ import annotations

import itertools
from typing import Any, cast

import pytest
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.program import Program, run
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.conditions import AssertPuzzleAnnouncement, CreateCoin, CreatePuzzleAnnouncement, UnknownCondition
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
from chia.wallet.nft_wallet.nft_puzzles import NFT_METADATA_UPDATER, NFT_TRANSFER_PROGRAM_DEFAULT
from chia.wallet.puzzles.puzzle_drivers import ACSPuzzle, ACSSolution, UnknownPuzzle, UnknownSolution
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
            metadata=METADATA.program, metadata_updater=METADATA_UPDATER, inner_puzzle=ACSPuzzle()
        )
        state_layer_ph = state_layer_puzzle.tree_hash
        await sim.farm_block(state_layer_ph)
        state_layer_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(state_layer_ph, include_spent_coins=False)
        )[0].coin

        generic_spend = make_spend(
            state_layer_coin,
            state_layer_puzzle.program,
            MetadataLayerSolution(ACSSolution(conditions=[CreateCoin(puzzle_hash=ACS_PH, amount=uint64(1))])).program,
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
                state_layer_puzzle.program,
                MetadataLayerSolution(
                    ACSSolution(conditions=[CreateCoin(puzzle_hash=ACS_PH, amount=uint64(1)), condition])
                ).program,
            )
            update_bundle = cost_logger.add_cost(
                "State layer only coin (metadata update) - one child created",
                WalletSpendBundle([update_spend], G2Element()),
            )
            result = await sim_client.push_tx(update_bundle)
            assert result == (MempoolInclusionStatus.SUCCESS, None)
            await sim.farm_block()
            state_layer_puzzle = MetadataLayer(
                metadata=metadata.program, metadata_updater=METADATA_UPDATER, inner_puzzle=ACSPuzzle()
            )


@pytest.mark.anyio
async def test_ownership_layer(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        TARGET_OWNER = bytes32.zeros
        TARGET_TP = Program.to([8])  # (x)
        # (a (i 11 (q 4 19 (c 43 (q ()))) (q 8)) 1) or
        # (mod (_ _ solution) (if solution (list (f solution) (f (r solution)) ()) (x)))
        transfer_program = UnknownPuzzle(
            known_program=Program.to([2, [3, 11, [1, 4, 19, [4, 43, [1, []]]], [1, 8]], 1])
        )

        ownership_puzzle = OwnershipLayer(
            current_owner=None, transfer_program=transfer_program, inner_puzzle=ACSPuzzle()
        )
        await sim.farm_block(ownership_puzzle.tree_hash)
        ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(ownership_puzzle.tree_hash, include_spent_coins=False)
        )[0].coin

        generic_spend = make_spend(
            ownership_coin,
            ownership_puzzle.program,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().tree_hash, amount=uint64(1)),
                        UnknownCondition(opcode=Program.to(-10), args=[Program.NIL, Program.NIL]),
                    ]
                )
            ).program,
        )
        generic_bundle = cost_logger.add_cost(
            "Ownership only coin - one child created", WalletSpendBundle([generic_spend], G2Element())
        )
        result = await sim_client.push_tx(generic_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(ownership_puzzle.tree_hash, include_spent_coins=False)
        )[0].coin

        skip_tp_spend = make_spend(
            ownership_coin,
            ownership_puzzle.program,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(conditions=[CreateCoin(puzzle_hash=ACSPuzzle().tree_hash, amount=uint64(1))])
            ).program,
        )
        skip_tp_bundle = WalletSpendBundle([skip_tp_spend], G2Element())

        result = await sim_client.push_tx(skip_tp_bundle)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
        with pytest.raises(ValueError, match="clvm raise"):
            run(skip_tp_spend.puzzle_reveal, Program.from_serialized(skip_tp_spend.solution))

        make_bad_announcement_spend = make_spend(
            ownership_coin,
            ownership_puzzle.program,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().tree_hash, amount=uint64(1)),
                        UnknownCondition(opcode=Program.to(-10), args=[Program.to(TARGET_OWNER), TARGET_TP]),
                        CreatePuzzleAnnouncement(msg=b"\xad\x4c" + bytes32.zeros),
                    ]
                )
            ).program,
        )
        make_bad_announcement_bundle = WalletSpendBundle([make_bad_announcement_spend], G2Element())

        result = await sim_client.push_tx(make_bad_announcement_bundle)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
        with pytest.raises(ValueError, match="clvm raise"):
            run(
                make_bad_announcement_spend.puzzle_reveal, Program.from_serialized(make_bad_announcement_spend.solution)
            )

        expected_announcement = AssertPuzzleAnnouncement(
            asserted_ph=ownership_puzzle.tree_hash,
            asserted_msg=b"\xad\x4c" + Program.to([TARGET_OWNER, TARGET_TP]).get_tree_hash(),
        )
        harmless_announcement = AssertPuzzleAnnouncement(
            asserted_ph=ownership_puzzle.tree_hash,
            asserted_msg=b"oy",
        )
        update_everything_spend = make_spend(
            ownership_coin,
            ownership_puzzle.program,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().tree_hash, amount=uint64(1)),
                        UnknownCondition(opcode=Program.to(-10), args=[Program.to(TARGET_OWNER), TARGET_TP]),
                        expected_announcement,
                        # create and assert a harmless puzzle announcement
                        harmless_announcement.corresponding_creation(),
                        harmless_announcement,
                    ]
                )
            ).program,
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
            transfer_program=UnknownPuzzle(known_program=TARGET_TP),
            inner_puzzle=ACSPuzzle(),
        ).tree_hash


@pytest.mark.anyio
async def test_default_transfer_program(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        # Now make the ownership coin
        FAKE_SINGLETON_MOD = Program.to([2, 5, 11])  # (a 5 11) | (mod (_ INNER_PUZ inner_sol) (a INNER_PUZ inner_sol))
        FAKE_CAT_MOD = Program.to([2, 11, 23])  # (a 11 23) or (mod (_ _ INNER_PUZ inner_sol) (a INNER_PUZ inner_sol))
        FAKE_LAUNCHER_ID = bytes32.zeros
        FAKE_TAIL = bytes32([2] * 32)
        FAKE_SINGLETON_STRUCT = Program.to((FAKE_SINGLETON_MOD.get_tree_hash(), (FAKE_LAUNCHER_ID, FAKE_LAUNCHER_ID)))
        FAKE_SINGLETON = FAKE_SINGLETON_MOD.curry(FAKE_SINGLETON_STRUCT, ACS)
        FAKE_CAT = FAKE_CAT_MOD.curry(FAKE_CAT_MOD.get_tree_hash(), FAKE_TAIL, ACS)

        ROYALTY_ADDRESS = bytes32([1] * 32)
        TRADE_PRICE_PERCENTAGE = 5000  # 50%
        # Build with a non-default singleton struct (fake mods), matching the pre-driver test shape.
        transfer_program_program: Program = NFT_TRANSFER_PROGRAM_DEFAULT.curry(
            FAKE_SINGLETON_STRUCT,
            ROYALTY_ADDRESS,
            TRADE_PRICE_PERCENTAGE,
        )
        ownership_puzzle = OwnershipLayer(
            current_owner=None,
            transfer_program=UnknownPuzzle(known_program=transfer_program_program),
            inner_puzzle=ACSPuzzle(),
        )
        await sim.farm_block(ownership_puzzle.tree_hash)
        ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(ownership_puzzle.tree_hash, include_spent_coins=False)
        )[0].coin

        BLOCK_HEIGHT = sim.block_height

        # Try a spend, no royalties, no owner update
        generic_spend = make_spend(
            ownership_coin,
            ownership_puzzle.program,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(conditions=[CreateCoin(puzzle_hash=ACSPuzzle().tree_hash, amount=uint64(1))])
            ).program,
        )
        generic_bundle = cost_logger.add_cost(
            "Ownership only coin (default NFT1 TP) - one child created", WalletSpendBundle([generic_spend], G2Element())
        )
        result = await sim_client.push_tx(generic_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        assert (
            len(await sim_client.get_coin_records_by_puzzle_hash(ownership_puzzle.tree_hash, include_spent_coins=False))
            > 0
        )
        await sim.rewind(BLOCK_HEIGHT)

        # Now try an owner update plus royalties
        await sim.farm_block(FAKE_SINGLETON.get_tree_hash())
        await sim.farm_block(FAKE_CAT.get_tree_hash())
        await sim.farm_block(ACS_PH)
        singleton_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(FAKE_SINGLETON.get_tree_hash(), include_spent_coins=False)
        )[0].coin
        cat_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(FAKE_CAT.get_tree_hash(), include_spent_coins=False)
        )[0].coin
        xch_coin = (await sim_client.get_coin_records_by_puzzle_hash(ACS_PH, include_spent_coins=False))[0].coin

        ownership_spend = make_spend(
            ownership_coin,
            ownership_puzzle.program,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().tree_hash, amount=uint64(1)),
                        TransferProgramCondition(
                            trade_prices_list={
                                ACS_PH: 100,
                                FAKE_CAT.get_tree_hash(): 100,
                            },
                            new_owner=FAKE_LAUNCHER_ID,
                            new_owner_inner_puzzle_hash=ACS_PH,
                        ),
                    ]
                )
            ).program,
        )

        did_announcement_spend = make_spend(
            singleton_coin,
            FAKE_SINGLETON,
            Program.to([ACSSolution(conditions=[CreatePuzzleAnnouncement(msg=FAKE_LAUNCHER_ID)]).program]),
        )

        expected_announcement_data = Program.to(
            (FAKE_LAUNCHER_ID, [[ROYALTY_ADDRESS, 50, [ROYALTY_ADDRESS]]])
        ).get_tree_hash()
        xch_announcement_spend = make_spend(
            xch_coin,
            ACS,
            ACSSolution(conditions=[CreatePuzzleAnnouncement(msg=expected_announcement_data)]).program,
        )

        cat_announcement_spend = make_spend(
            cat_coin,
            FAKE_CAT,
            Program.to([ACSSolution(conditions=[CreatePuzzleAnnouncement(msg=expected_announcement_data)]).program]),
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
            current_owner=FAKE_LAUNCHER_ID,
            transfer_program=UnknownPuzzle(known_program=transfer_program_program),
            inner_puzzle=ACSPuzzle(),
        )
        await sim.farm_block(new_ownership_puzzle.tree_hash)
        new_ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(new_ownership_puzzle.tree_hash, include_spent_coins=False)
        )[0].coin

        empty_spend = make_spend(
            new_ownership_coin,
            new_ownership_puzzle.program,
            OwnershipLayerSolution(
                inner_solution=ACSSolution(
                    conditions=[
                        CreateCoin(puzzle_hash=ACSPuzzle().tree_hash, amount=uint64(1)),
                        TransferProgramCondition(trade_prices_list={}),
                    ]
                )
            ).program,
        )
        empty_bundle = cost_logger.add_cost(
            "Ownership only coin (default NFT1 TP) - one child created + clear DID",
            WalletSpendBundle([empty_spend], G2Element()),
        )
        result = await sim_client.push_tx(empty_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()


def test_update_metadata_condition() -> None:
    for condition in (
        UpdateMetadataCondition(data_uri="https://example.com/data"),
        UpdateMetadataCondition(meta_uri="https://example.com/meta"),
        UpdateMetadataCondition(license_uri="https://example.com/license"),
    ):
        assert UpdateMetadataCondition.from_program(condition.to_program()) == condition

    with pytest.raises(ValueError, match="Only one of"):
        UpdateMetadataCondition(data_uri="a", meta_uri="b")
    with pytest.raises(ValueError, match="Only one of"):
        UpdateMetadataCondition()

    other = UpdateMetadataCondition(other_update=("foo", "bar"))
    assert other.to_program() == Program.to([-24, NFT_METADATA_UPDATER, (b"foo", "bar")])
    with pytest.raises(ValueError, match="Invalid key"):
        UpdateMetadataCondition.from_program(other.to_program())


def test_transfer_program_condition() -> None:
    owner = bytes32([1] * 32)
    inner = bytes32([2] * 32)
    asset_a = bytes32([3] * 32)
    asset_b = bytes32([4] * 32)

    empty = TransferProgramCondition(trade_prices_list={})
    assert TransferProgramCondition.from_program(empty.to_program()) == empty

    full = TransferProgramCondition(
        trade_prices_list={asset_a: 100, asset_b: 250},
        new_owner=owner,
        new_owner_inner_puzzle_hash=inner,
    )
    assert TransferProgramCondition.from_program(full.to_program()) == full
    assert full.to_program() == Program.to([-10, owner, [[100, asset_a], [250, asset_b]], inner])


def test_nft_metadata_ownership_driver_edge_cases() -> None:
    # other_update path is covered by lifecycle tests; unreachable else needs bypass of __post_init__
    unreachable = object.__new__(UpdateMetadataCondition)
    object.__setattr__(unreachable, "data_uri", None)
    object.__setattr__(unreachable, "meta_uri", None)
    object.__setattr__(unreachable, "license_uri", None)
    object.__setattr__(unreachable, "other_update", None)
    object.__setattr__(unreachable, "metadata_updater", DefaultMetadataUpdater())
    with pytest.raises(ValueError, match="One of data_uri, meta_uri, or license_uri must be provided"):
        unreachable.to_program()

    metadata = NFTMetadata(data_uris=["https://example.com"], data_hash=b"\x01" * 32)
    assert metadata.prepend_value(key=b"u", value="new").data_uris == ["new", "https://example.com"]
    assert metadata.prepend_value(key=b"mu", value="meta").meta_uris == ["meta"]
    assert metadata.prepend_value(key=b"lu", value="lic").license_uris == ["lic"]
    with pytest.raises(ValueError, match="Unsupported metadata key"):
        metadata.prepend_value(key=cast(Any, b"bad"), value="x")

    # other_update path in to_program
    assert UpdateMetadataCondition(other_update=("custom", "uri")).to_program() is not None

    # Atom and list forms of unrecognized metadata keys
    with_other = NFTMetadata.from_program(
        Program.to(
            [
                (b"u", ["https://a"]),
                (b"h", b"\x02" * 32),
                (b"custom-atom", b"value"),
                (b"custom-list", [b"a", b"b"]),
            ]
        )
    )
    assert with_other.other_metadata[b"custom-atom"] == b"value"
    assert with_other.other_metadata[b"custom-list"] == ["a", "b"]

    assert MetadataLayerSolution.match(unknown_solution=UnknownSolution(program=Program.to(1))) is None
    assert MetadataLayerSolution.match(unknown_solution=UnknownSolution(program=Program.to([1, 2]))) is None
    assert OwnershipLayerSolution.match(unknown_solution=UnknownSolution(program=Program.to(1))) is None
    assert OwnershipLayerSolution.match(unknown_solution=UnknownSolution(program=Program.to([1, 2]))) is None

    assert DefaultTransferProgram.match(unknown_puzzle=UnknownPuzzle(known_program=ACSPuzzle().program)) is None
    assert DefaultMetadataUpdater.match(unknown_puzzle=UnknownPuzzle(known_program=ACSPuzzle().program)) is None

    matched_updater = DefaultMetadataUpdater.match(
        unknown_puzzle=UnknownPuzzle(known_program=DefaultMetadataUpdater().program)
    )
    assert matched_updater == DefaultMetadataUpdater()

    transfer_program = DefaultTransferProgram(
        self_launcher_id=bytes32.zeros,
        royalty_address=bytes32([1] * 32),
        royalty_basis_points=300,
    )
    matched_tp = DefaultTransferProgram.match(unknown_puzzle=UnknownPuzzle(known_program=transfer_program.program))
    assert matched_tp == transfer_program

    ownership = OwnershipLayer(
        current_owner=None,
        transfer_program=transfer_program,
        inner_puzzle=ACSPuzzle(),
    )
    matched_ownership = OwnershipLayer.match(unknown_puzzle=UnknownPuzzle(known_program=ownership.program))
    assert matched_ownership is not None
    assert matched_ownership.current_owner is None
    assert DefaultTransferProgram.match(unknown_puzzle=matched_ownership.transfer_program) == transfer_program

    metadata_layer = MetadataLayer(
        metadata=NFTMetadata(data_uris=["u"], data_hash=b"\x00" * 32).program,
        metadata_updater=DefaultMetadataUpdater(),
        inner_puzzle=ownership,
    )
    matched_metadata = MetadataLayer.match(unknown_puzzle=UnknownPuzzle(known_program=metadata_layer.program))
    assert matched_metadata is not None
    assert matched_metadata.metadata == metadata_layer.metadata
    assert OwnershipLayer.match(unknown_puzzle=matched_metadata.inner_puzzle) is not None
