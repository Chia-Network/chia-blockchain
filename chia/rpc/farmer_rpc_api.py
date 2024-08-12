from __future__ import annotations

import dataclasses
import operator
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple

from typing_extensions import Protocol

from chia.farmer.farmer import Farmer
from chia.plot_sync.receiver import Receiver
from chia.protocols.harvester_protocol import Plot
from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32
from chia.util.paginator import Paginator
from chia.util.streamable import Streamable, streamable
from chia.util.ws_message import WsRpcMessage, create_payload_dict


@dataclasses.dataclass(frozen=True)
class PaginatedRequestData(Protocol):
    node_id: bytes32
    page: uint32
    page_size: uint32

    __match_args__: ClassVar[Tuple[str, ...]] = ()


@streamable
@dataclasses.dataclass(frozen=True)
class FilterItem(Streamable):
    key: str
    value: Optional[str]


@streamable
@dataclasses.dataclass(frozen=True)
class PlotInfoRequestData(Streamable):
    node_id: bytes32
    page: uint32
    page_size: uint32
    filter: List[FilterItem] = dataclasses.field(default_factory=list)
    sort_key: str = "filename"
    reverse: bool = False

    __match_args__: ClassVar[Tuple[str, ...]] = ()


@streamable
@dataclasses.dataclass(frozen=True)
class PlotPathRequestData(Streamable):
    node_id: bytes32
    page: uint32
    page_size: uint32
    filter: List[str] = dataclasses.field(default_factory=list)
    reverse: bool = False

    __match_args__: ClassVar[Tuple[str, ...]] = ()


def paginated_plot_request(source: List[Any], request: PaginatedRequestData) -> Dict[str, object]:
    paginator: Paginator = Paginator(source, request.page_size)
    return {
        "node_id": request.node_id.hex(),
        "page": request.page,
        "page_count": paginator.page_count(),
        "total_count": len(source),
        "plots": paginator.get_page(request.page),
    }


def plot_matches_filter(plot: Plot, filter_item: FilterItem) -> bool:
    plot_attribute = getattr(plot, filter_item.key)
    if filter_item.value is None:
        return plot_attribute is None
    else:
        return filter_item.value in str(plot_attribute)


class FarmerRpcApi:
    def __init__(self, farmer: Farmer):
        self.service = farmer
        self.service_name = "chia_farmer"

    def get_routes(self) -> Dict[str, Endpoint]:
        return {
            "/get_signage_point": self.get_signage_point,
            "/get_signage_points": self.get_signage_points,
            "/get_reward_targets": self.get_reward_targets,
            "/set_reward_targets": self.set_reward_targets,
            "/get_pool_state": self.get_pool_state,
            "/set_payout_instructions": self.set_payout_instructions,
            "/get_harvesters": self.get_harvesters,
            "/get_harvesters_summary": self.get_harvesters_summary,
            "/get_harvester_plots_valid": self.get_harvester_plots_valid,
            "/get_harvester_plots_invalid": self.get_harvester_plots_invalid,
            "/get_harvester_plots_keys_missing": self.get_harvester_plots_keys_missing,
            "/get_harvester_plots_duplicates": self.get_harvester_plots_duplicates,
            "/get_pool_login_link": self.get_pool_login_link,
        }

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]]) -> List[WsRpcMessage]:
        payloads = []

        if change_data is None:
            # TODO: maybe something better?
            pass
        elif change == "new_signage_point":
            sp_hash = change_data["sp_hash"]
            missing_signage_points = change_data["missing_signage_points"]
            data = await self.get_signage_point({"sp_hash": sp_hash.hex()})
            data["missing_signage_points"] = missing_signage_points
            payloads.append(
                create_payload_dict(
                    "new_signage_point",
                    data,
                    self.service_name,
                    "wallet_ui",
                )
            )
            payloads.append(
                create_payload_dict(
                    "new_signage_point",
                    data,
                    self.service_name,
                    "metrics",
                )
            )
        elif change == "new_farming_info":
            payloads.append(
                create_payload_dict(
                    "new_farming_info",
                    change_data,
                    self.service_name,
                    "wallet_ui",
                )
            )
            payloads.append(
                create_payload_dict(
                    "new_farming_info",
                    change_data,
                    self.service_name,
                    "metrics",
                )
            )
        elif change == "harvester_update":
            payloads.append(
                create_payload_dict(
                    "harvester_update",
                    change_data,
                    self.service_name,
                    "wallet_ui",
                )
            )
            payloads.append(
                create_payload_dict(
                    "harvester_update",
                    change_data,
                    self.service_name,
                    "metrics",
                )
            )
        elif change == "harvester_removed":
            payloads.append(
                create_payload_dict(
                    "harvester_removed",
                    change_data,
                    self.service_name,
                    "wallet_ui",
                )
            )
            payloads.append(
                create_payload_dict(
                    "harvester_removed",
                    change_data,
                    self.service_name,
                    "metrics",
                )
            )
        elif change == "submitted_partial":
            payloads.append(
                create_payload_dict(
                    "submitted_partial",
                    change_data,
                    self.service_name,
                    "metrics",
                )
            )
            payloads.append(
                create_payload_dict(
                    "submitted_partial",
                    change_data,
                    self.service_name,
                    "wallet_ui",
                )
            )
        elif change == "failed_partial":
            payloads.append(
                create_payload_dict(
                    "failed_partial",
                    change_data,
                    self.service_name,
                    "wallet_ui",
                )
            )
        elif change == "proof":
            payloads.append(
                create_payload_dict(
                    "proof",
                    change_data,
                    self.service_name,
                    "metrics",
                )
            )
        elif change == "add_connection":
            payloads.append(
                create_payload_dict(
                    "add_connection",
                    change_data,
                    self.service_name,
                    "metrics",
                )
            )
        elif change == "close_connection":
            payloads.append(
                create_payload_dict(
                    "close_connection",
                    change_data,
                    self.service_name,
                    "metrics",
                )
            )

        return payloads

    async def get_signage_point(self, request: Dict[str, Any]) -> EndpointResult:
        sp_hash = bytes32.from_hexstr(request["sp_hash"])
        sps = self.service.sps.get(sp_hash)
        if sps is None or len(sps) < 1:
            raise ValueError(f"Signage point {sp_hash.hex()} not found")
        sp = sps[0]
        assert sp_hash == sp.challenge_chain_sp
        pospaces = self.service.proofs_of_space.get(sp.challenge_chain_sp, [])
        return {
            "signage_point": {
                "challenge_hash": sp.challenge_hash,
                "challenge_chain_sp": sp.challenge_chain_sp,
                "reward_chain_sp": sp.reward_chain_sp,
                "difficulty": sp.difficulty,
                "sub_slot_iters": sp.sub_slot_iters,
                "signage_point_index": sp.signage_point_index,
            },
            "proofs": pospaces,
        }

    async def get_signage_points(self, _: Dict[str, Any]) -> EndpointResult:
        result: List[Dict[str, Any]] = []
        for sps in self.service.sps.values():
            for sp in sps:
                pospaces = self.service.proofs_of_space.get(sp.challenge_chain_sp, [])
                result.append(
                    {
                        "signage_point": {
                            "challenge_hash": sp.challenge_hash,
                            "challenge_chain_sp": sp.challenge_chain_sp,
                            "reward_chain_sp": sp.reward_chain_sp,
                            "difficulty": sp.difficulty,
                            "sub_slot_iters": sp.sub_slot_iters,
                            "signage_point_index": sp.signage_point_index,
                        },
                        "proofs": pospaces,
                    }
                )
        return {"signage_points": result}

    async def get_reward_targets(self, request: Dict[str, Any]) -> EndpointResult:
        search_for_private_key = request["search_for_private_key"]
        max_ph_to_search = request.get("max_ph_to_search", 500)
        return await self.service.get_reward_targets(search_for_private_key, max_ph_to_search)

    async def set_reward_targets(self, request: Dict[str, Any]) -> EndpointResult:
        farmer_target, pool_target = None, None
        if "farmer_target" in request:
            farmer_target = request["farmer_target"]
        if "pool_target" in request:
            pool_target = request["pool_target"]

        self.service.set_reward_targets(farmer_target, pool_target)
        return {}

    def get_pool_contract_puzzle_hash_plot_count(self, pool_contract_puzzle_hash: bytes32) -> int:
        plot_count: int = 0
        for receiver in self.service.plot_sync_receivers.values():
            plot_count += sum(
                plot.pool_contract_puzzle_hash == pool_contract_puzzle_hash for plot in receiver.plots().values()
            )
        return plot_count

    async def get_pool_state(self, request: Dict[str, Any]) -> EndpointResult:
        pools_list = []
        for p2_singleton_puzzle_hash, pool_dict in self.service.pool_state.items():
            pool_state = pool_dict.copy()
            pool_state["plot_count"] = self.get_pool_contract_puzzle_hash_plot_count(p2_singleton_puzzle_hash)
            pools_list.append(pool_state)
        return {"pool_state": pools_list}

    async def set_payout_instructions(self, request: Dict[str, Any]) -> EndpointResult:
        launcher_id: bytes32 = bytes32.from_hexstr(request["launcher_id"])
        await self.service.set_payout_instructions(launcher_id, request["payout_instructions"])
        return {}

    async def get_harvesters(self, request: Dict[str, Any]) -> EndpointResult:
        return await self.service.get_harvesters(False)

    async def get_harvesters_summary(self, _: Dict[str, object]) -> EndpointResult:
        return await self.service.get_harvesters(True)

    async def get_harvester_plots_valid(self, request_dict: Dict[str, object]) -> EndpointResult:
        # TODO: Consider having a extra List[PlotInfo] in Receiver to avoid rebuilding the list for each call
        request = PlotInfoRequestData.from_json_dict(request_dict)
        plot_list = list(self.service.get_receiver(request.node_id).plots().values())
        # Apply filter
        plot_list = [
            plot for plot in plot_list if all(plot_matches_filter(plot, filter_item) for filter_item in request.filter)
        ]
        restricted_sort_keys: List[str] = ["pool_contract_puzzle_hash", "pool_public_key", "plot_public_key"]
        # Apply sort_key and reverse if sort_key is not restricted
        if request.sort_key in restricted_sort_keys:
            raise KeyError(f"Can't sort by optional attributes: {restricted_sort_keys}")
        # Sort by plot_id also by default since its unique
        plot_list = sorted(plot_list, key=operator.attrgetter(request.sort_key, "plot_id"), reverse=request.reverse)
        return paginated_plot_request(plot_list, request)

    def paginated_plot_path_request(
        self, source_func: Callable[[Receiver], List[str]], request_dict: Dict[str, object]
    ) -> Dict[str, object]:
        request: PlotPathRequestData = PlotPathRequestData.from_json_dict(request_dict)
        receiver = self.service.get_receiver(request.node_id)
        source = source_func(receiver)
        # Apply filter
        source = [plot for plot in source if all(filter_item in plot for filter_item in request.filter)]
        # Apply reverse
        source = sorted(source, reverse=request.reverse)
        return paginated_plot_request(source, request)

    async def get_harvester_plots_invalid(self, request_dict: Dict[str, object]) -> EndpointResult:
        return self.paginated_plot_path_request(Receiver.invalid, request_dict)

    async def get_harvester_plots_keys_missing(self, request_dict: Dict[str, object]) -> EndpointResult:
        return self.paginated_plot_path_request(Receiver.keys_missing, request_dict)

    async def get_harvester_plots_duplicates(self, request_dict: Dict[str, object]) -> EndpointResult:
        return self.paginated_plot_path_request(Receiver.duplicates, request_dict)

    async def get_pool_login_link(self, request: Dict[str, Any]) -> EndpointResult:
        launcher_id: bytes32 = bytes32.from_hexstr(request["launcher_id"])
        login_link: Optional[str] = await self.service.generate_login_link(launcher_id)
        if login_link is None:
            raise ValueError(f"Failed to generate login link for {launcher_id.hex()}")
        return {"login_link": login_link}
