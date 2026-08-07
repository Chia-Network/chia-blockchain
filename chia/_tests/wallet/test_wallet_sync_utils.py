from __future__ import annotations

import pytest
from chia_rs import RespondToPhUpdates
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import int16, uint32

from chia.protocols.shared_protocol import Error
from chia.protocols.wallet_protocol import RespondToCoinUpdates
from chia.wallet.util.wallet_sync_utils import _coin_states_from_subscribe_response


@pytest.mark.parametrize(
    "response, match",
    [
        (None, "None response from peer peer.example for register_for_ph_updates"),
        (
            Error(int16(1), "rejected", None),
            "Error response from peer peer.example for register_for_ph_updates",
        ),
        (object(), "Unexpected response from peer peer.example for register_for_ph_updates: object"),
    ],
    ids=["none", "protocol_error", "unexpected_type"],
)
def test_coin_states_from_subscribe_response_rejects_invalid(response: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _coin_states_from_subscribe_response(response, "peer.example", "register_for_ph_updates")


@pytest.mark.parametrize(
    "response",
    [
        RespondToPhUpdates([bytes32.zeros], uint32(0), []),
        RespondToCoinUpdates([bytes32.zeros], uint32(0), []),
    ],
    ids=["ph_updates", "coin_updates"],
)
def test_coin_states_from_subscribe_response_returns_coin_states(
    response: RespondToPhUpdates | RespondToCoinUpdates,
) -> None:
    assert _coin_states_from_subscribe_response(response, "peer.example", "register_for_ph_updates") == []
