# flake8: noqa
from __future__ import annotations

from typing import Any, List, Set

from chia.protocols import (
    farmer_protocol,
    full_node_protocol,
    harvester_protocol,
    introducer_protocol,
    pool_protocol,
    shared_protocol,
    timelord_protocol,
    wallet_protocol,
)

# this test is to ensure the network protocol message regression test always
# stays up to date. It's a test for the test


def types_in_module(mod: Any) -> Set[str]:
    ret: List[str] = []
    mod_name = mod.__name__
    for sym in dir(mod):
        obj = getattr(mod, sym)
        if hasattr(obj, "__module__") and obj.__module__ == mod_name:
            ret.append(sym)

    if hasattr(mod, "__all__"):
        ret += getattr(mod, "__all__")
    return set(ret)


def test_missing_messages_state_machine() -> None:
    from chia.protocols.protocol_state_machine import NO_REPLY_EXPECTED, VALID_REPLY_MESSAGE_MAP

    # if these asserts fail, make sure to add the new network protocol messages
    # to the visitor in build_network_protocol_files.py and rerun it. Then
    # update this test
    assert (
        len(VALID_REPLY_MESSAGE_MAP) == 20
    ), "A message was added to the protocol state machine. Make sure to update the protocol message regression test to include the new message"
    assert (
        len(NO_REPLY_EXPECTED) == 7
    ), "A message was added to the protocol state machine. Make sure to update the protocol message regression test to include the new message"


def test_missing_messages() -> None:

    wallet_msgs = {
        "CoinState",
        "CoinStateUpdate",
        "NewPeakWallet",
        "PuzzleSolutionResponse",
        "RegisterForCoinUpdates",
        "RegisterForPhUpdates",
        "RejectAdditionsRequest",
        "RejectBlockHeaders",
        "RejectHeaderBlocks",
        "RejectHeaderRequest",
        "RejectPuzzleSolution",
        "RejectRemovalsRequest",
        "RequestAdditions",
        "RequestBlockHeader",
        "RequestBlockHeaders",
        "RequestChildren",
        "RequestFeeEstimates",
        "RequestHeaderBlocks",
        "RequestPuzzleSolution",
        "RequestRemovals",
        "RequestSESInfo",
        "RespondAdditions",
        "RespondBlockHeader",
        "RespondBlockHeaders",
        "RespondChildren",
        "RespondFeeEstimates",
        "RespondHeaderBlocks",
        "RespondPuzzleSolution",
        "RespondRemovals",
        "RespondSESInfo",
        "RespondToCoinUpdates",
        "RespondToPhUpdates",
        "SendTransaction",
        "TransactionAck",
    }

    farmer_msgs = {
        "DeclareProofOfSpace",
        "FarmingInfo",
        "NewSignagePoint",
        "RequestSignedValues",
        "SignedValues",
    }

    full_node_msgs = {
        "NewCompactVDF",
        "NewPeak",
        "NewSignagePointOrEndOfSubSlot",
        "NewTransaction",
        "NewUnfinishedBlock",
        "RejectBlock",
        "RejectBlocks",
        "RequestBlock",
        "RequestBlocks",
        "RequestCompactVDF",
        "RequestMempoolTransactions",
        "RequestPeers",
        "RequestProofOfWeight",
        "RequestSignagePointOrEndOfSubSlot",
        "RequestTransaction",
        "RequestUnfinishedBlock",
        "RespondBlock",
        "RespondBlocks",
        "RespondCompactVDF",
        "RespondEndOfSubSlot",
        "RespondPeers",
        "RespondProofOfWeight",
        "RespondSignagePoint",
        "RespondTransaction",
        "RespondUnfinishedBlock",
    }

    harvester_msgs = {
        "HarvesterHandshake",
        "NewProofOfSpace",
        "NewSignagePointHarvester",
        "Plot",
        "PlotSyncDone",
        "PlotSyncError",
        "PlotSyncIdentifier",
        "PlotSyncPathList",
        "PlotSyncPlotList",
        "PlotSyncResponse",
        "PlotSyncStart",
        "PoolDifficulty",
        "RequestPlots",
        "RequestSignatures",
        "RespondPlots",
        "RespondSignatures",
    }

    introducer_msgs = {"RequestPeersIntroducer", "RespondPeersIntroducer"}

    pool_msgs = {
        "AuthenticationPayload",
        "ErrorResponse",
        "GetFarmerResponse",
        "GetPoolInfoResponse",
        "PoolErrorCode",
        "PostFarmerPayload",
        "PostFarmerRequest",
        "PostFarmerResponse",
        "PostPartialPayload",
        "PostPartialRequest",
        "PostPartialResponse",
        "PutFarmerPayload",
        "PutFarmerRequest",
        "PutFarmerResponse",
        "get_current_authentication_token",
        "validate_authentication_token",
    }

    timelord_msgs = {
        "NewEndOfSubSlotVDF",
        "NewInfusionPointVDF",
        "NewPeakTimelord",
        "NewSignagePointVDF",
        "NewUnfinishedBlockTimelord",
        "RequestCompactProofOfTime",
        "RespondCompactProofOfTime",
    }

    shared_msgs = {"Handshake", "Capability"}

    # if these asserts fail, make sure to add the new network protocol messages
    # to the visitor in build_network_protocol_files.py and rerun it. Then
    # update this test
    assert (
        types_in_module(wallet_protocol) == wallet_msgs
    ), "message types were added or removed from wallet_protocol. Make sure to update the protocol message regression test to include the new message"

    assert (
        types_in_module(farmer_protocol) == farmer_msgs
    ), "message types were added or removed from farmer_protocol. Make sure to update the protocol message regression test to include the new message"

    assert (
        types_in_module(full_node_protocol) == full_node_msgs
    ), "message types were added or removed from full_node_protocol. Make sure to update the protocol message regression test to include the new message"

    assert (
        types_in_module(harvester_protocol) == harvester_msgs
    ), "message types were added or removed from harvester_protocol. Make sure to update the protocol message regression test to include the new message"

    assert (
        types_in_module(introducer_protocol) == introducer_msgs
    ), "message types were added or removed from introducer_protocol. Make sure to update the protocol message regression test to include the new message"

    assert (
        types_in_module(pool_protocol) == pool_msgs
    ), "message types were added or removed from pool_protocol. Make sure to update the protocol message regression test to include the new message"

    assert (
        types_in_module(timelord_protocol) == timelord_msgs
    ), "message types were added or removed from timelord_protocol. Make sure to update the protocol message regression test to include the new message"

    assert (
        types_in_module(shared_protocol) == shared_msgs
    ), "message types were added or removed from shared_protocol. Make sure to update the protocol message regression test to include the new message"
