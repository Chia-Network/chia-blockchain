from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import time
from types import TracebackType
from typing import Any, Dict, List, Optional, Tuple, Type, Union, cast
from unittest.mock import ANY

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey
from pytest_mock import MockerFixture
from yarl import URL

from chia import __version__
from chia._tests.conftest import HarvesterFarmerEnvironment
from chia._tests.util.misc import DataCase, Marks, datacases
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.farmer.farmer import UPDATE_POOL_FARMER_INFO_INTERVAL, Farmer, increment_pool_stats, strip_old_entries
from chia.pools.pool_config import PoolWalletConfig
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.harvester_protocol import NewProofOfSpace, RespondSignatures
from chia.protocols.pool_protocol import PoolErrorCode
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools
from chia.types.aliases import FarmerService, HarvesterService
from chia.types.blockchain_format.proof_of_space import (
    ProofOfSpace,
    generate_plot_public_key,
    verify_and_get_quality_string,
)
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config, save_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64

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
    version: str

    def __init__(self, return_invalid_response: bool = False, version: str = "1.0.0"):
        self.return_invalid_response = return_invalid_response
        self.version = version

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
            include_source_signature_data=False,
            farmer_reward_address_override=None,
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
            authentication_keys=(
                {
                    p2_singleton_puzzle_hash: PrivateKey.from_bytes(
                        bytes.fromhex("11ed596eb95b31364a9185e948f6b66be30415f816819449d5d40751dc70e786")
                    ),
                }
                if has_valid_authentication_keys
                else {}
            ),
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
                    "valid_partials_since_start": 1,
                    "valid_partials_24h": [1],
                    "invalid_partials_since_start": 0,
                    "invalid_partials_24h": [],
                    "insufficient_partials_since_start": 0,
                    "insufficient_partials_24h": [],
                    "stale_partials_since_start": 0,
                    "stale_partials_24h": [],
                    "missing_partials_since_start": 0,
                    "missing_partials_24h": [],
                },
            ),
            # Empty pool_url means solo plotNFT farming
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
                    "insufficient_partials_since_start": 0,
                    "insufficient_partials_24h": [],
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
                    "invalid_partials_since_start": 0,
                    "invalid_partials_24h": [],
                    "insufficient_partials_since_start": 1,
                    "insufficient_partials_24h": [1],
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
                    "insufficient_partials_since_start": 0,
                    "insufficient_partials_24h": [],
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
                    "insufficient_partials_since_start": 0,
                    "insufficient_partials_24h": [],
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
                    "insufficient_partials_since_start": 0,
                    "insufficient_partials_24h": [],
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
                    "insufficient_partials_since_start": 0,
                    "insufficient_partials_24h": [],
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
@pytest.mark.anyio
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
        include_source_signature_data=False,
        farmer_reward_address_override=None,
        fee_info=None,
    )

    p2_singleton_puzzle_hash = case.pool_contract_puzzle_hash
    farmer_api.farmer.constants = DEFAULT_CONSTANTS.replace(POOL_SUB_SLOT_ITERS=case.sub_slot_iters)
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
        "insufficient_partials_since_start": 0,
        "insufficient_partials_24h": [],
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
    assert_stats_since_start("insufficient_partials_since_start")
    assert_stats_24h("insufficient_partials_24h")
    assert_stats_since_start("stale_partials_since_start")
    assert_stats_24h("stale_partials_24h")
    assert_stats_since_start("missing_partials_since_start")
    assert_stats_24h("missing_partials_24h")


@dataclass
class DummyPoolResponse:
    ok: bool
    status: int
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    new_difficulty: Optional[int] = None

    async def text(self) -> str:
        json_dict: Dict[str, Any] = dict()
        if self.error_code:
            json_dict["error_code"] = self.error_code
            json_dict["error_message"] = self.error_message if self.error_message else "error-msg"
        elif self.new_difficulty:
            json_dict["new_difficulty"] = self.new_difficulty

        return json.dumps(json_dict)

    async def __aenter__(self) -> DummyPoolResponse:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        pass


def create_valid_pos(farmer: Farmer) -> Tuple[farmer_protocol.NewSignagePoint, ProofOfSpace, NewProofOfSpace]:
    case = NewProofOfSpaceCase.create_verified_quality_case(
        difficulty=uint64(1),
        sub_slot_iters=uint64(1000000000000),
        pool_url="https://192.168.0.256",
        pool_difficulty=uint64(1),
        authentication_token_timeout=uint8(10),
        use_invalid_peer_response=False,
        has_valid_authentication_keys=True,
        expected_pool_stats={},
    )
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
        include_source_signature_data=False,
        farmer_reward_address_override=None,
        fee_info=None,
    )
    p2_singleton_puzzle_hash = case.pool_contract_puzzle_hash
    farmer.constants = DEFAULT_CONSTANTS.replace(POOL_SUB_SLOT_ITERS=case.sub_slot_iters)
    farmer._private_keys = case.farmer_private_keys
    farmer.authentication_keys = case.authentication_keys
    farmer.sps[case.sp_hash] = [sp]
    farmer.pool_state[p2_singleton_puzzle_hash] = {
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
        "insufficient_partials_since_start": 0,
        "insufficient_partials_24h": [],
        "stale_partials_since_start": 0,
        "stale_partials_24h": [],
        "missing_partials_since_start": 0,
        "missing_partials_24h": [],
        "authentication_token_timeout": case.authentication_token_timeout,
        "plot_count": 0,
        "pool_config": case.pool_config,
    }
    return sp, pos, new_pos


def override_pool_state(overrides: Dict[str, Any]) -> Dict[str, Any]:
    pool_state = {
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
        "insufficient_partials_since_start": 0,
        "insufficient_partials_24h": [],
        "stale_partials_since_start": 0,
        "stale_partials_24h": [],
        "missing_partials_since_start": 0,
        "missing_partials_24h": [],
    }
    for key, value in overrides.items():
        pool_state[key] = value
    return pool_state


@dataclass
class PoolStateCase:
    id: str
    pool_response: DummyPoolResponse
    expected_pool_state: Dict[str, Any]
    marks: Marks = ()


@datacases(
    PoolStateCase(
        "valid_response",
        DummyPoolResponse(True, 200, new_difficulty=123),
        override_pool_state(
            {
                "points_found_since_start": 1,
                "points_found_24h": [1],
                "points_acknowledged_since_start": 123,
                "points_acknowledged_24h": [123],
                "valid_partials_since_start": 1,
                "valid_partials_24h": [1],
            }
        ),
    ),
    PoolStateCase(
        "response_not_ok",
        DummyPoolResponse(False, 500),
        override_pool_state(
            {
                "points_found_since_start": 1,
                "points_found_24h": [1],
                "invalid_partials_since_start": 1,
                "invalid_partials_24h": [1],
            }
        ),
    ),
    PoolStateCase(
        "stale_partial",
        DummyPoolResponse(True, 200, error_code=uint16(PoolErrorCode.TOO_LATE.value)),
        override_pool_state(
            {
                "points_found_since_start": 1,
                "points_found_24h": [1],
                "pool_errors_24h": [{"error_code": uint16(PoolErrorCode.TOO_LATE.value)}],
                "stale_partials_since_start": 1,
                "stale_partials_24h": [1],
            }
        ),
    ),
    PoolStateCase(
        "insufficient_partial",
        DummyPoolResponse(True, 200, error_code=uint16(PoolErrorCode.PROOF_NOT_GOOD_ENOUGH.value)),
        override_pool_state(
            {
                "points_found_since_start": 1,
                "points_found_24h": [1],
                "pool_errors_24h": [{"error_code": uint16(PoolErrorCode.PROOF_NOT_GOOD_ENOUGH.value)}],
                "insufficient_partials_since_start": 1,
                "insufficient_partials_24h": [1],
            }
        ),
    ),
    PoolStateCase(
        "other_failed_partial",
        DummyPoolResponse(True, 200, error_code=uint16(PoolErrorCode.SERVER_EXCEPTION.value)),
        override_pool_state(
            {
                "points_found_since_start": 1,
                "points_found_24h": [1],
                "pool_errors_24h": [{"error_code": uint16(PoolErrorCode.SERVER_EXCEPTION.value)}],
                "invalid_partials_since_start": 1,
                "invalid_partials_24h": [1],
            }
        ),
    ),
)
@pytest.mark.anyio
async def test_farmer_pool_response(
    mocker: MockerFixture,
    farmer_one_harvester: Tuple[List[HarvesterService], FarmerService, BlockTools],
    case: PoolStateCase,
) -> None:
    _, farmer_service, _ = farmer_one_harvester
    assert farmer_service.rpc_server is not None
    farmer_api = farmer_service._api

    sp, pos, new_pos = create_valid_pos(farmer_api.farmer)
    assert pos.pool_contract_puzzle_hash is not None
    p2_singleton_puzzle_hash: bytes32 = pos.pool_contract_puzzle_hash

    assert (
        verify_and_get_quality_string(
            pos, DEFAULT_CONSTANTS, sp.challenge_hash, sp.challenge_chain_sp, height=uint32(1)
        )
        is not None
    )

    pool_response = case.pool_response
    expected_pool_state = case.expected_pool_state

    mock_http_post = mocker.patch("aiohttp.ClientSession.post", return_value=pool_response)

    peer = cast(WSChiaConnection, DummyHarvesterPeer(False))
    await farmer_api.new_proof_of_space(new_pos, peer)

    mock_http_post.assert_called_once()

    def assert_stats_since_start(name: str) -> None:
        assert farmer_api.farmer.pool_state[p2_singleton_puzzle_hash][name] == expected_pool_state[name]

    def assert_stats_24h(name: str) -> None:
        assert len(farmer_api.farmer.pool_state[p2_singleton_puzzle_hash][name]) == len(expected_pool_state[name])
        for i, stat in enumerate(farmer_api.farmer.pool_state[p2_singleton_puzzle_hash][name]):
            assert stat[1] == expected_pool_state[name][i]

    def assert_pool_errors_24h() -> None:
        assert len(farmer_api.farmer.pool_state[p2_singleton_puzzle_hash]["pool_errors_24h"]) == len(
            expected_pool_state["pool_errors_24h"]
        )
        for i, stat in enumerate(farmer_api.farmer.pool_state[p2_singleton_puzzle_hash]["pool_errors_24h"]):
            assert stat[1]["error_code"] == expected_pool_state["pool_errors_24h"][i]["error_code"]

    assert_stats_since_start("points_found_since_start")
    assert_stats_24h("points_found_24h")
    assert_stats_since_start("points_acknowledged_since_start")
    assert_stats_24h("points_acknowledged_24h")
    assert_pool_errors_24h()
    assert_stats_since_start("valid_partials_since_start")
    assert_stats_24h("valid_partials_24h")
    assert_stats_since_start("invalid_partials_since_start")
    assert_stats_24h("invalid_partials_24h")
    assert_stats_since_start("insufficient_partials_since_start")
    assert_stats_24h("insufficient_partials_24h")
    assert_stats_since_start("stale_partials_since_start")
    assert_stats_24h("stale_partials_24h")
    assert_stats_since_start("missing_partials_since_start")
    assert_stats_24h("missing_partials_24h")


def make_pool_list_entry(overrides: Dict[str, Any]) -> Dict[str, Any]:
    pool_list_entry = {
        "owner_public_key": "84c3fcf9d5581c1ddc702cb0f3b4a06043303b334dd993ab42b2c320ebfa98e5ce558448615b3f69638ba92cf7f43da5",  # noqa: E501
        "p2_singleton_puzzle_hash": "302e05a1e6af431c22043ae2a9a8f71148c955c372697cb8ab348160976283df",
        "payout_instructions": "c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8",
        "pool_url": "localhost",
        "launcher_id": "ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa",
        "target_puzzle_hash": "344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58",
    }
    for key, value in overrides.items():
        pool_list_entry[key] = value
    return pool_list_entry


def make_pool_info() -> Dict[str, Any]:
    return {
        "name": "Pool Name",
        "description": "Pool Description",
        "logo_url": "https://subdomain.pool-domain.tld/path/to/logo.svg",
        "target_puzzle_hash": "344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58",
        "fee": "0.01",
        "protocol_version": 1,
        "relative_lock_height": 100,
        "minimum_difficulty": 1,
        "authentication_token_timeout": 5,
    }


def make_pool_state(p2_singleton_puzzle_hash: bytes32, overrides: Dict[str, Any]) -> Dict[str, Any]:
    pool_info = {
        "p2_singleton_puzzle_hash": p2_singleton_puzzle_hash.hex(),
        "points_found_since_start": 0,
        "points_found_24h": [],
        "points_acknowledged_since_start": 0,
        "points_acknowledged_24h": [],
        "next_farmer_update": 0,
        "next_pool_info_update": 0,
        "current_points": 0,
        "current_difficulty": None,
        "pool_errors_24h": [],
        "valid_partials_since_start": 0,
        "valid_partials_24h": [],
        "invalid_partials_since_start": 0,
        "invalid_partials_24h": [],
        "insufficient_partials_since_start": 0,
        "insufficient_partials_24h": [],
        "stale_partials_since_start": 0,
        "stale_partials_24h": [],
        "missing_partials_since_start": 0,
        "missing_partials_24h": [],
        "authentication_token_timeout": None,
        "plot_count": 0,
    }
    for key, value in overrides.items():
        pool_info[key] = value
    return pool_info


@dataclass
class DummyClientResponse:
    status: int


@dataclass
class DummyPoolInfoResponse:
    ok: bool
    status: int
    url: URL
    pool_info: Optional[Dict[str, Any]] = None
    history: Tuple[DummyClientResponse, ...] = ()

    async def text(self) -> str:
        if self.pool_info is None:
            return ""

        return json.dumps(self.pool_info)

    async def __aenter__(self) -> DummyPoolInfoResponse:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        pass


@dataclass
class PoolInfoCase(DataCase):
    _id: str
    initial_pool_url_in_config: str
    pool_response: DummyPoolInfoResponse
    expected_pool_url_in_config: str
    marks: Marks = ()

    @property
    def id(self) -> str:
        return self._id


@datacases(
    PoolInfoCase(
        "valid_response_without_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=True,
            status=200,
            url=URL("https://endpoint-1.pool-domain.tld/some-path"),
            pool_info=make_pool_info(),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
    PoolInfoCase(
        "valid_response_with_301_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=True,
            status=200,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            pool_info=make_pool_info(),
            history=tuple([DummyClientResponse(status=301)]),
        ),
        expected_pool_url_in_config="https://endpoint-1337.pool-domain.tld/some-other-path",
    ),
    PoolInfoCase(
        "valid_response_with_302_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=True,
            status=200,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            pool_info=make_pool_info(),
            history=tuple([DummyClientResponse(status=302)]),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
    PoolInfoCase(
        "valid_response_with_307_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=True,
            status=200,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            pool_info=make_pool_info(),
            history=tuple([DummyClientResponse(status=307)]),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
    PoolInfoCase(
        "valid_response_with_308_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=True,
            status=200,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            pool_info=make_pool_info(),
            history=tuple([DummyClientResponse(status=308)]),
        ),
        expected_pool_url_in_config="https://endpoint-1337.pool-domain.tld/some-other-path",
    ),
    PoolInfoCase(
        "valid_response_with_multiple_308_redirects",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=True,
            status=200,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            pool_info=make_pool_info(),
            history=tuple([DummyClientResponse(status=308), DummyClientResponse(status=308)]),
        ),
        expected_pool_url_in_config="https://endpoint-1337.pool-domain.tld/some-other-path",
    ),
    PoolInfoCase(
        "valid_response_with_multiple_307_and_308_redirects",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=True,
            status=200,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            pool_info=make_pool_info(),
            history=tuple([DummyClientResponse(status=307), DummyClientResponse(status=308)]),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
    PoolInfoCase(
        "failed_request_without_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=False,
            status=500,
            url=URL("https://endpoint-1.pool-domain.tld/some-path"),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
    PoolInfoCase(
        "failed_request_with_301_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=False,
            status=500,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            history=tuple([DummyClientResponse(status=301)]),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
    PoolInfoCase(
        "failed_request_with_302_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=False,
            status=500,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            history=tuple([DummyClientResponse(status=302)]),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
    PoolInfoCase(
        "failed_request_with_307_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=False,
            status=500,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            history=tuple([DummyClientResponse(status=307)]),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
    PoolInfoCase(
        "failed_request_with_308_redirect",
        initial_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
        pool_response=DummyPoolInfoResponse(
            ok=False,
            status=500,
            url=URL("https://endpoint-1337.pool-domain.tld/some-other-path"),
            history=tuple([DummyClientResponse(status=308)]),
        ),
        expected_pool_url_in_config="https://endpoint-1.pool-domain.tld/some-path",
    ),
)
@pytest.mark.anyio
async def test_farmer_pool_info_config_update(
    mocker: MockerFixture,
    farmer_one_harvester: Tuple[List[HarvesterService], FarmerService, BlockTools],
    case: PoolInfoCase,
) -> None:
    _, farmer_service, _ = farmer_one_harvester
    p2_singleton_puzzle_hash = bytes32.fromhex("302e05a1e6af431c22043ae2a9a8f71148c955c372697cb8ab348160976283df")
    farmer_service._node.authentication_keys = {
        p2_singleton_puzzle_hash: PrivateKey.from_bytes(
            bytes.fromhex("11ed596eb95b31364a9185e948f6b66be30415f816819449d5d40751dc70e786")
        ),
    }
    farmer_service._node.pool_state[p2_singleton_puzzle_hash] = make_pool_state(
        p2_singleton_puzzle_hash,
        overrides={
            "next_farmer_update": time() + UPDATE_POOL_FARMER_INFO_INTERVAL,
        },
    )
    config = load_config(farmer_service.root_path, "config.yaml")
    config["pool"]["pool_list"] = [
        make_pool_list_entry(
            overrides={
                "p2_singleton_puzzle_hash": p2_singleton_puzzle_hash.hex(),
                "pool_url": case.initial_pool_url_in_config,
            }
        )
    ]
    save_config(farmer_service.root_path, "config.yaml", config)
    mock_http_get = mocker.patch("aiohttp.ClientSession.get", return_value=case.pool_response)

    await farmer_service._node.update_pool_state()

    mock_http_get.assert_called_once()
    config = load_config(farmer_service.root_path, "config.yaml")
    assert len(config["pool"]["pool_list"]) == 1
    assert config["pool"]["pool_list"][0]["p2_singleton_puzzle_hash"] == p2_singleton_puzzle_hash.hex()
    assert config["pool"]["pool_list"][0]["pool_url"] == case.expected_pool_url_in_config


@dataclass
class PartialSubmitHeaderCase(DataCase):
    _id: str
    harvester_peer: DummyHarvesterPeer
    expected_headers: Dict[str, str]
    marks: Marks = ()

    @property
    def id(self) -> str:
        return self._id


@datacases(
    PartialSubmitHeaderCase(
        "additional version headers",
        harvester_peer=DummyHarvesterPeer(
            version="1.2.3.asdf42",
        ),
        expected_headers={
            "User-Agent": f"Chia Blockchain v.{__version__}",
            "chia-farmer-version": __version__,
            "chia-harvester-version": "1.2.3.asdf42",
        },
    ),
)
@pytest.mark.anyio
async def test_farmer_additional_headers_on_partial_submit(
    mocker: MockerFixture,
    farmer_one_harvester: Tuple[List[HarvesterService], FarmerService, BlockTools],
    case: PartialSubmitHeaderCase,
) -> None:
    _, farmer_service, _ = farmer_one_harvester
    assert farmer_service.rpc_server is not None
    farmer_api = farmer_service._api

    sp, pos, new_pos = create_valid_pos(farmer_api.farmer)
    assert pos.pool_contract_puzzle_hash is not None

    assert (
        verify_and_get_quality_string(
            pos, DEFAULT_CONSTANTS, sp.challenge_hash, sp.challenge_chain_sp, height=uint32(1)
        )
        is not None
    )

    mock_http_post = mocker.patch(
        "aiohttp.ClientSession.post",
        return_value=DummyPoolResponse(True, 200, new_difficulty=123),
    )

    peer = cast(WSChiaConnection, case.harvester_peer)
    await farmer_api.new_proof_of_space(new_pos, peer)

    mock_http_post.assert_called_once_with(ANY, json=ANY, ssl=ANY, headers=case.expected_headers)
