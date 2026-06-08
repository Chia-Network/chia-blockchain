from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
from chia_rs import MerkleSet
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.full_node.full_node_api import MAX_COINS_MAP_SIZE, FullNodeAPI
from chia.protocols import wallet_protocol
from chia.protocols.outbound_message import Message
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.types.blockchain_format.coin import Coin
from chia.util.limited_semaphore import LimitedSemaphore


class _FakeBlockchain:
    def __init__(self, header_hash: bytes32) -> None:
        self._header_hash = header_hash

    def height_to_hash(self, _height: uint32) -> bytes32:
        return self._header_hash

    def get_peak_height(self) -> uint32:  # pragma: no cover
        return uint32(1)


class _FailIfCalledCoinStore:
    async def get_coins_added_at_height(self, _height: uint32) -> list[object]:  # pragma: no cover
        raise AssertionError("coin_store should not be called")

    async def get_coins_removed_at_height(self, _height: uint32) -> list[object]:  # pragma: no cover
        raise AssertionError("coin_store should not be called")


class _FailIfCalledBlockStore:
    async def get_full_block(self, _header_hash: bytes32) -> object:  # pragma: no cover
        raise AssertionError("block_store should not be called")


def _make_api(header_hash: bytes32) -> FullNodeAPI:
    full_node = SimpleNamespace(
        blockchain=_FakeBlockchain(header_hash),
        coin_store=_FailIfCalledCoinStore(),
        block_store=_FailIfCalledBlockStore(),
        config={},
        initialized=True,
        server=object(),
    )
    return FullNodeAPI(full_node)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_request_additions_empty_puzzle_hashes_short_circuits() -> None:
    header_hash = bytes32(b"\x01" * 32)
    api = _make_api(header_hash)
    request = wallet_protocol.RequestAdditions(uint32(1), header_hash, [])

    message = await api.request_additions(request)

    assert message is not None
    assert message.type == ProtocolMessageTypes.respond_additions.value
    response = wallet_protocol.RespondAdditions.from_bytes(message.data)
    assert response.header_hash == header_hash
    assert response.coins == []
    assert response.proofs == []


def _additions_request_and_handler(
    header_hash: bytes32,
) -> tuple[Any, Callable[[FullNodeAPI, Any], Awaitable[Message | None]], int]:
    request = wallet_protocol.RequestAdditions(uint32(1), header_hash, [bytes32(b"\xaa" * 32)])
    return request, FullNodeAPI.request_additions, ProtocolMessageTypes.reject_additions_request.value


def _removals_request_and_handler(
    header_hash: bytes32,
) -> tuple[Any, Callable[[FullNodeAPI, Any], Awaitable[Message | None]], int]:
    request = wallet_protocol.RequestRemovals(uint32(1), header_hash, [])
    return request, FullNodeAPI.request_removals, ProtocolMessageTypes.reject_removals_request.value


@pytest.mark.anyio
@pytest.mark.parametrize(
    "make_request_and_handler",
    [_additions_request_and_handler, _removals_request_and_handler],
    ids=["request_additions", "request_removals"],
)
async def test_wallet_sync_handler_rejects_when_throttle_is_full(
    make_request_and_handler: Callable[
        [bytes32], tuple[Any, Callable[[FullNodeAPI, Any], Awaitable[Message | None]], int]
    ],
) -> None:
    header_hash = bytes32(b"\x02" * 32)
    api = _make_api(header_hash)
    api.wallet_sync_api_sem = LimitedSemaphore.create(active_limit=1, waiting_limit=0)
    request, handler, expected_reject_type = make_request_and_handler(header_hash)

    async with api.wallet_sync_api_sem.acquire():
        message = await handler(api, request)

    assert message is not None
    assert message.type == expected_reject_type


# ---------------------------------------------------------------------------
# Shared helpers for deeper-path tests (inside the semaphore)
# ---------------------------------------------------------------------------


class _StableBlockchain:
    def __init__(self, header_hash: bytes32) -> None:
        self._header_hash = header_hash

    def height_to_hash(self, _height: uint32) -> bytes32:
        return self._header_hash

    def get_peak_height(self) -> uint32:
        return uint32(10)


class _ReorgBlockchain:
    """height_to_hash returns the expected hash for the first *reorg_after*
    calls, then a different hash for all subsequent calls."""

    def __init__(self, header_hash: bytes32, *, reorg_after: int) -> None:
        self._header_hash = header_hash
        self._reorg_after = reorg_after
        self._calls = 0

    def height_to_hash(self, _height: uint32) -> bytes32:
        self._calls += 1
        return self._header_hash if self._calls <= self._reorg_after else bytes32(b"\xff" * 32)

    def get_peak_height(self) -> uint32:
        return uint32(10)


def _make_full_node_ns(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {"config": {}, "initialized": True, "server": object()}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# request_additions — deeper paths
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_request_additions_rejects_on_reorg_after_db_query() -> None:
    """Covers L1363-1365: height_to_hash changes between the pre-semaphore
    check and the post-DB-query reorg guard."""
    header_hash = bytes32(b"\x03" * 32)

    class _EmptyCoinStore:
        async def get_coins_added_at_height(self, _height: uint32) -> list[object]:
            return []

    api = FullNodeAPI(
        _make_full_node_ns(  # type: ignore[arg-type]
            blockchain=_ReorgBlockchain(header_hash, reorg_after=1),
            coin_store=_EmptyCoinStore(),
        )
    )
    request = wallet_protocol.RequestAdditions(uint32(1), header_hash, [bytes32(b"\xaa" * 32)])

    message = await api.request_additions(request)

    assert message is not None
    assert message.type == ProtocolMessageTypes.reject_additions_request.value


@pytest.mark.anyio
async def test_request_additions_rejects_oversized_coins_map() -> None:
    """Covers L1379-1380: puzzle_hashes=None with >MAX_COINS_MAP_SIZE
    distinct puzzle hashes triggers rejection."""
    header_hash = bytes32(b"\x05" * 32)

    class _FakeCoinRecord:
        def __init__(self, ph: bytes32) -> None:
            self.coin = SimpleNamespace(puzzle_hash=ph)

    records: list[object] = [_FakeCoinRecord(bytes32(i.to_bytes(32, "big"))) for i in range(MAX_COINS_MAP_SIZE + 1)]

    class _BigCoinStore:
        async def get_coins_added_at_height(self, _height: uint32) -> list[object]:
            return records

    api = FullNodeAPI(
        _make_full_node_ns(  # type: ignore[arg-type]
            blockchain=_StableBlockchain(header_hash),
            coin_store=_BigCoinStore(),
        )
    )
    request = wallet_protocol.RequestAdditions(uint32(1), header_hash, None)

    message = await api.request_additions(request)

    assert message is not None
    assert message.type == ProtocolMessageTypes.reject_additions_request.value


# ---------------------------------------------------------------------------
# request_removals — deeper paths
# ---------------------------------------------------------------------------


def _make_block_ns(
    height: uint32,
    header_hash: bytes32,
    *,
    is_tx_block: bool = True,
    has_generator: bool = True,
    removals_root: bytes32 | None = None,
) -> SimpleNamespace:
    ftb = SimpleNamespace(removals_root=removals_root) if removals_root is not None else object()
    return SimpleNamespace(
        height=height,
        header_hash=header_hash,
        is_transaction_block=lambda: is_tx_block,
        foliage_transaction_block=ftb,
        transactions_generator=b"gen" if has_generator else None,
    )


@pytest.mark.anyio
async def test_request_removals_rejects_when_block_not_found() -> None:
    """Covers L1434-1436: block_store returns None."""
    header_hash = bytes32(b"\x06" * 32)

    class _NullBlockStore:
        async def get_full_block(self, _hash: bytes32) -> None:
            return None

    api = FullNodeAPI(
        _make_full_node_ns(  # type: ignore[arg-type]
            blockchain=_StableBlockchain(header_hash),
            block_store=_NullBlockStore(),
        )
    )
    request = wallet_protocol.RequestRemovals(uint32(1), header_hash, [])

    message = await api.request_removals(request)

    assert message is not None
    assert message.type == ProtocolMessageTypes.reject_removals_request.value


@pytest.mark.anyio
async def test_request_removals_rejects_on_reorg_after_db_query() -> None:
    """Covers L1447-1449: height_to_hash changes between block-validation
    and the post-DB-query reorg guard."""
    header_hash = bytes32(b"\x07" * 32)
    height = uint32(5)
    block = _make_block_ns(height, header_hash)

    class _BlockStore:
        async def get_full_block(self, _hash: bytes32) -> object:
            return block

    class _CoinStore:
        async def get_coins_removed_at_height(self, _height: uint32) -> list[object]:
            return []

    api = FullNodeAPI(
        _make_full_node_ns(  # type: ignore[arg-type]
            blockchain=_ReorgBlockchain(header_hash, reorg_after=1),
            block_store=_BlockStore(),
            coin_store=_CoinStore(),
        )
    )
    request = wallet_protocol.RequestRemovals(height, header_hash, [])

    message = await api.request_removals(request)

    assert message is not None
    assert message.type == ProtocolMessageTypes.reject_removals_request.value


@pytest.mark.anyio
async def test_request_removals_no_tx_generator_coin_names_none() -> None:
    """Covers L1462: block.transactions_generator is None with
    coin_names=None yields proofs=None."""
    header_hash = bytes32(b"\x09" * 32)
    height = uint32(5)
    block = _make_block_ns(height, header_hash, has_generator=False)

    class _BlockStore:
        async def get_full_block(self, _hash: bytes32) -> object:
            return block

    class _CoinStore:
        async def get_coins_removed_at_height(self, _height: uint32) -> list[object]:
            return []

    api = FullNodeAPI(
        _make_full_node_ns(  # type: ignore[arg-type]
            blockchain=_StableBlockchain(header_hash),
            block_store=_BlockStore(),
            coin_store=_CoinStore(),
        )
    )
    request = wallet_protocol.RequestRemovals(height, header_hash, None)

    message = await api.request_removals(request)

    assert message is not None
    assert message.type == ProtocolMessageTypes.respond_removals.value
    response = wallet_protocol.RespondRemovals.from_bytes(message.data)
    assert response.proofs is None


@pytest.mark.anyio
async def test_request_removals_all_removals_without_filter() -> None:
    """Covers L1467-1469: transactions_generator exists, coin_names=None
    returns all removals without Merkle proofs."""
    header_hash = bytes32(b"\x0a" * 32)
    height = uint32(5)
    coin = Coin(bytes32(b"\x01" * 32), bytes32(b"\x02" * 32), uint64(1000))
    block = _make_block_ns(height, header_hash)

    class _FakeCoinRecord:
        def __init__(self, c: Coin) -> None:
            self.coin = c

    class _BlockStore:
        async def get_full_block(self, _hash: bytes32) -> object:
            return block

    class _CoinStore:
        async def get_coins_removed_at_height(self, _height: uint32) -> list[object]:
            return [_FakeCoinRecord(coin)]

    api = FullNodeAPI(
        _make_full_node_ns(  # type: ignore[arg-type]
            blockchain=_StableBlockchain(header_hash),
            block_store=_BlockStore(),
            coin_store=_CoinStore(),
        )
    )
    request = wallet_protocol.RequestRemovals(height, header_hash, None)

    message = await api.request_removals(request)

    assert message is not None
    assert message.type == ProtocolMessageTypes.respond_removals.value
    response = wallet_protocol.RespondRemovals.from_bytes(message.data)
    assert len(response.coins) == 1
    assert response.proofs is None


@pytest.mark.anyio
async def test_request_removals_merkle_proof_with_unknown_coin() -> None:
    """Covers L1485-1486: requesting a coin_name not present in the removals
    dict yields (coin_name, None) with an exclusion proof."""
    header_hash = bytes32(b"\x0b" * 32)
    height = uint32(5)
    coin = Coin(bytes32(b"\x01" * 32), bytes32(b"\x02" * 32), uint64(1000))
    coin_name = coin.name()
    unknown_name = bytes32(b"\xee" * 32)

    removal_merkle_set = MerkleSet([coin_name])
    removals_root = removal_merkle_set.get_root()
    block = _make_block_ns(height, header_hash, removals_root=removals_root)

    class _FakeCoinRecord:
        def __init__(self, c: Coin) -> None:
            self.coin = c

    class _BlockStore:
        async def get_full_block(self, _hash: bytes32) -> object:
            return block

    class _CoinStore:
        async def get_coins_removed_at_height(self, _height: uint32) -> list[object]:
            return [_FakeCoinRecord(coin)]

    api = FullNodeAPI(
        _make_full_node_ns(  # type: ignore[arg-type]
            blockchain=_StableBlockchain(header_hash),
            block_store=_BlockStore(),
            coin_store=_CoinStore(),
        )
    )
    request = wallet_protocol.RequestRemovals(height, header_hash, [coin_name, unknown_name])

    message = await api.request_removals(request)

    assert message is not None
    assert message.type == ProtocolMessageTypes.respond_removals.value
    response = wallet_protocol.RespondRemovals.from_bytes(message.data)
    assert len(response.coins) == 2
    found = dict(response.coins)
    assert found[coin_name] == coin
    assert found[unknown_name] is None
