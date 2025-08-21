from __future__ import annotations

import pytest

from chia.apis.farmer_stub import FarmerApiStub
from chia.apis.full_node_stub import FullNodeApiStub
from chia.apis.harvester_stub import HarvesterApiStub
from chia.apis.introducer_stub import IntroducerApiStub
from chia.apis.timelord_stub import TimelordApiStub
from chia.apis.wallet_stub import WalletNodeApiStub


# Dummy argument classes for protocol methods
class Dummy:
    def __bytes__(self):
        return b""


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,args",
    [
        # HarvesterAPIStub missing coverage
        ("harvester_handshake", (Dummy(), Dummy())),
        ("new_signage_point_harvester", (Dummy(), Dummy())),
        ("request_signatures", (Dummy(),)),
        ("request_plots", (Dummy(),)),
        ("plot_sync_response", (Dummy(),)),
    ],
)
async def test_harvester_stub_raises(method, args):
    stub = HarvesterApiStub()
    with pytest.raises(NotImplementedError):
        await getattr(stub, method)(*args)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,args",
    [
        # HarvesterAPIStub plot sync methods
        ("new_proof_of_space", (Dummy(), Dummy())),
        ("respond_signatures", (Dummy(),)),
        ("new_signage_point", (Dummy(),)),
        ("farming_info", (Dummy(), Dummy())),
        ("respond_plots", (Dummy(), Dummy())),
        ("plot_sync_start", (Dummy(), Dummy())),
        ("plot_sync_loaded", (Dummy(), Dummy())),
        ("plot_sync_removed", (Dummy(), Dummy())),
        ("plot_sync_invalid", (Dummy(), Dummy())),
        ("plot_sync_keys_missing", (Dummy(), Dummy())),
        ("plot_sync_duplicates", (Dummy(), Dummy())),
        ("plot_sync_done", (Dummy(), Dummy())),
    ],
)
async def test_farmer_stub_raises(method, args):
    stub = FarmerApiStub()
    with pytest.raises(NotImplementedError):
        await getattr(stub, method)(*args)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,args",
    [
        # IntroducerAPIStub missing coverage
        ("request_peers_introducer", (Dummy(), Dummy())),
    ],
)
async def test_introducer_stub_raises(method, args):
    stub = IntroducerApiStub()
    with pytest.raises(NotImplementedError):
        await getattr(stub, method)(*args)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,args",
    [
        # TimelordAPIStub missing coverage
        ("new_peak_timelord", (Dummy(),)),
        ("new_unfinished_block_timelord", (Dummy(),)),
        ("request_compact_proof_of_time", (Dummy(),)),
    ],
)
async def test_timelord_stub_raises(method, args):
    stub = TimelordApiStub()
    with pytest.raises(NotImplementedError):
        await getattr(stub, method)(*args)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,args,kwargs",
    [
        # FullNodeAPIStub missing coverage
        ("request_peers", (Dummy(), Dummy()), {}),
        ("respond_peers", (Dummy(), Dummy()), {}),
        ("respond_peers_introducer", (Dummy(), Dummy()), {}),
        ("new_peak", (Dummy(), Dummy()), {}),
        ("new_transaction", (Dummy(), Dummy()), {}),
        ("request_transaction", (Dummy(),), {}),
        ("respond_transaction", (Dummy(), Dummy()), {"tx_bytes": b""}),
        ("request_proof_of_weight", (Dummy(),), {}),
        ("respond_proof_of_weight", (Dummy(),), {}),
        ("request_block", (Dummy(),), {}),
        ("request_blocks", (Dummy(),), {}),
        ("reject_block", (Dummy(), Dummy()), {}),
        ("reject_blocks", (Dummy(), Dummy()), {}),
        ("respond_blocks", (Dummy(), Dummy()), {}),
        ("respond_block", (Dummy(), Dummy()), {}),
        ("new_unfinished_block", (Dummy(),), {}),
        ("request_unfinished_block", (Dummy(),), {}),
        ("new_unfinished_block2", (Dummy(),), {}),
        ("request_unfinished_block2", (Dummy(),), {}),
        ("respond_unfinished_block", (Dummy(), Dummy()), {}),
        ("new_signage_point_or_end_of_sub_slot", (Dummy(), Dummy()), {}),
        ("request_signage_point_or_end_of_sub_slot", (Dummy(),), {}),
        ("respond_signage_point", (Dummy(), Dummy()), {}),
        ("respond_end_of_sub_slot", (Dummy(), Dummy()), {}),
        ("request_mempool_transactions", (Dummy(), Dummy()), {}),
        ("declare_proof_of_space", (Dummy(), Dummy()), {}),
        ("signed_values", (Dummy(), Dummy()), {}),
        ("new_infusion_point_vdf", (Dummy(), Dummy()), {}),
        ("new_signage_point_vdf", (Dummy(), Dummy()), {}),
        ("new_end_of_sub_slot_vdf", (Dummy(), Dummy()), {}),
        ("request_block_header", (Dummy(),), {}),
        ("request_additions", (Dummy(),), {}),
        ("request_removals", (Dummy(),), {}),
        ("send_transaction", (Dummy(),), {}),
        ("request_puzzle_solution", (Dummy(),), {}),
        ("request_block_headers", (Dummy(),), {}),
        ("request_header_blocks", (Dummy(),), {}),
        ("respond_compact_proof_of_time", (Dummy(),), {"request_bytes": b""}),
        ("new_compact_vdf", (Dummy(), Dummy()), {"request_bytes": b""}),
        ("request_compact_vdf", (Dummy(), Dummy()), {}),
        ("respond_compact_vdf", (Dummy(), Dummy()), {}),
        ("register_for_ph_updates", (Dummy(), Dummy()), {}),
        ("register_for_coin_updates", (Dummy(), Dummy()), {}),
        ("request_children", (Dummy(),), {}),
        ("request_ses_hashes", (Dummy(),), {}),
        ("request_fee_estimates", (Dummy(),), {}),
        ("request_remove_puzzle_subscriptions", (Dummy(), Dummy()), {}),
        ("request_remove_coin_subscriptions", (Dummy(), Dummy()), {}),
        ("request_puzzle_state", (Dummy(), Dummy()), {}),
        ("request_coin_state", (Dummy(), Dummy()), {}),
        ("request_cost_info", (Dummy(),), {}),
    ],
)
async def test_full_node_stub_raises(method, args, kwargs):
    stub = FullNodeApiStub()
    with pytest.raises(NotImplementedError):
        await getattr(stub, method)(*args, **kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,args,returns_none",
    [
        # WalletAPIStub missing coverage
        ("respond_removals", (Dummy(), Dummy()), False),
        ("reject_removals_request", (Dummy(), Dummy()), False),
        ("reject_additions_request", (Dummy(),), False),
        ("new_peak_wallet", (Dummy(), Dummy()), False),
        ("reject_header_request", (Dummy(),), False),
        ("respond_block_header", (Dummy(),), False),
        ("respond_additions", (Dummy(), Dummy()), False),
        ("respond_proof_of_weight", (Dummy(),), False),
        ("transaction_ack", (Dummy(), Dummy()), True),
        ("respond_peers_introducer", (Dummy(), Dummy()), False),
        ("respond_peers", (Dummy(), Dummy()), True),
        ("respond_puzzle_solution", (Dummy(),), False),
        ("reject_puzzle_solution", (Dummy(),), False),
        ("respond_header_blocks", (Dummy(),), False),
        ("respond_block_headers", (Dummy(),), False),
        ("reject_header_blocks", (Dummy(),), False),
        ("reject_block_headers", (Dummy(),), False),
        ("coin_state_update", (Dummy(), Dummy()), False),
        ("respond_to_ph_updates", (Dummy(),), False),
        ("respond_to_coin_updates", (Dummy(),), False),
        ("respond_children", (Dummy(),), False),
        ("respond_ses_hashes", (Dummy(),), False),
        ("respond_blocks", (Dummy(),), False),
    ],
)
async def test_wallet_stub_raises_or_none(method, args, returns_none):
    stub = WalletNodeApiStub()
    if returns_none:
        result = await getattr(stub, method)(*args)
        assert result is None
    else:
        with pytest.raises(NotImplementedError):
            await getattr(stub, method)(*args)
