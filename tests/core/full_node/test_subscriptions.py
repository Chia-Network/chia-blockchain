from __future__ import annotations

import pytest

from chia.full_node.subscriptions import PeerSubscriptions
from chia.types.blockchain_format.sized_bytes import bytes32

peer1 = bytes32(b"1" * 32)
peer2 = bytes32(b"2" * 32)

coin1 = bytes32(b"a" * 32)
coin2 = bytes32(b"b" * 32)
coin3 = bytes32(b"c" * 32)
coin4 = bytes32(b"d" * 32)

ph1 = bytes32(b"e" * 32)
ph2 = bytes32(b"f" * 32)
ph3 = bytes32(b"g" * 32)
ph4 = bytes32(b"h" * 32)


@pytest.mark.anyio
async def test_has_ph_sub() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.is_puzzle_subscribed(ph2) is False

        ret = await sub.add_puzzle_subscriptions(peer1, [ph1], 100)
        assert ret == {ph1}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is False

        ret = await sub.add_puzzle_subscriptions(peer1, [ph1, ph2], 100)
        # we have already subscribed to ph1, it's filtered in the returned list
        assert ret == {ph2}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is True

        # note that this is technically a type error as well.
        # we can remove these asserts once we have type checking
        assert await sub.is_coin_subscribed(coin1) is False
        assert await sub.is_coin_subscribed(coin2) is False

        await sub.remove_peer(peer1)

        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.is_puzzle_subscribed(ph2) is False


@pytest.mark.anyio
async def test_has_coin_sub() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_coin_subscribed(coin1) is False
        assert await sub.is_coin_subscribed(coin2) is False

        await sub.add_coin_subscriptions(peer1, [coin1], 100)

        assert await sub.is_coin_subscribed(coin1) is True
        assert await sub.is_coin_subscribed(coin2) is False

        await sub.add_coin_subscriptions(peer1, [coin1, coin2], 100)

        assert await sub.is_coin_subscribed(coin1) is True
        assert await sub.is_coin_subscribed(coin2) is True

        # note that this is technically a type error as well.
        # we can remove these asserts once we have type checking
        assert await sub.is_puzzle_subscribed(coin1) is False
        assert await sub.is_puzzle_subscribed(coin2) is False

        await sub.remove_peer(peer1)

        assert await sub.is_coin_subscribed(coin1) is False
        assert await sub.is_coin_subscribed(coin2) is False


@pytest.mark.anyio
async def test_overlapping_coin_subscriptions() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_coin_subscribed(coin1) is False
        assert await sub.is_coin_subscribed(coin2) is False

        assert await sub.peers_for_coin_id(coin1) == set()
        assert await sub.peers_for_coin_id(coin2) == set()

        # subscribed to different coins
        await sub.add_coin_subscriptions(peer1, [coin1], 100)

        assert await sub.peers_for_coin_id(coin1) == {peer1}
        assert await sub.peers_for_coin_id(coin2) == set()

        await sub.add_coin_subscriptions(peer2, [coin2], 100)

        assert await sub.is_coin_subscribed(coin1) is True
        assert await sub.is_coin_subscribed(coin2) is True

        assert await sub.peers_for_coin_id(coin1) == {peer1}
        assert await sub.peers_for_coin_id(coin2) == {peer2}

        # peer1 is now subscribing to both coins
        await sub.add_coin_subscriptions(peer1, [coin2], 100)

        assert await sub.is_coin_subscribed(coin1) is True
        assert await sub.is_coin_subscribed(coin2) is True

        assert await sub.peers_for_coin_id(coin1) == {peer1}
        assert await sub.peers_for_coin_id(coin2) == {peer1, peer2}

        # removing peer1 still leaves the subscription to coin2
        await sub.remove_peer(peer1)

        assert await sub.is_coin_subscribed(coin1) is False
        assert await sub.is_coin_subscribed(coin2) is True

        assert await sub.peers_for_coin_id(coin1) == set()
        assert await sub.peers_for_coin_id(coin2) == {peer2}


@pytest.mark.anyio
async def test_overlapping_ph_subscriptions() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.is_puzzle_subscribed(ph2) is False

        assert await sub.peers_for_puzzle_hash(ph1) == set()
        assert await sub.peers_for_puzzle_hash(ph2) == set()

        # subscribed to different phs
        ret = await sub.add_puzzle_subscriptions(peer1, [ph1], 100)
        assert ret == {ph1}

        assert await sub.peers_for_puzzle_hash(ph1) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph2) == set()

        ret = await sub.add_puzzle_subscriptions(peer2, [ph2], 100)
        assert ret == {ph2}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is True

        assert await sub.peers_for_puzzle_hash(ph1) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph2) == {peer2}

        # peer1 is now subscribing to both phs
        ret = await sub.add_puzzle_subscriptions(peer1, [ph2], 100)
        assert ret == {ph2}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is True

        assert await sub.peers_for_puzzle_hash(ph1) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph2) == {peer1, peer2}

        # removing peer1 still leaves the subscription to ph2
        await sub.remove_peer(peer1)

        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.is_puzzle_subscribed(ph2) is True

        assert await sub.peers_for_puzzle_hash(ph1) == set()
        assert await sub.peers_for_puzzle_hash(ph2) == {peer2}


@pytest.mark.anyio
async def test_ph_sub_limit() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.is_puzzle_subscribed(ph2) is False
        assert await sub.is_puzzle_subscribed(ph2) is False
        assert await sub.is_puzzle_subscribed(ph3) is False

        ret = await sub.add_puzzle_subscriptions(peer1, [ph1, ph2, ph3, ph4], 3)
        # we only ended up subscribing to 3 puzzle hashes because of the limit
        assert ret == {ph1, ph2, ph3}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is True
        assert await sub.is_puzzle_subscribed(ph3) is True
        assert await sub.is_puzzle_subscribed(ph4) is False

        assert await sub.peers_for_puzzle_hash(ph1) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph2) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph3) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph4) == set()

        # peer1 should still be limited
        ret = await sub.add_puzzle_subscriptions(peer1, [ph4], 3)
        assert ret == set()

        assert await sub.is_puzzle_subscribed(ph4) is False
        assert await sub.peers_for_puzzle_hash(ph4) == set()

        # peer1 is also limied on coin subscriptions
        await sub.add_coin_subscriptions(peer1, [coin1], 3)

        assert await sub.is_coin_subscribed(coin1) is False
        assert await sub.peers_for_coin_id(coin1) == set()

        # peer2 is has its own limit
        ret = await sub.add_puzzle_subscriptions(peer2, [ph4], 3)
        assert ret == {ph4}

        assert await sub.is_puzzle_subscribed(ph4) is True
        assert await sub.peers_for_puzzle_hash(ph4) == {peer2}

        await sub.remove_peer(peer1)
        await sub.remove_peer(peer2)


@pytest.mark.anyio
async def test_ph_sub_limit_incremental() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.is_puzzle_subscribed(ph2) is False
        assert await sub.is_puzzle_subscribed(ph2) is False
        assert await sub.is_puzzle_subscribed(ph3) is False

        ret = await sub.add_puzzle_subscriptions(peer1, [ph1], 2)
        assert ret == {ph1}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is False
        assert await sub.is_puzzle_subscribed(ph3) is False
        assert await sub.is_puzzle_subscribed(ph4) is False

        assert await sub.peers_for_puzzle_hash(ph1) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph2) == set()
        assert await sub.peers_for_puzzle_hash(ph3) == set()
        assert await sub.peers_for_puzzle_hash(ph4) == set()

        # this will cross the limit. Only ph2 will be added
        ret = await sub.add_puzzle_subscriptions(peer1, [ph2, ph3], 2)
        assert ret == {ph2}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is True
        assert await sub.is_puzzle_subscribed(ph3) is False
        assert await sub.is_puzzle_subscribed(ph4) is False

        assert await sub.peers_for_puzzle_hash(ph1) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph2) == {peer1}
        assert await sub.peers_for_puzzle_hash(ph3) == set()
        assert await sub.peers_for_puzzle_hash(ph4) == set()

        await sub.remove_peer(peer1)


@pytest.mark.anyio
async def test_coin_sub_limit() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_coin_subscribed(coin1) is False
        assert await sub.is_coin_subscribed(coin2) is False
        assert await sub.is_coin_subscribed(coin2) is False
        assert await sub.is_coin_subscribed(coin3) is False

        await sub.add_coin_subscriptions(peer1, [coin1, coin2, coin3, coin4], 3)

        assert await sub.is_coin_subscribed(coin1) is True
        assert await sub.is_coin_subscribed(coin2) is True
        assert await sub.is_coin_subscribed(coin3) is True
        assert await sub.is_coin_subscribed(coin4) is False

        assert await sub.peers_for_coin_id(coin1) == {peer1}
        assert await sub.peers_for_coin_id(coin2) == {peer1}
        assert await sub.peers_for_coin_id(coin3) == {peer1}
        assert await sub.peers_for_coin_id(coin4) == set()

        # peer1 should still be limited
        await sub.add_coin_subscriptions(peer1, [coin4], 3)

        assert await sub.is_coin_subscribed(coin4) is False
        assert await sub.peers_for_coin_id(coin4) == set()

        # peer1 is also limied on ph subscriptions
        ret = await sub.add_puzzle_subscriptions(peer1, [ph1], 3)
        assert ret == set()

        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.peers_for_puzzle_hash(ph1) == set()

        # peer2 is has its own limit
        await sub.add_coin_subscriptions(peer2, [coin4], 3)

        assert await sub.is_coin_subscribed(coin4) is True
        assert await sub.peers_for_coin_id(coin4) == {peer2}

        await sub.remove_peer(peer1)
        await sub.remove_peer(peer2)


@pytest.mark.anyio
async def test_coin_sub_limit_incremental() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_coin_subscribed(coin1) is False
        assert await sub.is_coin_subscribed(coin2) is False
        assert await sub.is_coin_subscribed(coin2) is False
        assert await sub.is_coin_subscribed(coin3) is False

        await sub.add_coin_subscriptions(peer1, [coin1], 2)

        assert await sub.is_coin_subscribed(coin1) is True
        assert await sub.is_coin_subscribed(coin2) is False
        assert await sub.is_coin_subscribed(coin3) is False
        assert await sub.is_coin_subscribed(coin4) is False

        assert await sub.peers_for_coin_id(coin1) == {peer1}
        assert await sub.peers_for_coin_id(coin2) == set()
        assert await sub.peers_for_coin_id(coin3) == set()
        assert await sub.peers_for_coin_id(coin4) == set()

        # this will cross the limit. Only coin2 will be added
        await sub.add_coin_subscriptions(peer1, [coin2, coin3], 2)

        assert await sub.is_coin_subscribed(coin1) is True
        assert await sub.is_coin_subscribed(coin2) is True
        assert await sub.is_coin_subscribed(coin3) is False
        assert await sub.is_coin_subscribed(coin4) is False

        assert await sub.peers_for_coin_id(coin1) == {peer1}
        assert await sub.peers_for_coin_id(coin2) == {peer1}
        assert await sub.peers_for_coin_id(coin3) == set()
        assert await sub.peers_for_coin_id(coin4) == set()

        await sub.remove_peer(peer1)


@pytest.mark.anyio
async def test_ph_subscription_duplicates() -> None:
    async with PeerSubscriptions.managed() as sub:
        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.is_puzzle_subscribed(ph2) is False
        assert await sub.is_puzzle_subscribed(ph3) is False
        assert await sub.is_puzzle_subscribed(ph4) is False

        ret = await sub.add_puzzle_subscriptions(peer1, [ph1, ph2, ph3], 100)
        assert ret == {ph1, ph2, ph3}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is True
        assert await sub.is_puzzle_subscribed(ph3) is True
        assert await sub.is_puzzle_subscribed(ph4) is False

        # only ph4 is new, the others are duplicates and ignored
        ret = await sub.add_puzzle_subscriptions(peer1, [ph1, ph2, ph3, ph4], 100)
        assert ret == {ph4}

        assert await sub.is_puzzle_subscribed(ph1) is True
        assert await sub.is_puzzle_subscribed(ph2) is True
        assert await sub.is_puzzle_subscribed(ph3) is True
        assert await sub.is_puzzle_subscribed(ph4) is True

        await sub.remove_peer(peer1)

        assert await sub.is_puzzle_subscribed(ph1) is False
        assert await sub.is_puzzle_subscribed(ph2) is False
        assert await sub.is_puzzle_subscribed(ph3) is False
        assert await sub.is_puzzle_subscribed(ph4) is False
