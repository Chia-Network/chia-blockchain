"""
Tests to exercise every RpcError raise site.

Each test directly instantiates (or mocks) the relevant RPC API class and calls a method
that triggers the error path, verifying that RpcError is raised with the expected error code.
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chia.rpc.rpc_errors import RpcError, RpcErrorCodes


# ──────────────────────────────────────────────────────────────────────────────
# data_layer_rpc_api.py
# ──────────────────────────────────────────────────────────────────────────────
class TestDataLayerRpcApiErrors:
    """Cover all RpcError raises in data_layer_rpc_api.py."""

    def _make_api(self, *, service: Any = None) -> Any:
        from chia.data_layer.data_layer_rpc_api import DataLayerRpcApi

        api = DataLayerRpcApi.__new__(DataLayerRpcApi)
        api.service = service
        return api

    @pytest.mark.anyio
    async def test_wallet_log_in_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.wallet_log_in({"fingerprint": 123})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_create_data_store_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.create_data_store({})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_owned_stores_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_owned_stores({})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_value_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_value({"id": "aa" * 32, "key": "0x01"})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_keys_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_keys({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_keys_cannot_find(self) -> None:
        """When keys=[] for a non-zero root_hash, raise CANNOT_FIND_KEYS."""
        svc = AsyncMock()
        svc.get_keys = AsyncMock(return_value=[])
        api = self._make_api(service=svc)
        root_hash = "bb" * 32
        with pytest.raises(RpcError, match="Can't find keys") as exc_info:
            await api.get_keys({"id": "aa" * 32, "root_hash": root_hash})
        assert exc_info.value.error_code == RpcErrorCodes.CANNOT_FIND_KEYS.value

    @pytest.mark.anyio
    async def test_get_keys_values_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_keys_values({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_keys_values_cannot_find(self) -> None:
        """When keys_values=[] for a non-zero root_hash, raise CANNOT_FIND_KEYS_AND_VALUES."""
        svc = AsyncMock()
        svc.get_keys_values = AsyncMock(return_value=[])
        api = self._make_api(service=svc)
        root_hash = "bb" * 32
        with pytest.raises(RpcError, match="Can't find keys and values") as exc_info:
            await api.get_keys_values({"id": "aa" * 32, "root_hash": root_hash})
        assert exc_info.value.error_code == RpcErrorCodes.CANNOT_FIND_KEYS_AND_VALUES.value

    @pytest.mark.anyio
    async def test_get_ancestors_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_ancestors({"id": "aa" * 32, "hash": "bb" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_batch_update_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.batch_update({"id": "aa" * 32, "changelist": []})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_batch_update_failed(self) -> None:
        """submit_on_chain=True but transaction_record is None => BATCH_UPDATE_FAILED."""
        svc = AsyncMock()
        svc.batch_update = AsyncMock(return_value=None)
        api = self._make_api(service=svc)
        with pytest.raises(RpcError, match="Batch update failed") as exc_info:
            await api.batch_update({"id": "aa" * 32, "changelist": [], "submit_on_chain": True})
        assert exc_info.value.error_code == RpcErrorCodes.BATCH_UPDATE_FAILED.value

    @pytest.mark.anyio
    async def test_batch_update_submit_false_but_submitted(self) -> None:
        """submit_on_chain=False but transaction_record is not None => error."""
        svc = AsyncMock()
        svc.batch_update = AsyncMock(return_value=MagicMock(name="tx_record"))
        api = self._make_api(service=svc)
        with pytest.raises(RpcError, match="submit_on_chain set to False") as exc_info:
            await api.batch_update({"id": "aa" * 32, "changelist": [], "submit_on_chain": False})
        assert exc_info.value.error_code == RpcErrorCodes.SUBMIT_ON_CHAIN_FALSE_BUT_SUBMITTED.value

    @pytest.mark.anyio
    async def test_multistore_batch_update_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.multistore_batch_update({"store_updates": [], "submit_on_chain": True})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_multistore_batch_update_failed(self) -> None:
        svc = AsyncMock()
        svc.multistore_batch_update = AsyncMock(return_value=[])
        api = self._make_api(service=svc)
        with pytest.raises(RpcError, match="Batch update failed") as exc_info:
            await api.multistore_batch_update({"store_updates": [], "submit_on_chain": True})
        assert exc_info.value.error_code == RpcErrorCodes.BATCH_UPDATE_FAILED.value

    @pytest.mark.anyio
    async def test_multistore_batch_update_submit_false_but_submitted(self) -> None:
        svc = AsyncMock()
        svc.multistore_batch_update = AsyncMock(return_value=[MagicMock()])
        api = self._make_api(service=svc)
        with pytest.raises(RpcError, match="submit_on_chain set to False") as exc_info:
            await api.multistore_batch_update({"store_updates": [], "submit_on_chain": False})
        assert exc_info.value.error_code == RpcErrorCodes.SUBMIT_ON_CHAIN_FALSE_BUT_SUBMITTED.value

    @pytest.mark.anyio
    async def test_insert_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.insert({"id": "aa" * 32, "key": "0x01", "value": "0x02"})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_delete_key_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.delete_key({"id": "aa" * 32, "key": "0x01"})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_root_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_root({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_root_returns_none(self) -> None:
        svc = AsyncMock()
        svc.get_root = AsyncMock(return_value=None)
        api = self._make_api(service=svc)
        with pytest.raises(RpcError, match="Failed to get root") as exc_info:
            await api.get_root({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.NO_ROOT_FOR_STORE.value

    @pytest.mark.anyio
    async def test_get_local_root_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_local_root({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_roots_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_roots({"ids": []})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_subscribe_missing_store_id(self) -> None:
        api = self._make_api(service=MagicMock())
        with pytest.raises(RpcError, match="missing store id") as exc_info:
            await api.subscribe({})
        assert exc_info.value.error_code == RpcErrorCodes.MISSING_STORE_ID.value

    @pytest.mark.anyio
    async def test_subscribe_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.subscribe({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_unsubscribe_missing_store_id(self) -> None:
        api = self._make_api(service=MagicMock())
        with pytest.raises(RpcError, match="missing store id") as exc_info:
            await api.unsubscribe({})
        assert exc_info.value.error_code == RpcErrorCodes.MISSING_STORE_ID.value

    @pytest.mark.anyio
    async def test_unsubscribe_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.unsubscribe({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_subscriptions_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.subscriptions({})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_remove_subscriptions_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.remove_subscriptions({})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_remove_subscriptions_missing_store_id(self) -> None:
        api = self._make_api(service=MagicMock())
        with pytest.raises(RpcError, match="missing store id") as exc_info:
            await api.remove_subscriptions({})
        assert exc_info.value.error_code == RpcErrorCodes.MISSING_STORE_ID.value

    @pytest.mark.anyio
    async def test_get_root_history_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_root_history({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_kv_diff_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_kv_diff({"id": "aa" * 32, "hash_1": "bb" * 32, "hash_2": "cc" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_get_sync_status_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.get_sync_status({"id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_check_plugins_service_none(self) -> None:
        api = self._make_api(service=None)
        with pytest.raises(RpcError, match="Data layer not created") as exc_info:
            await api.check_plugins({})
        assert exc_info.value.error_code == RpcErrorCodes.DATA_LAYER_NOT_CREATED.value

    @pytest.mark.anyio
    async def test_process_change_multistore_missing_store_id(self) -> None:
        from chia.data_layer.data_layer_rpc_api import process_change_multistore

        with pytest.raises(RpcError, match="must specify a store_id") as exc_info:
            process_change_multistore({"changelist": []})
        assert exc_info.value.error_code == RpcErrorCodes.STORE_ID_REQUIRED.value

    @pytest.mark.anyio
    async def test_process_change_multistore_missing_changelist(self) -> None:
        from chia.data_layer.data_layer_rpc_api import process_change_multistore

        with pytest.raises(RpcError, match="must specify a changelist") as exc_info:
            process_change_multistore({"store_id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.CHANGELIST_REQUIRED.value

    @pytest.mark.anyio
    async def test_get_proof_no_root(self) -> None:
        """get_proof raises NO_ROOT when root is None."""
        from chia_rs.sized_bytes import bytes32

        svc = AsyncMock()
        svc.get_root = AsyncMock(return_value=None)
        api = self._make_api(service=svc)
        store_id = bytes32(b"\xaa" * 32)
        # get_proof is wrapped by @streamable_marshal, so pass a dict
        with pytest.raises(RpcError, match="no root") as exc_info:
            await api.get_proof({"store_id": store_id.hex(), "keys": []})
        assert exc_info.value.error_code == RpcErrorCodes.NO_ROOT.value


# ──────────────────────────────────────────────────────────────────────────────
# farmer_rpc_api.py
# ──────────────────────────────────────────────────────────────────────────────
class TestFarmerRpcApiErrors:
    """Cover RpcError raises in farmer_rpc_api.py."""

    @pytest.mark.anyio
    async def test_get_harvester_plots_valid_restricted_sort_key(self) -> None:
        from chia.farmer.farmer_rpc_api import FarmerRpcApi

        api = FarmerRpcApi.__new__(FarmerRpcApi)
        mock_receiver = MagicMock()
        mock_receiver.plots.return_value = {}

        mock_farmer = MagicMock()
        mock_farmer.get_receiver = MagicMock(return_value=mock_receiver)
        api.service = mock_farmer

        request_dict = {
            "node_id": "aa" * 32,
            "page": 0,
            "page_size": 10,
            "filter": [],
            "sort_key": "pool_contract_puzzle_hash",
            "reverse": False,
        }
        with pytest.raises(RpcError, match="Can't sort by optional attributes") as exc_info:
            await api.get_harvester_plots_valid(request_dict)
        assert exc_info.value.error_code == RpcErrorCodes.INVALID_SORT_KEY.value


# ──────────────────────────────────────────────────────────────────────────────
# harvester_rpc_api.py
# ──────────────────────────────────────────────────────────────────────────────
class TestHarvesterRpcApiErrors:
    """Cover RpcError raises in harvester_rpc_api.py."""

    def _make_api(self) -> Any:
        from chia.harvester.harvester_rpc_api import HarvesterRpcApi

        api = HarvesterRpcApi.__new__(HarvesterRpcApi)
        api.service = MagicMock()
        return api

    @pytest.mark.anyio
    async def test_delete_plot_failed(self) -> None:
        api = self._make_api()
        api.service.delete_plot = MagicMock(return_value=False)
        with pytest.raises(RpcError, match="Not able to delete file") as exc_info:
            await api.delete_plot({"filename": "plot-abc.plot"})
        assert exc_info.value.error_code == RpcErrorCodes.DELETE_PLOT_FAILED.value

    @pytest.mark.anyio
    async def test_add_plot_directory_failed(self) -> None:
        api = self._make_api()
        api.service.add_plot_directory = AsyncMock(return_value=False)
        with pytest.raises(RpcError, match="Did not add plot directory") as exc_info:
            await api.add_plot_directory({"dirname": "/home/user/plots"})
        assert exc_info.value.error_code == RpcErrorCodes.ADD_PLOT_DIRECTORY_FAILED.value

    @pytest.mark.anyio
    async def test_remove_plot_directory_failed(self) -> None:
        api = self._make_api()
        api.service.remove_plot_directory = AsyncMock(return_value=False)
        with pytest.raises(RpcError, match="Did not remove plot directory") as exc_info:
            await api.remove_plot_directory({"dirname": "/home/user/plots"})
        assert exc_info.value.error_code == RpcErrorCodes.REMOVE_PLOT_DIRECTORY_FAILED.value

    @pytest.mark.anyio
    async def test_update_harvester_config_refresh_interval_too_short(self) -> None:
        api = self._make_api()
        api.service.update_harvester_config = AsyncMock()
        with pytest.raises(RpcError, match="too short") as exc_info:
            await api.update_harvester_config({"refresh_parameter_interval_seconds": 1})
        assert exc_info.value.error_code == RpcErrorCodes.REFRESH_INTERVAL_TOO_SHORT.value


# ──────────────────────────────────────────────────────────────────────────────
# rpc_server.py — open_connection and close_connection
# ──────────────────────────────────────────────────────────────────────────────
class TestRpcServerErrors:
    """Cover RpcError raises in rpc_server.py (open_connection, close_connection)."""

    @pytest.mark.anyio
    async def test_open_connection_failed(self) -> None:
        """open_connection returns CONNECTION_FAILED when start_client returns False."""
        from chia.rpc.rpc_server import RpcServer

        server = RpcServer.__new__(RpcServer)
        server.prefer_ipv6 = False

        mock_service = MagicMock()
        mock_service.server.start_client = AsyncMock(return_value=False)
        # on_connect attribute check
        mock_service.on_connect = None

        mock_rpc_api = MagicMock()
        mock_rpc_api.service = mock_service
        server.rpc_api = mock_rpc_api

        with patch("chia.rpc.rpc_server.resolve", new_callable=AsyncMock, return_value="127.0.0.1"):
            result = await server.open_connection({"host": "localhost", "port": 8444})

        assert result["success"] is False
        assert result["structuredError"]["code"] == RpcErrorCodes.CONNECTION_FAILED.value

    @pytest.mark.anyio
    async def test_close_connection_not_found(self) -> None:
        """close_connection raises CONNECTION_NOT_FOUND for an unknown node_id."""
        from chia.rpc.rpc_server import RpcServer

        server = RpcServer.__new__(RpcServer)

        mock_service = MagicMock()
        mock_service.server.get_connections.return_value = []
        mock_rpc_api = MagicMock()
        mock_rpc_api.service = mock_service
        server.rpc_api = mock_rpc_api

        with pytest.raises(RpcError, match="does not exist") as exc_info:
            await server.close_connection({"node_id": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.CONNECTION_NOT_FOUND.value


# ──────────────────────────────────────────────────────────────────────────────
# simulator_full_node_rpc_api.py
# ──────────────────────────────────────────────────────────────────────────────
class TestSimulatorFullNodeRpcApiErrors:
    """Cover RpcError raises in simulator_full_node_rpc_api.py."""

    def _make_api(self) -> Any:
        from chia.simulator.simulator_full_node_rpc_api import SimulatorFullNodeRpcApi

        api = SimulatorFullNodeRpcApi.__new__(SimulatorFullNodeRpcApi)
        api.service = MagicMock()
        return api

    @pytest.mark.anyio
    async def test_revert_blocks_no_peak(self) -> None:
        api = self._make_api()
        api.service.blockchain.get_peak_height.return_value = None
        with pytest.raises(RpcError, match="No blocks to revert") as exc_info:
            await api.revert_blocks({})
        assert exc_info.value.error_code == RpcErrorCodes.NO_BLOCKS_TO_REVERT.value

    @pytest.mark.anyio
    async def test_reorg_blocks_no_peak(self) -> None:
        api = self._make_api()
        api.service.blockchain.get_peak_height.return_value = None
        with pytest.raises(RpcError, match="No blocks to revert") as exc_info:
            await api.reorg_blocks({})
        assert exc_info.value.error_code == RpcErrorCodes.NO_BLOCKS_TO_REVERT.value


# ──────────────────────────────────────────────────────────────────────────────
# full_node_rpc_api.py
# ──────────────────────────────────────────────────────────────────────────────
class TestFullNodeRpcApiErrors:
    """Cover RpcError raises in full_node_rpc_api.py."""

    def _make_api(self) -> Any:
        from chia.full_node.full_node_rpc_api import FullNodeRpcApi

        api = FullNodeRpcApi.__new__(FullNodeRpcApi)
        api.service = MagicMock()
        return api

    # get_recent_signage_point_or_eos
    @pytest.mark.anyio
    async def test_get_recent_signage_point_no_blocks(self) -> None:
        api = self._make_api()
        # EOS path: challenge_hash provided, eos found, but no peak
        eos_mock = MagicMock()
        eos_mock.challenge_chain.get_hash.return_value = b"\x00" * 32
        api.service.full_node_store.recent_eos.get.return_value = (eos_mock, 12345)
        api.service.full_node_store.get_sub_slot.return_value = None
        api.service.blockchain.get_peak.return_value = None
        with pytest.raises(RpcError, match="No blocks in the chain") as exc_info:
            await api.get_recent_signage_point_or_eos({"challenge_hash": "00" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.NO_BLOCKS_IN_CHAIN.value

    # get_block
    @pytest.mark.anyio
    async def test_get_block_no_header_hash(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No header_hash in request") as exc_info:
            await api.get_block({})
        assert exc_info.value.error_code == RpcErrorCodes.NO_HEADER_HASH_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_block_not_found(self) -> None:
        api = self._make_api()
        api.service.block_store.get_full_block = AsyncMock(return_value=None)
        with pytest.raises(RpcError, match="not found") as exc_info:
            await api.get_block({"header_hash": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_NOT_FOUND.value

    # get_blocks
    @pytest.mark.anyio
    async def test_get_blocks_no_start(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No start in request") as exc_info:
            await api.get_blocks({"end": 10})
        assert exc_info.value.error_code == RpcErrorCodes.NO_START_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_blocks_no_end(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No end in request") as exc_info:
            await api.get_blocks({"start": 0})
        assert exc_info.value.error_code == RpcErrorCodes.NO_END_IN_REQUEST.value

    # get_block_records
    @pytest.mark.anyio
    async def test_get_block_records_no_start(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No start in request") as exc_info:
            await api.get_block_records({"end": 10})
        assert exc_info.value.error_code == RpcErrorCodes.NO_START_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_block_records_no_end(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No end in request") as exc_info:
            await api.get_block_records({"start": 0})
        assert exc_info.value.error_code == RpcErrorCodes.NO_END_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_block_records_peak_none(self) -> None:
        api = self._make_api()
        api.service.blockchain.get_peak_height.return_value = None
        with pytest.raises(RpcError, match="Peak is None") as exc_info:
            await api.get_block_records({"start": 0, "end": 10})
        assert exc_info.value.error_code == RpcErrorCodes.PEAK_IS_NONE.value

    @pytest.mark.anyio
    async def test_get_block_records_height_not_in_blockchain(self) -> None:
        api = self._make_api()
        api.service.blockchain.get_peak_height.return_value = 100
        api.service.blockchain.height_to_hash.return_value = None
        with pytest.raises(RpcError, match="Height not in blockchain") as exc_info:
            await api.get_block_records({"start": 0, "end": 1})
        assert exc_info.value.error_code == RpcErrorCodes.HEIGHT_NOT_IN_BLOCKCHAIN.value

    @pytest.mark.anyio
    async def test_get_block_records_block_does_not_exist(self) -> None:
        from chia_rs.sized_bytes import bytes32

        api = self._make_api()
        api.service.blockchain.get_peak_height.return_value = 100
        api.service.blockchain.height_to_hash.return_value = bytes32(b"\xaa" * 32)
        api.service.blockchain.try_block_record.return_value = None
        api.service.blockchain.block_store.get_block_record = AsyncMock(return_value=None)
        with pytest.raises(RpcError, match="does not exist") as exc_info:
            await api.get_block_records({"start": 0, "end": 1})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_DOES_NOT_EXIST.value

    # get_block_spends
    @pytest.mark.anyio
    async def test_get_block_spends_no_header_hash(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No header_hash in request") as exc_info:
            await api.get_block_spends({})
        assert exc_info.value.error_code == RpcErrorCodes.NO_HEADER_HASH_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_block_spends_block_not_found(self) -> None:
        api = self._make_api()
        api.service.block_store.get_full_block = AsyncMock(return_value=None)
        with pytest.raises(RpcError, match="not found") as exc_info:
            await api.get_block_spends({"header_hash": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_NOT_FOUND.value

    # get_block_spends_with_conditions
    @pytest.mark.anyio
    async def test_get_block_spends_with_conditions_no_header_hash(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No header_hash in request") as exc_info:
            await api.get_block_spends_with_conditions({})
        assert exc_info.value.error_code == RpcErrorCodes.NO_HEADER_HASH_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_block_spends_with_conditions_block_not_found(self) -> None:
        api = self._make_api()
        api.service.block_store.get_full_block = AsyncMock(return_value=None)
        with pytest.raises(RpcError, match="not found") as exc_info:
            await api.get_block_spends_with_conditions({"header_hash": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_NOT_FOUND.value

    # get_block_record_by_height
    @pytest.mark.anyio
    async def test_get_block_record_by_height_no_height(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No height in request") as exc_info:
            await api.get_block_record_by_height({})
        assert exc_info.value.error_code == RpcErrorCodes.NO_HEIGHT_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_block_record_by_height_not_found(self) -> None:
        api = self._make_api()
        api.service.blockchain.get_peak_height.return_value = None
        with pytest.raises(RpcError, match="not found in chain") as exc_info:
            await api.get_block_record_by_height({"height": 10})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_HEIGHT_NOT_FOUND.value

    @pytest.mark.anyio
    async def test_get_block_record_by_height_hash_not_found(self) -> None:
        api = self._make_api()
        api.service.blockchain.get_peak_height.return_value = 100
        api.service.blockchain.height_to_hash.return_value = None
        with pytest.raises(RpcError, match="Block hash") as exc_info:
            await api.get_block_record_by_height({"height": 10})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_HASH_NOT_FOUND.value

    @pytest.mark.anyio
    async def test_get_block_record_by_height_does_not_exist(self) -> None:
        from chia_rs.sized_bytes import bytes32

        api = self._make_api()
        api.service.blockchain.get_peak_height.return_value = 100
        api.service.blockchain.height_to_hash.return_value = bytes32(b"\xaa" * 32)
        api.service.blockchain.try_block_record.return_value = None
        api.service.blockchain.block_store.get_block_record = AsyncMock(return_value=None)
        with pytest.raises(RpcError, match="does not exist") as exc_info:
            await api.get_block_record_by_height({"height": 10})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_DOES_NOT_EXIST.value

    # get_block_record
    @pytest.mark.anyio
    async def test_get_block_record_no_header_hash(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="header_hash not in request") as exc_info:
            await api.get_block_record({})
        assert exc_info.value.error_code == RpcErrorCodes.HEADER_HASH_NOT_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_block_record_does_not_exist(self) -> None:
        api = self._make_api()
        api.service.blockchain.try_block_record.return_value = None
        api.service.blockchain.block_store.get_block_record = AsyncMock(return_value=None)
        with pytest.raises(RpcError, match="does not exist") as exc_info:
            await api.get_block_record({"header_hash": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_DOES_NOT_EXIST.value

    # get_network_space
    @pytest.mark.anyio
    async def test_get_network_space_missing_hashes(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="newer_block_header_hash and older_block_header_hash required"):
            await api.get_network_space({})

    @pytest.mark.anyio
    async def test_get_network_space_same_hash(self) -> None:
        api = self._make_api()
        hh = "aa" * 32
        with pytest.raises(RpcError, match="New and old must not be the same") as exc_info:
            await api.get_network_space({"newer_block_header_hash": hh, "older_block_header_hash": hh})
        assert exc_info.value.error_code == RpcErrorCodes.NEW_AND_OLD_MUST_DIFFER.value

    @pytest.mark.anyio
    async def test_get_network_space_newer_not_found(self) -> None:
        api = self._make_api()
        api.service.block_store.get_block_record = AsyncMock(return_value=None)
        api.service.blockchain.block_record = MagicMock(side_effect=KeyError("not found"))
        with pytest.raises(RpcError, match=r"Newer block.*not found") as exc_info:
            await api.get_network_space({"newer_block_header_hash": "aa" * 32, "older_block_header_hash": "bb" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.NEWER_BLOCK_NOT_FOUND.value

    @pytest.mark.anyio
    async def test_get_network_space_older_not_found(self) -> None:
        api = self._make_api()
        newer_record = MagicMock()
        newer_record.weight = 100
        newer_record.total_iters = 1000
        newer_record.height = 10
        api.service.block_store.get_block_record = AsyncMock(side_effect=[newer_record, None])
        with pytest.raises(RpcError, match=r"Older block.*not found") as exc_info:
            await api.get_network_space({"newer_block_header_hash": "aa" * 32, "older_block_header_hash": "bb" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.OLDER_BLOCK_NOT_FOUND.value

    # get_coin_records_by_puzzle_hash
    @pytest.mark.anyio
    async def test_get_coin_records_by_puzzle_hash_missing(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="Puzzle hash not in request") as exc_info:
            await api.get_coin_records_by_puzzle_hash({})
        assert exc_info.value.error_code == RpcErrorCodes.PUZZLE_HASH_NOT_IN_REQUEST.value

    # get_coin_records_by_puzzle_hashes
    @pytest.mark.anyio
    async def test_get_coin_records_by_puzzle_hashes_missing(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="Puzzle hashes not in request") as exc_info:
            await api.get_coin_records_by_puzzle_hashes({})
        assert exc_info.value.error_code == RpcErrorCodes.PUZZLE_HASHES_NOT_IN_REQUEST.value

    # get_coin_record_by_name
    @pytest.mark.anyio
    async def test_get_coin_record_by_name_missing(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="Name not in request") as exc_info:
            await api.get_coin_record_by_name({})
        assert exc_info.value.error_code == RpcErrorCodes.NAME_NOT_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_coin_record_by_name_not_found(self) -> None:
        api = self._make_api()
        api.service.blockchain.coin_store.get_coin_record = AsyncMock(return_value=None)
        with pytest.raises(RpcError, match="not found") as exc_info:
            await api.get_coin_record_by_name({"name": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.COIN_RECORD_NOT_FOUND.value

    # get_coin_records_by_names
    @pytest.mark.anyio
    async def test_get_coin_records_by_names_missing(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="Names not in request") as exc_info:
            await api.get_coin_records_by_names({})
        assert exc_info.value.error_code == RpcErrorCodes.NAMES_NOT_IN_REQUEST.value

    # get_coin_records_by_parent_ids
    @pytest.mark.anyio
    async def test_get_coin_records_by_parent_ids_missing(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="Parent IDs not in request") as exc_info:
            await api.get_coin_records_by_parent_ids({})
        assert exc_info.value.error_code == RpcErrorCodes.PARENT_IDS_NOT_IN_REQUEST.value

    # get_coin_records_by_hint
    @pytest.mark.anyio
    async def test_get_coin_records_by_hint_missing(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="Hint not in request") as exc_info:
            await api.get_coin_records_by_hint({})
        assert exc_info.value.error_code == RpcErrorCodes.HINT_NOT_IN_REQUEST.value

    # push_tx
    @pytest.mark.anyio
    async def test_push_tx_missing_spend_bundle(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="Spend bundle not in request") as exc_info:
            await api.push_tx({})
        assert exc_info.value.error_code == RpcErrorCodes.SPEND_BUNDLE_NOT_IN_REQUEST.value

    # get_additions_and_removals
    @pytest.mark.anyio
    async def test_get_additions_and_removals_no_header_hash(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No header_hash in request") as exc_info:
            await api.get_additions_and_removals({})
        assert exc_info.value.error_code == RpcErrorCodes.NO_HEADER_HASH_IN_REQUEST.value

    @pytest.mark.anyio
    async def test_get_additions_and_removals_block_not_found(self) -> None:
        api = self._make_api()
        api.service.block_store.get_full_block = AsyncMock(return_value=None)
        with pytest.raises(RpcError, match="not found") as exc_info:
            await api.get_additions_and_removals({"header_hash": "aa" * 32})
        assert exc_info.value.error_code == RpcErrorCodes.BLOCK_NOT_FOUND.value

    # get_mempool_item_by_tx_id
    @pytest.mark.anyio
    async def test_get_mempool_item_by_tx_id_missing(self) -> None:
        api = self._make_api()
        with pytest.raises(RpcError, match="No tx_id in request") as exc_info:
            await api.get_mempool_item_by_tx_id({})
        assert exc_info.value.error_code == RpcErrorCodes.NO_TX_ID_IN_REQUEST.value


# ──────────────────────────────────────────────────────────────────────────────
# wallet_rpc_api.py
# ──────────────────────────────────────────────────────────────────────────────


class TestWalletRpcApiErrors:
    """Cover RpcError raises in wallet_rpc_api.py.

    These tests create a WalletRpcApi with mocked service dependencies to
    trigger the specific error paths. We only test the raise site to confirm
    RpcError with the right code, not full business logic.
    """

    def _make_api(self) -> Any:
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = WalletRpcApi.__new__(WalletRpcApi)
        api.service = MagicMock()
        return api

    # log_in — fingerprint not found
    @pytest.mark.anyio
    async def test_log_in_fingerprint_not_found(self) -> None:
        api = self._make_api()
        api.service.logged_in_fingerprint = None
        api._stop_wallet = AsyncMock()
        api.service._start_with_fingerprint = AsyncMock(return_value=False)

        from chia_rs.sized_ints import uint32

        from chia.wallet.wallet_request_types import LogIn

        request = LogIn(fingerprint=uint32(12345))
        with pytest.raises(RpcError, match=r"fingerprint.*not found") as exc_info:
            await api.log_in(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.FINGERPRINT_NOT_FOUND.value

    # get_public_keys — error getting keys
    @pytest.mark.anyio
    async def test_get_public_keys_error(self) -> None:
        api = self._make_api()
        api.service.keychain_proxy.get_keys = AsyncMock(side_effect=RuntimeError("keychain broken"))

        from chia.wallet.wallet_request_types import Empty

        with pytest.raises(RpcError, match="Error while getting keys") as exc_info:
            await api.get_public_keys(Empty().to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.FAILED_TO_GET_KEYS.value

    # get_private_key — not found
    @pytest.mark.anyio
    async def test_get_private_key_not_found(self) -> None:
        api = self._make_api()
        api._get_private_key = AsyncMock(return_value=(None, None))

        from chia_rs.sized_ints import uint32

        from chia.wallet.wallet_request_types import GetPrivateKey

        request = GetPrivateKey(fingerprint=uint32(99999))
        with pytest.raises(RpcError, match="Could not get a private key") as exc_info:
            await api.get_private_key(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.PRIVATE_KEY_NOT_FOUND.value

    # add_key — mnemonic word incorrect
    @pytest.mark.anyio
    async def test_add_key_incorrect_word(self) -> None:
        api = self._make_api()
        api.service.keychain_proxy.add_key = AsyncMock(side_effect=KeyError("badword"))

        from chia.wallet.wallet_request_types import AddKey

        request = AddKey(mnemonic=["badword"] * 24)
        with pytest.raises(RpcError, match="incorrect") as exc_info:
            await api.add_key(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.MNEMONIC_WORD_INCORRECT.value

    # add_key — failed to start
    @pytest.mark.anyio
    async def test_add_key_failed_to_start(self) -> None:
        api = self._make_api()
        mock_sk = MagicMock()
        mock_g1 = MagicMock()
        mock_g1.get_fingerprint.return_value = 12345
        mock_sk.get_g1.return_value = mock_g1
        api.service.keychain_proxy.add_key = AsyncMock(return_value=mock_sk)
        api._stop_wallet = AsyncMock()
        api.service.keychain_proxy.check_keys = AsyncMock()
        api.service._start_with_fingerprint = AsyncMock(return_value=False)

        from chia.wallet.wallet_request_types import AddKey

        request = AddKey(mnemonic=["abandon"] * 24)
        with pytest.raises(RpcError, match="Failed to start") as exc_info:
            await api.add_key(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.FAILED_TO_START.value

    # set_wallet_resync_on_startup — login required
    @pytest.mark.anyio
    async def test_set_wallet_resync_login_required(self) -> None:
        api = self._make_api()
        api.service.logged_in_fingerprint = None

        from chia.wallet.wallet_request_types import SetWalletResyncOnStartup

        request = SetWalletResyncOnStartup(enable=True)
        with pytest.raises(RpcError, match="login") as exc_info:
            await api.set_wallet_resync_on_startup(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.LOGIN_REQUIRED.value

    # push_tx — no full node peers
    @pytest.mark.anyio
    async def test_push_tx_no_peers(self) -> None:
        api = self._make_api()
        api.service.server.get_connections.return_value = []

        # Call through the @marshal wrapper with a dict
        # The marshal wrapper will try to deserialize PushTX from the dict
        # We need to mock the deserialization
        with patch(
            "chia.wallet.wallet_rpc_api.PushTX.from_json_dict",
            return_value=types.SimpleNamespace(spend_bundle=MagicMock()),
        ):
            with pytest.raises(RpcError, match="not currently connected") as exc_info:
                await api.push_tx({"spend_bundle": {}})
        assert exc_info.value.error_code == RpcErrorCodes.NO_FULL_NODE_PEERS.value

    # push_transactions — cannot push if false
    @pytest.mark.anyio
    async def test_push_transactions_cannot_push(self) -> None:
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        action_scope = MagicMock()
        action_scope.config.push = False

        # Get the actual inner function (past tx_endpoint and marshal)
        inner_fn = WalletRpcApi.__dict__["push_transactions"].__closure__[0].cell_contents.__closure__[0].cell_contents
        request = MagicMock()
        with pytest.raises(RpcError, match="Cannot push") as exc_info:
            await inner_fn(api, request, action_scope)
        assert exc_info.value.error_code == RpcErrorCodes.CANNOT_PUSH_IF_FALSE.value

    # get_transaction — not found
    @pytest.mark.anyio
    async def test_get_transaction_not_found(self) -> None:
        from chia_rs.sized_bytes import bytes32

        api = self._make_api()
        api.service.wallet_state_manager.get_transaction = AsyncMock(return_value=None)

        from chia.wallet.wallet_request_types import GetTransaction

        request = GetTransaction(transaction_id=bytes32(b"\xaa" * 32))
        with pytest.raises(RpcError, match="not found") as exc_info:
            await api.get_transaction(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.TRANSACTION_NOT_FOUND.value

    # get_transaction_memo — transaction not found
    @pytest.mark.anyio
    async def test_get_transaction_memo_not_found(self) -> None:
        from chia_rs.sized_bytes import bytes32

        api = self._make_api()
        api.service.wallet_state_manager.get_transaction = AsyncMock(return_value=None)

        from chia.wallet.wallet_request_types import GetTransactionMemo

        request = GetTransactionMemo(transaction_id=bytes32(b"\xaa" * 32))
        with pytest.raises(RpcError, match="not found") as exc_info:
            await api.get_transaction_memo(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.TRANSACTION_NOT_FOUND.value

    # get_transaction_memo — no coin spend
    @pytest.mark.anyio
    async def test_get_transaction_memo_no_coin_spend(self) -> None:
        from chia_rs.sized_bytes import bytes32
        from chia_rs.sized_ints import uint32

        api = self._make_api()
        tr = MagicMock()
        tr.spend_bundle = None
        # TransactionType.INCOMING_TX = 0, we need a type that is NOT INCOMING_TX
        # INCOMING_TX has value 0, so use a different value
        tr.type = uint32(1)  # OUTGOING_TX — not INCOMING_TX
        api.service.wallet_state_manager.get_transaction = AsyncMock(return_value=tr)

        from chia.wallet.wallet_request_types import GetTransactionMemo

        request = GetTransactionMemo(transaction_id=bytes32(b"\xaa" * 32))
        with pytest.raises(RpcError, match="doesn't have any coin spend") as exc_info:
            await api.get_transaction_memo(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.TRANSACTION_NO_COIN_SPEND.value

    # get_next_address — wallet type cannot create puzzle hashes
    @pytest.mark.anyio
    async def test_get_next_address_unsupported_wallet_type(self) -> None:
        api = self._make_api()
        mock_wallet = MagicMock()
        mock_wallet.type.return_value = 99  # unsupported type
        api.service.wallet_state_manager.wallets = {1: mock_wallet}

        from chia_rs.sized_ints import uint32

        from chia.wallet.wallet_request_types import GetNextAddress

        request = GetNextAddress(wallet_id=uint32(1), new_address=True, save_derivations=False)
        with pytest.raises(RpcError, match="cannot create puzzle hashes") as exc_info:
            await api.get_next_address(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_TYPE_CANNOT_CREATE_PUZZLE_HASHES.value

    # send_transaction_multi — wallet not synced (inner check)
    @pytest.mark.anyio
    async def test_send_transaction_multi_not_synced(self) -> None:
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        api.service.wallet_state_manager.synced = AsyncMock(return_value=False)
        action_scope = MagicMock()

        # Get the actual inner function
        inner_fn = (
            WalletRpcApi.__dict__["send_transaction_multi"].__closure__[0].cell_contents.__closure__[0].cell_contents
        )
        request = MagicMock()
        with pytest.raises(RpcError, match="fully synced") as exc_info:
            await inner_fn(api, request, action_scope)
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_NOT_SYNCED_FOR_TX.value

    # delete_unconfirmed_transactions — wallet not found
    @pytest.mark.anyio
    async def test_delete_unconfirmed_transactions_wallet_not_found(self) -> None:
        api = self._make_api()
        api.service.wallet_state_manager.wallets = {}

        from chia_rs.sized_ints import uint32

        from chia.wallet.wallet_request_types import DeleteUnconfirmedTransactions

        request = DeleteUnconfirmedTransactions(wallet_id=uint32(999))
        with pytest.raises(RpcError, match="does not exist") as exc_info:
            await api.delete_unconfirmed_transactions(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_NOT_FOUND.value

    # delete_unconfirmed_transactions — not synced
    @pytest.mark.anyio
    async def test_delete_unconfirmed_transactions_not_synced(self) -> None:
        api = self._make_api()
        api.service.wallet_state_manager.wallets = {1: MagicMock()}
        api.service.wallet_state_manager.synced = AsyncMock(return_value=False)

        from chia_rs.sized_ints import uint32

        from chia.wallet.wallet_request_types import DeleteUnconfirmedTransactions

        request = DeleteUnconfirmedTransactions(wallet_id=uint32(1))
        with pytest.raises(RpcError, match="fully synced") as exc_info:
            await api.delete_unconfirmed_transactions(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_NOT_SYNCED.value

    # select_coins — not synced
    @pytest.mark.anyio
    async def test_select_coins_not_synced(self) -> None:
        api = self._make_api()
        api.service.logged_in_fingerprint = 12345
        api.service.wallet_state_manager.synced = AsyncMock(return_value=False)
        api.service.wallet_state_manager.constants = MagicMock()

        from chia_rs.sized_ints import uint32, uint64

        from chia.wallet.wallet_request_types import SelectCoins

        request = SelectCoins(wallet_id=uint32(1), amount=uint64(100))
        with pytest.raises(RpcError, match="fully synced") as exc_info:
            await api.select_coins(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_NOT_SYNCED_FOR_COINS.value

    # get_spendable_coins — not synced
    @pytest.mark.anyio
    async def test_get_spendable_coins_not_synced(self) -> None:
        api = self._make_api()
        api.service.wallet_state_manager.synced = AsyncMock(return_value=False)

        from chia_rs.sized_ints import uint32

        from chia.wallet.wallet_request_types import GetSpendableCoins

        request = GetSpendableCoins(wallet_id=uint32(1))
        with pytest.raises(RpcError, match="fully synced") as exc_info:
            await api.get_spendable_coins(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_NOT_SYNCED_FOR_SPENDABLE.value

    # get_coin_records_by_names — not synced
    @pytest.mark.anyio
    async def test_get_coin_records_by_names_not_synced(self) -> None:
        api = self._make_api()
        api.service.wallet_state_manager.synced = AsyncMock(return_value=False)

        from chia_rs.sized_bytes import bytes32

        from chia.wallet.wallet_request_types import GetCoinRecordsByNames

        request = GetCoinRecordsByNames(names=[bytes32(b"\xaa" * 32)])
        with pytest.raises(RpcError, match="fully synced") as exc_info:
            await api.get_coin_records_by_names(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_NOT_SYNCED_FOR_COIN_INFO.value

    # extend_derivation_index — not synced
    @pytest.mark.anyio
    async def test_extend_derivation_index_not_synced(self) -> None:
        api = self._make_api()
        api.service.wallet_state_manager.synced = AsyncMock(return_value=False)

        from chia_rs.sized_ints import uint32

        from chia.wallet.wallet_request_types import ExtendDerivationIndex

        request = ExtendDerivationIndex(index=uint32(100))
        with pytest.raises(RpcError, match="fully synced") as exc_info:
            await api.extend_derivation_index(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_NOT_SYNCED_FOR_DERIVATION.value

    # extend_derivation_index — no derivation record
    @pytest.mark.anyio
    async def test_extend_derivation_index_no_record(self) -> None:
        api = self._make_api()
        api.service.wallet_state_manager.synced = AsyncMock(return_value=True)
        api.service.wallet_state_manager.puzzle_store.get_last_derivation_path = AsyncMock(return_value=None)

        from chia_rs.sized_ints import uint32

        from chia.wallet.wallet_request_types import ExtendDerivationIndex

        request = ExtendDerivationIndex(index=uint32(100))
        with pytest.raises(RpcError, match="No current derivation record") as exc_info:
            await api.extend_derivation_index(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.NO_DERIVATION_RECORD.value

    # sign_message_by_id — DID not found
    @pytest.mark.anyio
    async def test_sign_message_by_id_did_not_found(self) -> None:
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        api.service.wallet_state_manager.wallets = {}

        # Get the actual inner function (past @marshal)
        inner_fn = WalletRpcApi.__dict__["sign_message_by_id"].__closure__[0].cell_contents

        with patch("chia.wallet.wallet_rpc_api.is_valid_address", side_effect=[True, False]):
            with patch("chia.wallet.wallet_rpc_api.decode_puzzle_hash", return_value=b"\xaa" * 32):
                request = MagicMock()
                request.id = "did:chia:test"
                request.message = "hello"
                request.signing_mode_enum = MagicMock()
                with pytest.raises(RpcError, match=r"DID.*doesn't exist") as exc_info:
                    await inner_fn(api, request)
                assert exc_info.value.error_code == RpcErrorCodes.DID_NOT_FOUND.value

    # sign_message_by_id — NFT not found
    @pytest.mark.anyio
    async def test_sign_message_by_id_nft_not_found(self) -> None:
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        api.service.wallet_state_manager.wallets = {}

        inner_fn = WalletRpcApi.__dict__["sign_message_by_id"].__closure__[0].cell_contents

        with patch("chia.wallet.wallet_rpc_api.is_valid_address", side_effect=[False, True, False]):
            with patch("chia.wallet.wallet_rpc_api.decode_puzzle_hash", return_value=b"\xaa" * 32):
                request = MagicMock()
                request.id = "nft1test"
                request.message = "hello"
                request.signing_mode_enum = MagicMock()
                with pytest.raises(RpcError, match=r"NFT.*doesn't exist") as exc_info:
                    await inner_fn(api, request)
                assert exc_info.value.error_code == RpcErrorCodes.NFT_NOT_FOUND.value

    # sign_message_by_id — unknown ID type
    @pytest.mark.anyio
    async def test_sign_message_by_id_unknown_type(self) -> None:
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()

        inner_fn = WalletRpcApi.__dict__["sign_message_by_id"].__closure__[0].cell_contents

        with patch("chia.wallet.wallet_rpc_api.is_valid_address", return_value=False):
            with patch("chia.wallet.wallet_rpc_api.decode_puzzle_hash", return_value=b"\xaa" * 32):
                request = MagicMock()
                request.id = "unknown_id"
                request.message = "hello"
                request.signing_mode_enum = MagicMock()
                with pytest.raises(RpcError, match="Unknown ID type") as exc_info:
                    await inner_fn(api, request)
                assert exc_info.value.error_code == RpcErrorCodes.UNKNOWN_ID_TYPE.value

    # create_offer_for_ids — cannot push incomplete spend
    @pytest.mark.anyio
    async def test_create_offer_for_ids_cannot_push(self) -> None:
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        action_scope = MagicMock()
        action_scope.config.push = True

        inner_fn = (
            WalletRpcApi.__dict__["create_offer_for_ids"].__closure__[0].cell_contents.__closure__[0].cell_contents
        )
        request = MagicMock()
        with pytest.raises(RpcError, match="Cannot push") as exc_info:
            await inner_fn(api, request, action_scope)
        assert exc_info.value.error_code == RpcErrorCodes.CANNOT_PUSH_INCOMPLETE_SPEND.value

    # get_offer — trade not found
    @pytest.mark.anyio
    async def test_get_offer_not_found(self) -> None:
        from chia_rs.sized_bytes import bytes32

        api = self._make_api()
        api.service.wallet_state_manager.trade_manager.get_trade_by_id = AsyncMock(return_value=None)

        from chia.wallet.wallet_request_types import GetOffer

        request = GetOffer(trade_id=bytes32(b"\xaa" * 32), file_contents=False)
        with pytest.raises(RpcError, match="No trade") as exc_info:
            await api.get_offer(request.to_json_dict())
        assert exc_info.value.error_code == RpcErrorCodes.TRADE_NOT_FOUND.value

    # nft_mint_nft — royalty percentage invalid
    @pytest.mark.anyio
    async def test_nft_mint_nft_royalty_invalid(self) -> None:
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        mock_wallet = MagicMock()
        api.service.wallet_state_manager.get_wallet = MagicMock(return_value=mock_wallet)

        action_scope = MagicMock()

        inner_fn = WalletRpcApi.__dict__["nft_mint_nft"].__closure__[0].cell_contents.__closure__[0].cell_contents
        request = MagicMock()
        request.wallet_id = 1
        request.royalty_percentage = 10000  # 100% — invalid
        with pytest.raises(RpcError, match="Royalty percentage") as exc_info:
            await inner_fn(api, request, action_scope)
        assert exc_info.value.error_code == RpcErrorCodes.ROYALTY_PERCENTAGE_INVALID.value

    # create_signed_transaction — additions list required
    @pytest.mark.anyio
    async def test_create_signed_transaction_no_additions(self) -> None:
        from chia.wallet.wallet import Wallet
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        mock_wallet = MagicMock(spec=Wallet)
        api.service.wallet_state_manager.wallets = {1: mock_wallet}
        api.service.wallet_state_manager.main_wallet = mock_wallet

        action_scope = MagicMock()

        inner_fn = (
            WalletRpcApi.__dict__["create_signed_transaction"].__closure__[0].cell_contents.__closure__[0].cell_contents
        )
        request = MagicMock()
        request.wallet_id = None
        request.additions = []
        with pytest.raises(RpcError, match="Specify additions") as exc_info:
            await inner_fn(api, request, action_scope)
        assert exc_info.value.error_code == RpcErrorCodes.ADDITIONS_LIST_REQUIRED.value

    # create_signed_transaction — address invalid length
    @pytest.mark.anyio
    async def test_create_signed_transaction_address_invalid_length(self) -> None:
        from chia.wallet.wallet import Wallet
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        mock_wallet = MagicMock(spec=Wallet)
        api.service.wallet_state_manager.wallets = {1: mock_wallet}
        api.service.wallet_state_manager.main_wallet = mock_wallet
        api.service.constants.MAX_COIN_AMOUNT = 10**12

        action_scope = MagicMock()

        inner_fn = (
            WalletRpcApi.__dict__["create_signed_transaction"].__closure__[0].cell_contents.__closure__[0].cell_contents
        )
        addition = MagicMock()
        addition.amount = 100
        addition.puzzle_hash = b"\xaa" * 16  # only 16 bytes, not 32
        addition.memos = None

        request = MagicMock()
        request.wallet_id = None
        request.additions = [addition]
        with pytest.raises(RpcError, match="Address must be 32 bytes") as exc_info:
            await inner_fn(api, request, action_scope)
        assert exc_info.value.error_code == RpcErrorCodes.ADDRESS_INVALID_LENGTH.value

    # create_signed_transaction — coin amount exceeds max
    @pytest.mark.anyio
    async def test_create_signed_transaction_coin_amount_exceeds_max(self) -> None:
        from chia.wallet.wallet import Wallet
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        mock_wallet = MagicMock(spec=Wallet)
        api.service.wallet_state_manager.wallets = {1: mock_wallet}
        api.service.wallet_state_manager.main_wallet = mock_wallet
        api.service.constants.MAX_COIN_AMOUNT = 100

        action_scope = MagicMock()

        inner_fn = (
            WalletRpcApi.__dict__["create_signed_transaction"].__closure__[0].cell_contents.__closure__[0].cell_contents
        )
        addition0 = MagicMock()
        addition0.amount = 50
        addition0.puzzle_hash = b"\xaa" * 32
        addition0.memos = None

        addition1 = MagicMock()
        addition1.amount = 200  # exceeds max
        addition1.puzzle_hash = b"\xbb" * 32
        addition1.memos = None

        request = MagicMock()
        request.wallet_id = None
        request.additions = [addition0, addition1]
        with pytest.raises(RpcError, match="Coin amount cannot exceed") as exc_info:
            await inner_fn(api, request, action_scope)
        assert exc_info.value.error_code == RpcErrorCodes.COIN_AMOUNT_EXCEEDS_MAX.value

    # DataLayer wallet methods — wallet service not initialized
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method_name,is_tx_endpoint",
        [
            ("dl_track_new", False),
            ("dl_stop_tracking", False),
            ("dl_latest_singleton", False),
            ("dl_singletons_by_root", False),
            ("dl_history", False),
            ("dl_owned_singletons", False),
            ("dl_get_mirrors", False),
        ],
    )
    async def test_dl_wallet_marshal_only_not_initialized(self, method_name: str, is_tx_endpoint: bool) -> None:
        """DL wallet methods with @marshal only (no @tx_endpoint)."""
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        api.service.wallet_state_manager = None

        # For @marshal-only methods, the inner function is in closure[0]
        inner_fn = WalletRpcApi.__dict__[method_name].__closure__[0].cell_contents
        request = MagicMock()
        with pytest.raises(RpcError, match=r"not currently initialized|not initialized") as exc_info:
            await inner_fn(api, request)
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_SERVICE_NOT_INITIALIZED.value

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method_name",
        [
            "create_new_dl",
            "dl_update_root",
            "dl_update_multiple",
            "dl_new_mirror",
            "dl_delete_mirror",
        ],
    )
    async def test_dl_wallet_tx_endpoint_not_initialized(self, method_name: str) -> None:
        """DL wallet methods with @tx_endpoint + @marshal."""
        from chia.wallet.wallet_rpc_api import WalletRpcApi

        api = self._make_api()
        api.service.wallet_state_manager = None

        # For @tx_endpoint + @marshal, inner is closure[0].closure[0]
        inner_fn = WalletRpcApi.__dict__[method_name].__closure__[0].cell_contents.__closure__[0].cell_contents
        request = MagicMock()
        action_scope = MagicMock()
        with pytest.raises(RpcError, match=r"not currently initialized|not initialized") as exc_info:
            await inner_fn(api, request, action_scope)
        assert exc_info.value.error_code == RpcErrorCodes.WALLET_SERVICE_NOT_INITIALIZED.value
