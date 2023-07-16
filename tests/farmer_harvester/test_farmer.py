from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import pytest
from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS, default_kwargs
from chia.farmer.farmer import increment_pool_stats, strip_old_entries
from chia.pools.pool_config import PoolWalletConfig
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.harvester_protocol import NewProofOfSpace, RespondSignatures
from chia.protocols.pool_protocol import PoolErrorCode
from chia.types.blockchain_format.proof_of_space import (
    ProofOfSpace,
    generate_plot_public_key,
    verify_and_get_quality_string,
)
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64
from tests.conftest import HarvesterFarmerEnvironment
from tests.util.misc import Marks

log = logging.getLogger(__name__)


class StripOldEntriesCase:
    pairs: List[Tuple[float, int]]
    before: float
    expected_result: List[Tuple[float, int]]

    def __init__(self, pairs: List[Tuple[float, int]], before: float, expected_result: List[Tuple[float, int]]):
        self.pairs = pairs
        self.before = before
        self.expected_result = expected_result


class IncrementPoolStatsCase:
    pool_states: Dict[bytes32, Any]
    p2_singleton_puzzle_hash: bytes32
    name: str
    current_time: float
    count: int
    value: Optional[Union[int, Dict[str, Any]]]
    expected_result: Any

    def __init__(
        self,
        p2_singleton_puzzle_hash: bytes32,
        name: str,
        current_time: float,
        count: int,
        value: Optional[Union[int, Dict[str, Any]]],
        expected_result: Any,
    ):
        prepared_p2_singleton_puzzle_hash = std_hash(b"11223344")
        self.pool_states = {
            prepared_p2_singleton_puzzle_hash: {
                "p2_singleton_puzzle_hash": prepared_p2_singleton_puzzle_hash.hex(),
                "xxx_since_start": 1,
                "xxx_24h": [(1689491043, 1)],
                "current_difficulty": 1,
            }
        }
        self.p2_singleton_puzzle_hash = p2_singleton_puzzle_hash
        self.name = name
        self.current_time = current_time
        self.count = count
        self.value = value
        self.expected_result = expected_result


class DummyHarvesterPeer:
    return_invalid_response: bool
    peer_node_id: bytes32 = std_hash(b"1")

    def __init__(self, return_valid_response: bool):
        self.return_invalid_response = return_valid_response

    async def send_message(self, arg1: Any) -> None:
        pass

    async def call_api(self, arg1: Any, request: harvester_protocol.RequestSignatures) -> Any:
        if self.return_invalid_response:
            return 0

        local_sk: PrivateKey = PrivateKey.from_bytes(
            bytes.fromhex("185c61579e152bbd3b2face3245951e7c67f67f8d2fb2aa4a56e178186c1e5fa")
        )
        farmer_public_key = G1Element.from_bytes(
            bytes.fromhex(
                "af59ca047f2f34a4db6e4fa313764f6e71d4c53bc316517e0fa486b8e3d3f36f112ee078e3226854b97791452e3a9fd4"
            )
        )
        agg_pk = generate_plot_public_key(local_sk.get_g1(), farmer_public_key, True)
        message = request.messages[0]
        signature: G2Element = AugSchemeMPL.sign(local_sk, message, agg_pk)
        return RespondSignatures(
            plot_identifier=request.plot_identifier,
            challenge_hash=request.challenge_hash,
            sp_hash=request.sp_hash,
            local_pk=local_sk.get_g1(),
            farmer_pk=farmer_public_key,
            message_signatures=[(message, signature)],
        )


@dataclass
class NewProofOfSpaceCase:
    difficulty: uint64
    sub_slot_iters: uint64
    challenge_hash: bytes32
    sp_hash: bytes32
    plot_identifier: str
    signage_point_index: uint8
    plot_id: bytes32
    plot_size: uint8
    plot_challenge: bytes32
    plot_public_key: G1Element
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: bytes32
    height: uint32
    proof: bytes
    pool_config: PoolWalletConfig
    pool_difficulty: Optional[uint64]
    authentication_token_timeout: Optional[uint8]
    farmer_private_keys: List[PrivateKey]
    authentication_keys: Dict[bytes32, PrivateKey]
    use_invalid_peer_response: bool
    expected_pool_state: Dict[str, Any]
    marks: Marks = ()

    # This creates a test case whose proof of space passes plot filter and quality check
    @classmethod
    def create_verified_quality_case(
        cls,
        difficulty: uint64,
        sub_slot_iters: uint64,
        pool_url: str,
        pool_difficulty: Optional[uint64],
        authentication_token_timeout: Optional[uint8],
        use_invalid_peer_response: bool,
        has_valid_authentication_keys: bool,
        expected_pool_stats: Dict[str, Any],
    ) -> NewProofOfSpaceCase:
        p2_singleton_puzzle_hash = bytes32.fromhex("302e05a1e6af431c22043ae2a9a8f71148c955c372697cb8ab348160976283df")
        pool_config = PoolWalletConfig(
            launcher_id=bytes32.fromhex("ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa"),
            pool_url=pool_url,
            payout_instructions="c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8",
            target_puzzle_hash=bytes32.fromhex("344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58"),
            p2_singleton_puzzle_hash=p2_singleton_puzzle_hash,
            owner_public_key=G1Element.from_bytes(
                bytes.fromhex(
                    "8348455278ecec68325b6754b1f3218cde1511ca9393197e7876d7ae04af1c4dd86b0c50601cf5daeb034e8f7c226537"
                )
            ),
        )

        expected_pool_state = expected_pool_stats.copy()
        expected_pool_state["p2_singleton_puzzle_hash"] = p2_singleton_puzzle_hash.hex()
        expected_pool_state["pool_config"] = pool_config

        return NewProofOfSpaceCase(
            difficulty=difficulty,
            sub_slot_iters=sub_slot_iters,
            challenge_hash=bytes32.fromhex("9dcc155cafa8723627d01d00118767269a15f5f0d496dc9c2940a45b63c0c00c"),
            sp_hash=bytes32.fromhex("bca3ac17a0a8fc072188b3738455a3f006528d181c39e31c88e8755492575272"),
            plot_identifier="test",
            signage_point_index=uint8(1),
            plot_id=bytes32.fromhex("baaa6780c53d4b3739b8807b4ae79a76644ddf0d9e03dc7d0a6a0e613e764d9f"),
            plot_size=uint8(32),
            plot_challenge=bytes32.fromhex("7580e4c366dc2c94c37ce44943f9629a3cd6e027d7b24cd014adeaa578d4b0a2"),
            plot_public_key=G1Element.from_bytes(
                bytes.fromhex(
                    "a6126295fbf0f50dbed8dc41e236241413fdc8a97e650e3e"
                    "d69d66d0921d3236f8961cc1cf8c1b195521c2d9143048e2"
                )
            ),
            pool_public_key=None,
            pool_contract_puzzle_hash=p2_singleton_puzzle_hash,
            height=uint32(1),
            proof=bytes.fromhex(
                "2aa93f8c112c274d3c707d94d0a0e07b6710d96fca284baa198ca4632ee1f591"
                "edad47d97e854aec76dc08519614a0d17253fc24fbaab66f558b2f6afd2210ac"
                "ac09b48e01fd0b8334eae94d55db5df28c80c03a586ce8afe3b986e6aceef4d4"
                "93a7c0b1bf30baaafedc1ef9af6a1eee911e3873e9229a0bf18cfc95bcfc3dac"
                "36522c84a85fd16a3ff501b44024e371bbf7a3ee9d4ded6e05c82e95083ea5ea"
                "d2d64e4a46e0550e98fc56b30760b4bcf439ac0ee675e157fcfecd4b294c6d14"
                "987883e3659777c68d6a6962c770a66817f4dc641b5823b077093df10da031c1"
                "4b32005bf38eb53944bf3bc5a1d19c21e3b96759b7f557b4668687b7a8a36344"
            ),
            pool_config=pool_config,
            pool_difficulty=pool_difficulty,
            authentication_token_timeout=authentication_token_timeout,
            farmer_private_keys=[
                PrivateKey.from_bytes(bytes.fromhex("3cb188d8b2469bb8414a3ec68857959e231a8bec836df199a896ff523b9d2f7d"))
            ],
            authentication_keys={
                p2_singleton_puzzle_hash: PrivateKey.from_bytes(
                    bytes.fromhex("11ed596eb95b31364a9185e948f6b66be30415f816819449d5d40751dc70e786")
                ),
            }
            if has_valid_authentication_keys
            else {},
            use_invalid_peer_response=use_invalid_peer_response,
            expected_pool_state=expected_pool_state,
        )


@pytest.mark.parametrize(
    argnames="case",
    argvalues=[
        pytest.param(StripOldEntriesCase([], 0, []), id="no_params"),
        pytest.param(StripOldEntriesCase([(1689491043.3493967, 1)], 1689491044, []), id="stripped"),
        pytest.param(
            StripOldEntriesCase([(1689491043.3493967, 1)], 1689491043, [(1689491043.3493967, 1)]),
            id="not_stripped",
        ),
    ],
)
def test_strip_old_entries(case: StripOldEntriesCase) -> None:
    assert strip_old_entries(case.pairs, case.before) == case.expected_result


@pytest.mark.parametrize(
    argnames="case",
    argvalues=[
        pytest.param(
            IncrementPoolStatsCase(
                std_hash(b"0"),
                "xxx",
                1689491043.3493967,
                1,
                1,
                None,
            ),
            id="p2_singleton_puzzle_hash_not_exist",
        ),
        pytest.param(
            IncrementPoolStatsCase(
                std_hash(b"11223344"),
                "yyy",
                1689491043.3493967,
                1,
                1,
                {
                    "p2_singleton_puzzle_hash": std_hash(b"11223344").hex(),
                    "xxx_since_start": 1,
                    "xxx_24h": [(1689491043, 1)],
                    "current_difficulty": 1,
                },
            ),
            id="p2_singleton_puzzle_hash_exist_but_no_change",
        ),
        pytest.param(
            IncrementPoolStatsCase(
                std_hash(b"11223344"),
                "xxx",
                1689491044.1,
                1,
                2,
                {
                    "p2_singleton_puzzle_hash": std_hash(b"11223344").hex(),
                    "xxx_since_start": 2,
                    "xxx_24h": [(1689491043, 1), (1689491044, 2)],
                    "current_difficulty": 1,
                },
            ),
            id="value_is_set",
        ),
        pytest.param(
            IncrementPoolStatsCase(
                std_hash(b"11223344"),
                "xxx",
                1689491044.1,
                1,
                None,
                {
                    "p2_singleton_puzzle_hash": std_hash(b"11223344").hex(),
                    "xxx_since_start": 2,
                    "xxx_24h": [(1689491043, 1), (1689491044, 1)],
                    "current_difficulty": 1,
                },
            ),
            id="value_is_not_set",
        ),
        pytest.param(
            IncrementPoolStatsCase(
                std_hash(b"11223344"),
                "xxx",
                1689577444,
                1,
                None,
                {
                    "p2_singleton_puzzle_hash": std_hash(b"11223344").hex(),
                    "xxx_since_start": 2,
                    "xxx_24h": [(1689577444, 1)],
                    "current_difficulty": 1,
                },
            ),
            id="stripped",
        ),
    ],
)
def test_increment_pool_stats(case: IncrementPoolStatsCase) -> None:
    increment_pool_stats(
        case.pool_states, case.p2_singleton_puzzle_hash, case.name, case.current_time, case.count, case.value
    )
    if case.expected_result is None:
        assert case.p2_singleton_puzzle_hash not in case.pool_states
    else:
        assert case.pool_states[case.p2_singleton_puzzle_hash] == case.expected_result


@pytest.mark.parametrize(
    argnames="case",
    argvalues=[
        pytest.param(
            NewProofOfSpaceCase.create_verified_quality_case(
                difficulty=uint64(1),
                sub_slot_iters=uint64(1000000000000),
                pool_url="",
                pool_difficulty=uint64(1),
                authentication_token_timeout=uint8(10),
                use_invalid_peer_response=False,
                has_valid_authentication_keys=True,
                expected_pool_stats={
                    "points_found_since_start": 0,
                    # Original item format here is (timestamp, value) but we'll ignore timestamp part
                    # so every `xxx_24h` item in this dict will be List[Any].
                    "points_found_24h": [],
                    "points_acknowledged_since_start": 0,
                    "points_acknowledged_24h": [],
                    "pool_errors_24h": [],
                    "valid_partials_since_start": 0,
                    "valid_partials_24h": [],
                    "invalid_partials_since_start": 0,
                    "invalid_partials_24h": [],
                    "stale_partials_since_start": 0,
                    "stale_partials_24h": [],
                    "missing_partials_since_start": 1,
                    "missing_partials_24h": [1],
                },
            ),
            id="empty_pool_url",
        ),
        pytest.param(
            NewProofOfSpaceCase.create_verified_quality_case(
                difficulty=uint64(1),
                sub_slot_iters=uint64(1000000000000),
                pool_url="http://localhost",
                pool_difficulty=None,
                authentication_token_timeout=uint8(10),
                use_invalid_peer_response=False,
                has_valid_authentication_keys=True,
                expected_pool_stats={
                    "points_found_since_start": 0,
                    # Original item format here is (timestamp, value) but we'll ignore timestamp part
                    # so every `xxx_24h` item in this dict will be List[Any].
                    "points_found_24h": [],
                    "points_acknowledged_since_start": 0,
                    "points_acknowledged_24h": [],
                    "pool_errors_24h": [],
                    "valid_partials_since_start": 0,
                    "valid_partials_24h": [],
                    "invalid_partials_since_start": 0,
                    "invalid_partials_24h": [],
                    "stale_partials_since_start": 0,
                    "stale_partials_24h": [],
                    "missing_partials_since_start": 1,
                    "missing_partials_24h": [None],
                },
            ),
            id="empty_current_difficulty",
        ),
        pytest.param(
            NewProofOfSpaceCase.create_verified_quality_case(
                difficulty=uint64(1),
                sub_slot_iters=uint64(64),
                pool_url="http://localhost",
                pool_difficulty=uint64(1),
                authentication_token_timeout=uint8(10),
                use_invalid_peer_response=False,
                has_valid_authentication_keys=True,
                expected_pool_stats={
                    "points_found_since_start": 0,
                    # Original item format here is (timestamp, value) but we'll ignore timestamp part
                    # so every `xxx_24h` item in this dict will be List[Any].
                    "points_found_24h": [],
                    "points_acknowledged_since_start": 0,
                    "points_acknowledged_24h": [],
                    "pool_errors_24h": [],
                    "valid_partials_since_start": 0,
                    "valid_partials_24h": [],
                    "invalid_partials_since_start": 1,
                    "invalid_partials_24h": [1],
                    "stale_partials_since_start": 0,
                    "stale_partials_24h": [],
                    "missing_partials_since_start": 0,
                    "missing_partials_24h": [],
                },
            ),
            id="quality_not_good",
        ),
        pytest.param(
            NewProofOfSpaceCase.create_verified_quality_case(
                difficulty=uint64(1),
                sub_slot_iters=uint64(1000000000000),
                pool_url="http://localhost",
                pool_difficulty=uint64(1),
                authentication_token_timeout=None,
                use_invalid_peer_response=False,
                has_valid_authentication_keys=True,
                expected_pool_stats={
                    "points_found_since_start": 0,
                    # Original item format here is (timestamp, value) but we'll ignore timestamp part
                    # so every `xxx_24h` item in this dict will be List[Any].
                    "points_found_24h": [],
                    "points_acknowledged_since_start": 0,
                    "points_acknowledged_24h": [],
                    "pool_errors_24h": [],
                    "valid_partials_since_start": 0,
                    "valid_partials_24h": [],
                    "invalid_partials_since_start": 0,
                    "invalid_partials_24h": [],
                    "stale_partials_since_start": 0,
                    "stale_partials_24h": [],
                    "missing_partials_since_start": 1,
                    "missing_partials_24h": [1],
                },
            ),
            id="empty_auth_timeout",
        ),
        pytest.param(
            NewProofOfSpaceCase.create_verified_quality_case(
                difficulty=uint64(1),
                sub_slot_iters=uint64(1000000000000),
                pool_url="http://localhost",
                pool_difficulty=uint64(1),
                authentication_token_timeout=uint8(10),
                use_invalid_peer_response=True,
                has_valid_authentication_keys=True,
                expected_pool_stats={
                    "points_found_since_start": 0,
                    # Original item format here is (timestamp, value) but we'll ignore timestamp part
                    # so every `xxx_24h` item in this dict will be List[Any].
                    "points_found_24h": [],
                    "points_acknowledged_since_start": 0,
                    "points_acknowledged_24h": [],
                    "pool_errors_24h": [],
                    "valid_partials_since_start": 0,
                    "valid_partials_24h": [],
                    "invalid_partials_since_start": 1,
                    "invalid_partials_24h": [1],
                    "stale_partials_since_start": 0,
                    "stale_partials_24h": [],
                    "missing_partials_since_start": 0,
                    "missing_partials_24h": [],
                },
            ),
            id="invalid_peer_response",
        ),
        pytest.param(
            NewProofOfSpaceCase.create_verified_quality_case(
                difficulty=uint64(1),
                sub_slot_iters=uint64(1000000000000),
                pool_url="http://localhost",
                pool_difficulty=uint64(1),
                authentication_token_timeout=uint8(10),
                use_invalid_peer_response=False,
                has_valid_authentication_keys=False,
                expected_pool_stats={
                    "points_found_since_start": 0,
                    # Original item format here is (timestamp, value) but we'll ignore timestamp part
                    # so every `xxx_24h` item in this dict will be List[Any].
                    "points_found_24h": [],
                    "points_acknowledged_since_start": 0,
                    "points_acknowledged_24h": [],
                    "pool_errors_24h": [],
                    "valid_partials_since_start": 0,
                    "valid_partials_24h": [],
                    "invalid_partials_since_start": 0,
                    "invalid_partials_24h": [],
                    "stale_partials_since_start": 0,
                    "stale_partials_24h": [],
                    "missing_partials_since_start": 1,
                    "missing_partials_24h": [1],
                },
            ),
            id="no_valid_auth_keys",
        ),
        pytest.param(
            NewProofOfSpaceCase.create_verified_quality_case(
                difficulty=uint64(1),
                sub_slot_iters=uint64(1000000000000),
                pool_url="http://192.168.0.256",
                pool_difficulty=uint64(1),
                authentication_token_timeout=uint8(10),
                use_invalid_peer_response=False,
                has_valid_authentication_keys=True,
                expected_pool_stats={
                    "points_found_since_start": 1,
                    # Original item format here is (timestamp, value) but we'll ignore timestamp part
                    # so every `xxx_24h` item in this dict will be List[Any].
                    "points_found_24h": [1],
                    "points_acknowledged_since_start": 0,
                    "points_acknowledged_24h": [],
                    "pool_errors_24h": [{"error_code": uint16(PoolErrorCode.REQUEST_FAILED.value)}],
                    "valid_partials_since_start": 0,
                    "valid_partials_24h": [],
                    "invalid_partials_since_start": 1,
                    "invalid_partials_24h": [1],
                    "stale_partials_since_start": 0,
                    "stale_partials_24h": [],
                    "missing_partials_since_start": 0,
                    "missing_partials_24h": [],
                },
            ),
            id="error_connecting_pool_server",
        ),
    ],
)
@pytest.mark.asyncio
async def test_farmer_new_proof_of_space_for_pool_stats(
    harvester_farmer_environment: HarvesterFarmerEnvironment,
    case: NewProofOfSpaceCase,
) -> None:
    farmer_service, farmer_rpc_client, _, _, _ = harvester_farmer_environment
    farmer_api = farmer_service._api

    sp = farmer_protocol.NewSignagePoint(
        challenge_hash=case.challenge_hash,
        challenge_chain_sp=case.sp_hash,
        reward_chain_sp=std_hash(b"1"),
        difficulty=case.difficulty,
        sub_slot_iters=case.sub_slot_iters,
        signage_point_index=case.signage_point_index,
        peak_height=uint32(1),
    )
    pos = ProofOfSpace(
        challenge=case.plot_challenge,
        pool_public_key=case.pool_public_key,
        pool_contract_puzzle_hash=case.pool_contract_puzzle_hash,
        plot_public_key=case.plot_public_key,
        size=case.plot_size,
        proof=case.proof,
    )
    new_pos = NewProofOfSpace(
        challenge_hash=case.challenge_hash,
        sp_hash=case.sp_hash,
        plot_identifier=case.plot_identifier,
        proof=pos,
        signage_point_index=case.signage_point_index,
    )

    p2_singleton_puzzle_hash = case.pool_contract_puzzle_hash
    constant_kwargs = default_kwargs.copy()
    constant_kwargs["POOL_SUB_SLOT_ITERS"] = case.sub_slot_iters
    farmer_api.farmer.constants = ConsensusConstants(**constant_kwargs)  # type: ignore
    farmer_api.farmer._private_keys = case.farmer_private_keys
    farmer_api.farmer.authentication_keys = case.authentication_keys
    farmer_api.farmer.sps[case.sp_hash] = [sp]
    farmer_api.farmer.pool_state[p2_singleton_puzzle_hash] = {
        "p2_singleton_puzzle_hash": p2_singleton_puzzle_hash.hex(),
        "points_found_since_start": 0,
        "points_found_24h": [],
        "points_acknowledged_since_start": 0,
        "points_acknowledged_24h": [],
        "next_farmer_update": 0,
        "next_pool_info_update": 0,
        "current_points": 0,
        "current_difficulty": case.pool_difficulty,
        "pool_errors_24h": [],
        "valid_partials_since_start": 0,
        "valid_partials_24h": [],
        "invalid_partials_since_start": 0,
        "invalid_partials_24h": [],
        "stale_partials_since_start": 0,
        "stale_partials_24h": [],
        "missing_partials_since_start": 0,
        "missing_partials_24h": [],
        "authentication_token_timeout": case.authentication_token_timeout,
        "plot_count": 0,
        "pool_config": case.pool_config,
    }

    assert (
        verify_and_get_quality_string(pos, DEFAULT_CONSTANTS, case.challenge_hash, case.sp_hash, height=uint32(1))
        is not None
    )

    peer: Any = DummyHarvesterPeer(case.use_invalid_peer_response)
    await farmer_api.new_proof_of_space(new_pos, peer)

    def assert_stats_since_start(name: str) -> None:
        assert farmer_api.farmer.pool_state[p2_singleton_puzzle_hash][name] == case.expected_pool_state[name]

    def assert_stats_24h(name: str) -> None:
        assert len(farmer_api.farmer.pool_state[p2_singleton_puzzle_hash][name]) == len(case.expected_pool_state[name])
        for i, stat in enumerate(farmer_api.farmer.pool_state[p2_singleton_puzzle_hash][name]):
            assert stat[1] == case.expected_pool_state[name][i]

    def assert_pool_errors_24h() -> None:
        assert len(farmer_api.farmer.pool_state[p2_singleton_puzzle_hash]["pool_errors_24h"]) == len(
            case.expected_pool_state["pool_errors_24h"]
        )
        for i, stat in enumerate(farmer_api.farmer.pool_state[p2_singleton_puzzle_hash]["pool_errors_24h"]):
            assert stat[1]["error_code"] == case.expected_pool_state["pool_errors_24h"][i]["error_code"]

    assert_stats_since_start("points_found_since_start")
    assert_stats_24h("points_found_24h")
    assert_stats_since_start("points_acknowledged_since_start")
    assert_stats_24h("points_acknowledged_24h")
    assert_pool_errors_24h()
    assert_stats_since_start("valid_partials_since_start")
    assert_stats_24h("valid_partials_24h")
    assert_stats_since_start("invalid_partials_since_start")
    assert_stats_24h("invalid_partials_24h")
    assert_stats_since_start("stale_partials_since_start")
    assert_stats_24h("stale_partials_24h")
    assert_stats_since_start("missing_partials_since_start")
    assert_stats_24h("missing_partials_24h")
