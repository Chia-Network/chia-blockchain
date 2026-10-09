from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from chia_rs import AugSchemeMPL, PlotParam
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64
from pytest_mock import MockerFixture

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.plotting.prover import PlotVersion
from chia.plotting.util import stream_plot_info_ph, stream_plot_info_pk
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.pool_protocol import PostPartialRequest
from chia.types.blockchain_format.proof_of_space import generate_plot_public_key, generate_plot_public_key_v2, make_pos
from chia.util.hash import std_hash
from chia.wallet.derive_keys import master_sk_to_local_sk


@pytest.fixture(params=["v1-pool-key", "v1-contract", "v2-contract"])
def signing_setup(
    request: pytest.FixtureRequest, tmp_path: Path, mocker: MockerFixture
) -> tuple[FarmerAPI, HarvesterAPI, harvester_protocol.NewProofOfSpace]:
    v2 = request.param == "v2-contract"
    portable = request.param != "v1-pool-key"
    master_sk = AugSchemeMPL.key_gen(b"1" * 32)
    local_pk = master_sk_to_local_sk(master_sk).get_g1()
    farmer_sk = AugSchemeMPL.key_gen(b"2" * 32)
    farmer_pk = farmer_sk.get_g1()
    pool_sk = AugSchemeMPL.key_gen(b"3" * 32)
    pool_pk = None if portable else pool_sk.get_g1()
    puzzle_hash = bytes32(b"4" * 32) if portable else None
    plot_pk = (
        generate_plot_public_key_v2(local_pk, farmer_pk)
        if v2
        else generate_plot_public_key(local_pk, farmer_pk, portable)
    )
    memo = (
        stream_plot_info_ph(puzzle_hash, farmer_pk, master_sk)
        if puzzle_hash is not None
        else stream_plot_info_pk(pool_sk.get_g1(), farmer_pk, master_sk)
    )
    path = tmp_path / ("plot.plot2" if v2 else "plot.plot")
    harvester = Mock(spec=Harvester)
    harvester.plot_manager = MagicMock()
    harvester.plot_manager.plots = {
        path: Mock(
            prover=Mock(
                get_memo=Mock(return_value=memo),
                get_version=Mock(return_value=PlotVersion.V2 if v2 else PlotVersion.V1),
            )
        )
    }
    sp = farmer_protocol.NewSignagePoint(
        std_hash(b"challenge"),
        std_hash(b"cc"),
        std_hash(b"rc"),
        uint64(1),
        uint64(1000),
        uint8(1),
        uint32(1),
        uint32(0),
    )
    proof = make_pos(
        std_hash(b"plot challenge"),
        pool_pk,
        puzzle_hash,
        plot_pk,
        PlotParam.make_v2(uint16(3), uint8(0), uint8(2)) if v2 else PlotParam.make_v1(uint8(32)),
        b"",
    )
    # Exercise signing independently of the pending V2 identifier-routing changes.
    identifier = std_hash(b"quality").hex() + str(path)
    new_proof = harvester_protocol.NewProofOfSpace(
        sp.challenge_hash, sp.challenge_chain_sp, identifier, proof, sp.signage_point_index, False, None, None
    )
    farmer = Mock(spec=Farmer)
    farmer.log = logging.getLogger(__name__)
    farmer.constants = DEFAULT_CONSTANTS
    farmer.sps = {sp.challenge_chain_sp: [sp]}
    farmer.proofs_of_space = {sp.challenge_chain_sp: [(identifier, proof)]}
    farmer.get_private_keys.return_value = [farmer_sk]
    farmer.pool_sks_map = {bytes(pool_sk.get_g1()): pool_sk}
    farmer.pool_target = std_hash(b"pool target")
    farmer.farmer_target = std_hash(b"farmer target")
    mocker.patch("chia.farmer.farmer_api.verify_and_get_quality_string", return_value=std_hash(b"quality"))
    return FarmerAPI(farmer), HarvesterAPI(harvester), new_proof


@pytest.mark.anyio
@pytest.mark.parametrize("signage_point", [True, False], ids=["signage-point", "block"])
async def test_plot_signatures(
    signing_setup: tuple[FarmerAPI, HarvesterAPI, harvester_protocol.NewProofOfSpace], signage_point: bool
) -> None:
    farmer_api, harvester_api, new_proof = signing_setup
    sp = farmer_api.farmer.sps[new_proof.sp_hash][0]
    messages = (
        [sp.challenge_chain_sp, sp.reward_chain_sp]
        if signage_point
        else [std_hash(b"foliage"), std_hash(b"foliage transaction")]
    )
    request = harvester_protocol.RequestSignatures(
        new_proof.plot_identifier, new_proof.challenge_hash, new_proof.sp_hash, messages, None, None
    )
    response = await harvester_api.request_signatures(request)
    assert response is not None
    signatures = harvester_protocol.RespondSignatures.from_bytes(response.data)
    result = farmer_api._process_respond_signatures(signatures)
    if signage_point:
        assert isinstance(result, farmer_protocol.DeclareProofOfSpace)
        aggregate_signatures = [result.challenge_chain_sp_signature, result.reward_chain_sp_signature]
    else:
        assert isinstance(result, farmer_protocol.SignedValues)
        aggregate_signatures = [result.foliage_block_data_signature, result.foliage_transaction_block_signature]
    for message, signature in zip(messages, aggregate_signatures):
        assert AugSchemeMPL.verify(new_proof.proof.plot_public_key, message, signature)


@pytest.mark.anyio
async def test_pool_partial_signature(
    signing_setup: tuple[FarmerAPI, HarvesterAPI, harvester_protocol.NewProofOfSpace], mocker: MockerFixture
) -> None:
    farmer_api, harvester_api, new_proof = signing_setup
    if new_proof.proof.pool_contract_puzzle_hash is None:
        pytest.skip("Pool partials require a contract plot")
    farmer = farmer_api.farmer
    farmer.config = {}
    farmer.number_of_responses = {}
    farmer.cache_add_time = {}
    farmer.pool_state = {
        new_proof.proof.pool_contract_puzzle_hash: {
            "pool_config": Mock(pool_url="https://pool.invalid", launcher_id=std_hash(b"launcher")),
            "current_difficulty": uint64(1),
            "authentication_token_timeout": uint8(10),
        }
    }
    authentication_sk = AugSchemeMPL.key_gen(b"5" * 32)
    mocker.patch.object(farmer, "get_authentication_sk", return_value=authentication_sk)
    mocker.patch.object(farmer, "_get_current_authentication_token", new=AsyncMock(return_value="token"))
    mocker.patch("chia.farmer.farmer_api.calculate_iterations_quality", side_effect=[uint64(100), uint64(1)])
    mocker.patch("chia.farmer.farmer_api.calculate_sp_interval_iters", return_value=uint64(10))

    async def sign_partial(
        api: object, request: harvester_protocol.RequestSignatures
    ) -> harvester_protocol.RespondSignatures:
        response = await harvester_api.request_signatures(request)
        assert response is not None
        return harvester_protocol.RespondSignatures.from_bytes(response.data)

    peer = Mock(peer_node_id=std_hash(b"harvester"), version="test", call_api=AsyncMock(side_effect=sign_partial))
    session = mocker.patch("chia.farmer.farmer_api.aiohttp.ClientSession").return_value.__aenter__.return_value
    session.post.return_value.__aenter__.return_value.ok = False
    await farmer_api.new_proof_of_space(new_proof, peer)

    session.post.assert_called_once()
    partial = PostPartialRequest.from_json_dict(session.post.call_args.kwargs["json"])
    message = partial.payload.get_hash()
    assert AugSchemeMPL.aggregate_verify(
        [new_proof.proof.plot_public_key, authentication_sk.get_g1()], [message, message], partial.aggregate_signature
    )
