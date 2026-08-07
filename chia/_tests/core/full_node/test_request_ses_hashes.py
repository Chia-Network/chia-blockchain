from __future__ import annotations

from types import SimpleNamespace

import pytest
from chia_rs import SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32

from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes


def _reward_hash(height: int) -> bytes32:
    return bytes32(height.to_bytes(4, "big") * 8)


def _ses(height: int) -> SubEpochSummary:
    return SubEpochSummary(bytes32.zeros, _reward_hash(height), uint8(0), None, None, None)


class _SesBlockchain:
    def __init__(self, heights: list[int]) -> None:
        self._heights = [uint32(h) for h in heights]
        self._ses = {uint32(h): _ses(h) for h in heights}

    def get_ses_heights(self) -> list[uint32]:
        return list(self._heights)

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self._ses[height]


def _make_api(heights: list[int]) -> FullNodeAPI:
    full_node = SimpleNamespace(blockchain=_SesBlockchain(heights))
    return FullNodeAPI(full_node)  # type: ignore[arg-type]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "ses_heights, start, end, expected_height_pairs, expected_reward_heights",
    [
        # Too few SES entries → empty response.
        ([], 10, 20, [], []),
        ([100], 50, 150, [], []),
        # start before the first SES height.
        ([100, 200, 300, 400], 50, 150, [], []),
        # start after the last SES height.
        ([100, 200, 300, 400], 400, 500, [], []),
        ([100, 200, 300, 400], 500, 600, [], []),
        # Entire request inside one SES interval.
        ([100, 200, 300, 400], 100, 150, [[100, 200]], [100]),
        ([100, 200, 300, 400], 150, 199, [[100, 200]], [100]),
        # end on the next boundary is treated as spanning (strict upper bound).
        ([100, 200, 300, 400], 150, 200, [[100, 200], [200, 300]], [100, 200]),
        # Request spans two SES intervals.
        ([100, 200, 300, 400], 150, 250, [[100, 200], [200, 300]], [100, 200]),
        # start exactly on an SES boundary.
        ([100, 200, 300, 400], 200, 250, [[200, 300]], [200]),
        ([100, 200, 300, 400], 200, 350, [[200, 300], [300, 400]], [200, 300]),
        # Last interval: cannot append a following SES even if end is past it.
        ([100, 200, 300, 400], 350, 999, [[300, 400]], [300]),
    ],
    ids=[
        "empty_heights",
        "single_height",
        "before_first",
        "at_last_height",
        "after_last",
        "first_interval_at_start",
        "first_interval_interior",
        "end_on_next_boundary_spans",
        "spans_two",
        "on_boundary_same_interval",
        "on_boundary_spans",
        "last_interval_only",
    ],
)
async def test_request_ses_hashes_interval_lookup(
    ses_heights: list[int],
    start: int,
    end: int,
    expected_height_pairs: list[list[int]],
    expected_reward_heights: list[int],
) -> None:
    api = _make_api(ses_heights)
    request = wallet_protocol.RequestSESInfo(uint32(start), uint32(end))

    message = await api.request_ses_hashes(request)

    assert message.type == ProtocolMessageTypes.respond_ses_hashes.value
    response = wallet_protocol.RespondSESInfo.from_bytes(message.data)
    assert [[int(h) for h in pair] for pair in response.heights] == expected_height_pairs
    assert response.reward_chain_hash == [_reward_hash(h) for h in expected_reward_heights]
