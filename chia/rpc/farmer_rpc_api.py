from typing import Callable, Dict, List, Optional

from chia.farmer.farmer import Farmer
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class FarmerRpcApi:
    def __init__(self, farmer: Farmer):
        self.service = farmer
        self.service_name = "sit_farmer"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_signage_point": self.get_signage_point,
            "/get_signage_points": self.get_signage_points,
            "/get_reward_targets": self.get_reward_targets,
            "/set_reward_targets": self.set_reward_targets,
            "/get_pool_state": self.get_pool_state,
            "/set_payout_instructions": self.set_payout_instructions,
            "/get_harvesters": self.get_harvesters,
            "/get_pool_login_link": self.get_pool_login_link,
        }

    async def _state_changed(self, change: str, change_data: Dict) -> List[WsRpcMessage]:
        if change == "new_signage_point":
            sp_hash = change_data["sp_hash"]
            data = await self.get_signage_point({"sp_hash": sp_hash.hex()})
            return [
                create_payload_dict(
                    "new_signage_point",
                    data,
                    self.service_name,
                    "wallet_ui",
                )
            ]
        elif change == "new_farming_info":
            return [
                create_payload_dict(
                    "new_farming_info",
                    change_data,
                    self.service_name,
                    "wallet_ui",
                )
            ]
        elif change == "new_plots":
            return [
                create_payload_dict(
                    "get_harvesters",
                    change_data,
                    self.service_name,
                    "wallet_ui",
                )
            ]

        return []

    async def get_signage_point(self, request: Dict) -> Dict:
        sp_hash = hexstr_to_bytes(request["sp_hash"])
        for _, sps in self.service.sps.items():
            for sp in sps:
                if sp.challenge_chain_sp == sp_hash:
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
        raise ValueError(f"Signage point {sp_hash.hex()} not found")

    async def get_signage_points(self, _: Dict) -> Dict:
        result: List = []
        for _, sps in self.service.sps.items():
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

    async def get_reward_targets(self, request: Dict) -> Dict:
        search_for_private_key = request["search_for_private_key"]
        return await self.service.get_reward_targets(search_for_private_key)

    async def set_reward_targets(self, request: Dict) -> Dict:
        farmer_target, pool_target = None, None
        if "farmer_target" in request:
            farmer_target = request["farmer_target"]
        if "pool_target" in request:
            pool_target = request["pool_target"]

        self.service.set_reward_targets(farmer_target, pool_target)
        return {}

    async def get_pool_state(self, _: Dict) -> Dict:
        pools_list = []
        for p2_singleton_puzzle_hash, pool_dict in self.service.pool_state.items():
            pool_state = pool_dict.copy()
            pool_state["p2_singleton_puzzle_hash"] = p2_singleton_puzzle_hash.hex()
            pools_list.append(pool_state)
        return {"pool_state": pools_list}

    async def set_payout_instructions(self, request: Dict) -> Dict:
        launcher_id: bytes32 = hexstr_to_bytes(request["launcher_id"])
        await self.service.set_payout_instructions(launcher_id, request["payout_instructions"])
        return {}

    async def get_harvesters(self, _: Dict):
        return await self.service.get_harvesters()

    async def get_pool_login_link(self, request: Dict) -> Dict:
        launcher_id: bytes32 = bytes32(hexstr_to_bytes(request["launcher_id"]))
        login_link: Optional[str] = await self.service.generate_login_link(launcher_id)
        if login_link is None:
            raise ValueError(f"Failed to generate login link for {launcher_id.hex()}")
        return {"login_link": login_link}
