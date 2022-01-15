# flake8: noqa

import logging
import os
import pytest
from tests.util.build_network_protocol_files import get_network_protocol_filename
from chinilla.protocols import (
    farmer_protocol,
    full_node_protocol,
    harvester_protocol,
    introducer_protocol,
    pool_protocol,
    timelord_protocol,
    wallet_protocol,
)
from tests.util.network_protocol_data import *

log = logging.getLogger(__name__)


def parse_blob(input_bytes):
    size_bytes = input_bytes[:4]
    input_bytes = input_bytes[4:]
    size = int.from_bytes(size_bytes, "big")
    message_bytes = input_bytes[:size]
    input_bytes = input_bytes[size:]
    return (message_bytes, input_bytes)


def parse_farmer_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.NewSignagePoint.from_bytes(message_bytes)
    assert message == new_signage_point
    assert message_bytes == bytes(new_signage_point)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.DeclareProofOfSpace.from_bytes(message_bytes)
    assert message == declare_proof_of_space
    assert message_bytes == bytes(declare_proof_of_space)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.RequestSignedValues.from_bytes(message_bytes)
    assert message == request_signed_values
    assert message_bytes == bytes(request_signed_values)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.FarmingInfo.from_bytes(message_bytes)
    assert message == farming_info
    assert message_bytes == bytes(farming_info)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.SignedValues.from_bytes(message_bytes)
    assert message == signed_values
    assert message_bytes == bytes(signed_values)

    return input_bytes


def parse_full_node_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewPeak.from_bytes(message_bytes)
    assert message == new_peak
    assert message_bytes == bytes(new_peak)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewTransaction.from_bytes(message_bytes)
    assert message == new_transaction
    assert message_bytes == bytes(new_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestTransaction.from_bytes(message_bytes)
    assert message == request_transaction
    assert message_bytes == bytes(request_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondTransaction.from_bytes(message_bytes)
    assert message == respond_transaction
    assert message_bytes == bytes(respond_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestProofOfWeight.from_bytes(message_bytes)
    assert message == request_proof_of_weight
    assert message_bytes == bytes(request_proof_of_weight)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondProofOfWeight.from_bytes(message_bytes)
    assert message == respond_proof_of_weight
    assert message_bytes == bytes(respond_proof_of_weight)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestBlock.from_bytes(message_bytes)
    assert message == request_block
    assert message_bytes == bytes(request_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RejectBlock.from_bytes(message_bytes)
    assert message == reject_block
    assert message_bytes == bytes(reject_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestBlocks.from_bytes(message_bytes)
    assert message == request_blocks
    assert message_bytes == bytes(request_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondBlocks.from_bytes(message_bytes)
    assert message == respond_blocks
    assert message_bytes == bytes(respond_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RejectBlocks.from_bytes(message_bytes)
    assert message == reject_blocks
    assert message_bytes == bytes(reject_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondBlock.from_bytes(message_bytes)
    assert message == respond_block
    assert message_bytes == bytes(respond_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewUnfinishedBlock.from_bytes(message_bytes)
    assert message == new_unfinished_block
    assert message_bytes == bytes(new_unfinished_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestUnfinishedBlock.from_bytes(message_bytes)
    assert message == request_unfinished_block
    assert message_bytes == bytes(request_unfinished_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondUnfinishedBlock.from_bytes(message_bytes)
    assert message == respond_unfinished_block
    assert message_bytes == bytes(respond_unfinished_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewSignagePointOrEndOfSubSlot.from_bytes(message_bytes)
    assert message == new_signage_point_or_end_of_subslot
    assert message_bytes == bytes(new_signage_point_or_end_of_subslot)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestSignagePointOrEndOfSubSlot.from_bytes(message_bytes)
    assert message == request_signage_point_or_end_of_subslot
    assert message_bytes == bytes(request_signage_point_or_end_of_subslot)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondSignagePoint.from_bytes(message_bytes)
    assert message == respond_signage_point
    assert message_bytes == bytes(respond_signage_point)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondEndOfSubSlot.from_bytes(message_bytes)
    assert message == respond_end_of_subslot
    assert message_bytes == bytes(respond_end_of_subslot)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestMempoolTransactions.from_bytes(message_bytes)
    assert message == request_mempool_transaction
    assert message_bytes == bytes(request_mempool_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewCompactVDF.from_bytes(message_bytes)
    assert message == new_compact_vdf
    assert message_bytes == bytes(new_compact_vdf)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestCompactVDF.from_bytes(message_bytes)
    assert message == request_compact_vdf
    assert message_bytes == bytes(request_compact_vdf)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondCompactVDF.from_bytes(message_bytes)
    assert message == respond_compact_vdf
    assert message_bytes == bytes(respond_compact_vdf)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestPeers.from_bytes(message_bytes)
    assert message == request_peers
    assert message_bytes == bytes(request_peers)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondPeers.from_bytes(message_bytes)
    assert message == respond_peers
    assert message_bytes == bytes(respond_peers)

    return input_bytes


def parse_wallet_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RequestPuzzleSolution.from_bytes(message_bytes)
    assert message == request_puzzle_solution
    assert message_bytes == bytes(request_puzzle_solution)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.PuzzleSolutionResponse.from_bytes(message_bytes)
    assert message == puzzle_solution_response
    assert message_bytes == bytes(puzzle_solution_response)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondPuzzleSolution.from_bytes(message_bytes)
    assert message == respond_puzzle_solution
    assert message_bytes == bytes(respond_puzzle_solution)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RejectPuzzleSolution.from_bytes(message_bytes)
    assert message == reject_puzzle_solution
    assert message_bytes == bytes(reject_puzzle_solution)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.SendTransaction.from_bytes(message_bytes)
    assert message == send_transaction
    assert message_bytes == bytes(send_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.TransactionAck.from_bytes(message_bytes)
    assert message == transaction_ack
    assert message_bytes == bytes(transaction_ack)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.NewPeakWallet.from_bytes(message_bytes)
    assert message == new_peak_wallet
    assert message_bytes == bytes(new_peak_wallet)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RequestBlockHeader.from_bytes(message_bytes)
    assert message == request_block_header
    assert message_bytes == bytes(request_block_header)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondBlockHeader.from_bytes(message_bytes)
    assert message == respond_header_block
    assert message_bytes == bytes(respond_header_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RejectHeaderRequest.from_bytes(message_bytes)
    assert message == reject_header_request
    assert message_bytes == bytes(reject_header_request)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RequestRemovals.from_bytes(message_bytes)
    assert message == request_removals
    assert message_bytes == bytes(request_removals)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondRemovals.from_bytes(message_bytes)
    assert message == respond_removals
    assert bytes(message) == bytes(respond_removals)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RejectRemovalsRequest.from_bytes(message_bytes)
    assert message == reject_removals_request
    assert bytes(message) == bytes(reject_removals_request)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RequestAdditions.from_bytes(message_bytes)
    assert message == request_additions
    assert bytes(message) == bytes(request_additions)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondAdditions.from_bytes(message_bytes)
    assert message == respond_additions
    assert bytes(message) == bytes(respond_additions)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RejectAdditionsRequest.from_bytes(message_bytes)
    assert message == reject_additions
    assert bytes(message) == bytes(reject_additions)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RequestHeaderBlocks.from_bytes(message_bytes)
    assert message == request_header_blocks
    assert bytes(message) == bytes(request_header_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RejectHeaderBlocks.from_bytes(message_bytes)
    assert message == reject_header_blocks
    assert bytes(message) == bytes(reject_header_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondHeaderBlocks.from_bytes(message_bytes)
    assert message == respond_header_blocks
    assert bytes(message) == bytes(respond_header_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.CoinState.from_bytes(message_bytes)
    assert message == coin_state
    assert bytes(message) == bytes(coin_state)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RegisterForPhUpdates.from_bytes(message_bytes)
    assert message == register_for_ph_updates
    assert bytes(message) == bytes(register_for_ph_updates)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondToPhUpdates.from_bytes(message_bytes)
    assert message == respond_to_ph_updates
    assert bytes(message) == bytes(respond_to_ph_updates)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RegisterForCoinUpdates.from_bytes(message_bytes)
    assert message == register_for_coin_updates
    assert bytes(message) == bytes(register_for_coin_updates)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondToCoinUpdates.from_bytes(message_bytes)
    assert message == respond_to_coin_updates
    assert bytes(message) == bytes(respond_to_coin_updates)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.CoinStateUpdate.from_bytes(message_bytes)
    assert message == coin_state_update
    assert bytes(message) == bytes(coin_state_update)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RequestChildren.from_bytes(message_bytes)
    assert message == request_children
    assert bytes(message) == bytes(request_children)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondChildren.from_bytes(message_bytes)
    assert message == respond_children
    assert bytes(message) == bytes(respond_children)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RequestSESInfo.from_bytes(message_bytes)
    assert message == request_ses_info
    assert bytes(message) == bytes(request_ses_info)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = wallet_protocol.RespondSESInfo.from_bytes(message_bytes)
    assert message == respond_ses_info
    assert bytes(message) == bytes(respond_ses_info)

    return input_bytes


def parse_harvester_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.PoolDifficulty.from_bytes(message_bytes)
    assert message == pool_difficulty
    assert bytes(message) == bytes(pool_difficulty)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.HarvesterHandshake.from_bytes(message_bytes)
    assert message == harvester_handhsake
    assert bytes(message) == bytes(harvester_handhsake)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.NewSignagePointHarvester.from_bytes(message_bytes)
    assert message == new_signage_point_harvester
    assert bytes(message) == bytes(new_signage_point_harvester)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.NewProofOfSpace.from_bytes(message_bytes)
    assert message == new_proof_of_space
    assert bytes(message) == bytes(new_proof_of_space)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.RequestSignatures.from_bytes(message_bytes)
    assert message == request_signatures
    assert bytes(message) == bytes(request_signatures)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.RespondSignatures.from_bytes(message_bytes)
    assert message == respond_signatures
    assert bytes(message) == bytes(respond_signatures)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.Plot.from_bytes(message_bytes)
    assert message == plot
    assert bytes(message) == bytes(plot)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.RequestPlots.from_bytes(message_bytes)
    assert message == request_plots
    assert bytes(message) == bytes(request_plots)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = harvester_protocol.RespondPlots.from_bytes(message_bytes)
    assert message == respond_plots
    assert bytes(message) == bytes(respond_plots)

    return input_bytes


def parse_introducer_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = introducer_protocol.RequestPeersIntroducer.from_bytes(message_bytes)
    assert message == request_peers_introducer
    assert bytes(message) == bytes(request_peers_introducer)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = introducer_protocol.RespondPeersIntroducer.from_bytes(message_bytes)
    assert message == respond_peers_introducer
    assert bytes(message) == bytes(respond_peers_introducer)

    return input_bytes


def parse_pool_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.AuthenticationPayload.from_bytes(message_bytes)
    assert message == authentication_payload
    assert bytes(message) == bytes(authentication_payload)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.GetPoolInfoResponse.from_bytes(message_bytes)
    assert message == get_pool_info_response
    assert bytes(message) == bytes(get_pool_info_response)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PostPartialPayload.from_bytes(message_bytes)
    assert message == post_partial_payload
    assert bytes(message) == bytes(post_partial_payload)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PostPartialRequest.from_bytes(message_bytes)
    assert message == post_partial_request
    assert bytes(message) == bytes(post_partial_request)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PostPartialResponse.from_bytes(message_bytes)
    assert message == post_partial_response
    assert bytes(message) == bytes(post_partial_response)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.GetFarmerResponse.from_bytes(message_bytes)
    assert message == get_farmer_response
    assert bytes(message) == bytes(get_farmer_response)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PostFarmerPayload.from_bytes(message_bytes)
    assert message == post_farmer_payload
    assert bytes(message) == bytes(post_farmer_payload)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PostFarmerRequest.from_bytes(message_bytes)
    assert message == post_farmer_request
    assert bytes(message) == bytes(post_farmer_request)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PostFarmerResponse.from_bytes(message_bytes)
    assert message == post_farmer_response
    assert bytes(message) == bytes(post_farmer_response)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PutFarmerPayload.from_bytes(message_bytes)
    assert message == put_farmer_payload
    assert bytes(message) == bytes(put_farmer_payload)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PutFarmerRequest.from_bytes(message_bytes)
    assert message == put_farmer_request
    assert bytes(message) == bytes(put_farmer_request)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.PutFarmerResponse.from_bytes(message_bytes)
    assert message == put_farmer_response
    assert bytes(message) == bytes(put_farmer_response)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = pool_protocol.ErrorResponse.from_bytes(message_bytes)
    assert message == error_response
    assert bytes(message) == bytes(error_response)

    return input_bytes


def parse_timelord_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = timelord_protocol.NewPeakTimelord.from_bytes(message_bytes)
    assert message == new_peak_timelord
    assert bytes(message) == bytes(new_peak_timelord)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = timelord_protocol.NewUnfinishedBlockTimelord.from_bytes(message_bytes)
    assert message == new_unfinished_block_timelord
    assert bytes(message) == bytes(new_unfinished_block_timelord)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = timelord_protocol.NewInfusionPointVDF.from_bytes(message_bytes)
    assert message == new_infusion_point_vdf
    assert bytes(message) == bytes(new_infusion_point_vdf)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = timelord_protocol.NewSignagePointVDF.from_bytes(message_bytes)
    assert message == new_signage_point_vdf
    assert bytes(message) == bytes(new_signage_point_vdf)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = timelord_protocol.NewEndOfSubSlotVDF.from_bytes(message_bytes)
    assert message == new_end_of_sub_slot_bundle
    assert bytes(message) == bytes(new_end_of_sub_slot_bundle)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = timelord_protocol.RequestCompactProofOfTime.from_bytes(message_bytes)
    assert message == request_compact_proof_of_time
    assert bytes(message) == bytes(request_compact_proof_of_time)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = timelord_protocol.RespondCompactProofOfTime.from_bytes(message_bytes)
    assert message == respond_compact_proof_of_time
    assert bytes(message) == bytes(respond_compact_proof_of_time)

    return input_bytes


class TestNetworkProtocolFiles:
    def test_network_protocol_files(self):
        filename = get_network_protocol_filename()
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            input_bytes = f.read()
        input_bytes = parse_farmer_protocol(input_bytes)
        input_bytes = parse_full_node_protocol(input_bytes)
        input_bytes = parse_wallet_protocol(input_bytes)
        input_bytes = parse_harvester_protocol(input_bytes)
        input_bytes = parse_introducer_protocol(input_bytes)
        input_bytes = parse_pool_protocol(input_bytes)
        input_bytes = parse_timelord_protocol(input_bytes)
        assert input_bytes == b""
