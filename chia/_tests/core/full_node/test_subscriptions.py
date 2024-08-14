from __future__ import annotations

from chia_rs import AugSchemeMPL, Coin, CoinSpend, Program
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.full_node.subscriptions import PeerSubscriptions, peers_for_spend_bundle
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle

IDENTITY_PUZZLE = Program.to(1)
IDENTITY_PUZZLE_HASH = IDENTITY_PUZZLE.get_tree_hash()

OTHER_PUZZLE = Program.to(2)
OTHER_PUZZLE_HASH = OTHER_PUZZLE.get_tree_hash()

HINT_PUZZLE = Program.to(3)
HINT_PUZZLE_HASH = HINT_PUZZLE.get_tree_hash()

IDENTITY_COIN = Coin(bytes32(b"0" * 32), IDENTITY_PUZZLE_HASH, uint64(1000))
OTHER_COIN = Coin(bytes32(b"3" * 32), OTHER_PUZZLE_HASH, uint64(1000))

EMPTY_SIGNATURE = AugSchemeMPL.aggregate([])

peer1 = bytes32(b"1" * 32)
peer2 = bytes32(b"2" * 32)
peer3 = bytes32(b"3" * 32)
peer4 = bytes32(b"4" * 32)

coin1 = bytes32(b"a" * 32)
coin2 = bytes32(b"b" * 32)
coin3 = bytes32(b"c" * 32)
coin4 = bytes32(b"d" * 32)

ph1 = bytes32(b"e" * 32)
ph2 = bytes32(b"f" * 32)
ph3 = bytes32(b"g" * 32)
ph4 = bytes32(b"h" * 32)


def test_has_ph_sub() -> None:
    sub = PeerSubscriptions()

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.has_puzzle_subscription(ph2) is False

    ret = sub.add_puzzle_subscriptions(peer1, [ph1], 100)
    assert ret == {ph1}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is False

    ret = sub.add_puzzle_subscriptions(peer1, [ph1, ph2], 100)
    # we have already subscribed to ph1, it's filtered in the returned list
    assert ret == {ph2}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is True

    # note that this is technically a type error as well.
    # we can remove these asserts once we have type checking
    assert sub.has_coin_subscription(coin1) is False
    assert sub.has_coin_subscription(coin2) is False

    sub.remove_peer(peer1)

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.has_puzzle_subscription(ph2) is False


def test_has_coin_sub() -> None:
    sub = PeerSubscriptions()

    assert sub.has_coin_subscription(coin1) is False
    assert sub.has_coin_subscription(coin2) is False

    sub.add_coin_subscriptions(peer1, [coin1], 100)

    assert sub.has_coin_subscription(coin1) is True
    assert sub.has_coin_subscription(coin2) is False

    sub.add_coin_subscriptions(peer1, [coin1, coin2], 100)

    assert sub.has_coin_subscription(coin1) is True
    assert sub.has_coin_subscription(coin2) is True

    # note that this is technically a type error as well.
    # we can remove these asserts once we have type checking
    assert sub.has_puzzle_subscription(coin1) is False
    assert sub.has_puzzle_subscription(coin2) is False

    sub.remove_peer(peer1)

    assert sub.has_coin_subscription(coin1) is False
    assert sub.has_coin_subscription(coin2) is False


def test_overlapping_coin_subscriptions() -> None:
    sub = PeerSubscriptions()

    assert sub.has_coin_subscription(coin1) is False
    assert sub.has_coin_subscription(coin2) is False

    assert sub.peers_for_coin_id(coin1) == set()
    assert sub.peers_for_coin_id(coin2) == set()

    # subscribed to different coins
    sub.add_coin_subscriptions(peer1, [coin1], 100)

    assert sub.peers_for_coin_id(coin1) == {peer1}
    assert sub.peers_for_coin_id(coin2) == set()

    sub.add_coin_subscriptions(peer2, [coin2], 100)

    assert sub.has_coin_subscription(coin1) is True
    assert sub.has_coin_subscription(coin2) is True

    assert sub.peers_for_coin_id(coin1) == {peer1}
    assert sub.peers_for_coin_id(coin2) == {peer2}

    # peer1 is now subscribing to both coins
    sub.add_coin_subscriptions(peer1, [coin2], 100)

    assert sub.has_coin_subscription(coin1) is True
    assert sub.has_coin_subscription(coin2) is True

    assert sub.peers_for_coin_id(coin1) == {peer1}
    assert sub.peers_for_coin_id(coin2) == {peer1, peer2}

    # removing peer1 still leaves the subscription to coin2
    sub.remove_peer(peer1)

    assert sub.has_coin_subscription(coin1) is False
    assert sub.has_coin_subscription(coin2) is True

    assert sub.peers_for_coin_id(coin1) == set()
    assert sub.peers_for_coin_id(coin2) == {peer2}


def test_overlapping_ph_subscriptions() -> None:
    sub = PeerSubscriptions()

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.has_puzzle_subscription(ph2) is False

    assert sub.peers_for_puzzle_hash(ph1) == set()
    assert sub.peers_for_puzzle_hash(ph2) == set()

    # subscribed to different phs
    ret = sub.add_puzzle_subscriptions(peer1, [ph1], 100)
    assert ret == {ph1}

    assert sub.peers_for_puzzle_hash(ph1) == {peer1}
    assert sub.peers_for_puzzle_hash(ph2) == set()

    ret = sub.add_puzzle_subscriptions(peer2, [ph2], 100)
    assert ret == {ph2}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is True

    assert sub.peers_for_puzzle_hash(ph1) == {peer1}
    assert sub.peers_for_puzzle_hash(ph2) == {peer2}

    # peer1 is now subscribing to both phs
    ret = sub.add_puzzle_subscriptions(peer1, [ph2], 100)
    assert ret == {ph2}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is True

    assert sub.peers_for_puzzle_hash(ph1) == {peer1}
    assert sub.peers_for_puzzle_hash(ph2) == {peer1, peer2}

    # removing peer1 still leaves the subscription to ph2
    sub.remove_peer(peer1)

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.has_puzzle_subscription(ph2) is True

    assert sub.peers_for_puzzle_hash(ph1) == set()
    assert sub.peers_for_puzzle_hash(ph2) == {peer2}


def test_ph_sub_limit() -> None:
    sub = PeerSubscriptions()

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.has_puzzle_subscription(ph2) is False
    assert sub.has_puzzle_subscription(ph2) is False
    assert sub.has_puzzle_subscription(ph3) is False

    ret = sub.add_puzzle_subscriptions(peer1, [ph1, ph2, ph3, ph4], 3)
    # we only ended up subscribing to 3 puzzle hashes because of the limit
    assert ret == {ph1, ph2, ph3}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is True
    assert sub.has_puzzle_subscription(ph3) is True
    assert sub.has_puzzle_subscription(ph4) is False

    assert sub.peers_for_puzzle_hash(ph1) == {peer1}
    assert sub.peers_for_puzzle_hash(ph2) == {peer1}
    assert sub.peers_for_puzzle_hash(ph3) == {peer1}
    assert sub.peers_for_puzzle_hash(ph4) == set()

    # peer1 should still be limited
    ret = sub.add_puzzle_subscriptions(peer1, [ph4], 3)
    assert ret == set()

    assert sub.has_puzzle_subscription(ph4) is False
    assert sub.peers_for_puzzle_hash(ph4) == set()

    # peer1 is also limied on coin subscriptions
    sub.add_coin_subscriptions(peer1, [coin1], 3)

    assert sub.has_coin_subscription(coin1) is False
    assert sub.peers_for_coin_id(coin1) == set()

    # peer2 is has its own limit
    ret = sub.add_puzzle_subscriptions(peer2, [ph4], 3)
    assert ret == {ph4}

    assert sub.has_puzzle_subscription(ph4) is True
    assert sub.peers_for_puzzle_hash(ph4) == {peer2}

    sub.remove_peer(peer1)
    sub.remove_peer(peer2)


def test_ph_sub_limit_incremental() -> None:
    sub = PeerSubscriptions()

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.has_puzzle_subscription(ph2) is False
    assert sub.has_puzzle_subscription(ph2) is False
    assert sub.has_puzzle_subscription(ph3) is False

    ret = sub.add_puzzle_subscriptions(peer1, [ph1], 2)
    assert ret == {ph1}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is False
    assert sub.has_puzzle_subscription(ph3) is False
    assert sub.has_puzzle_subscription(ph4) is False

    assert sub.peers_for_puzzle_hash(ph1) == {peer1}
    assert sub.peers_for_puzzle_hash(ph2) == set()
    assert sub.peers_for_puzzle_hash(ph3) == set()
    assert sub.peers_for_puzzle_hash(ph4) == set()

    # this will cross the limit. Only ph2 will be added
    ret = sub.add_puzzle_subscriptions(peer1, [ph2, ph3], 2)
    assert ret == {ph2}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is True
    assert sub.has_puzzle_subscription(ph3) is False
    assert sub.has_puzzle_subscription(ph4) is False

    assert sub.peers_for_puzzle_hash(ph1) == {peer1}
    assert sub.peers_for_puzzle_hash(ph2) == {peer1}
    assert sub.peers_for_puzzle_hash(ph3) == set()
    assert sub.peers_for_puzzle_hash(ph4) == set()

    sub.remove_peer(peer1)


def test_coin_sub_limit() -> None:
    sub = PeerSubscriptions()

    assert sub.has_coin_subscription(coin1) is False
    assert sub.has_coin_subscription(coin2) is False
    assert sub.has_coin_subscription(coin2) is False
    assert sub.has_coin_subscription(coin3) is False

    sub.add_coin_subscriptions(peer1, [coin1, coin2, coin3, coin4], 3)

    assert sub.has_coin_subscription(coin1) is True
    assert sub.has_coin_subscription(coin2) is True
    assert sub.has_coin_subscription(coin3) is True
    assert sub.has_coin_subscription(coin4) is False

    assert sub.peers_for_coin_id(coin1) == {peer1}
    assert sub.peers_for_coin_id(coin2) == {peer1}
    assert sub.peers_for_coin_id(coin3) == {peer1}
    assert sub.peers_for_coin_id(coin4) == set()

    # peer1 should still be limited
    sub.add_coin_subscriptions(peer1, [coin4], 3)

    assert sub.has_coin_subscription(coin4) is False
    assert sub.peers_for_coin_id(coin4) == set()

    # peer1 is also limied on ph subscriptions
    ret = sub.add_puzzle_subscriptions(peer1, [ph1], 3)
    assert ret == set()

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.peers_for_puzzle_hash(ph1) == set()

    # peer2 is has its own limit
    sub.add_coin_subscriptions(peer2, [coin4], 3)

    assert sub.has_coin_subscription(coin4) is True
    assert sub.peers_for_coin_id(coin4) == {peer2}

    sub.remove_peer(peer1)
    sub.remove_peer(peer2)


def test_coin_sub_limit_incremental() -> None:
    sub = PeerSubscriptions()

    assert sub.has_coin_subscription(coin1) is False
    assert sub.has_coin_subscription(coin2) is False
    assert sub.has_coin_subscription(coin2) is False
    assert sub.has_coin_subscription(coin3) is False

    sub.add_coin_subscriptions(peer1, [coin1], 2)

    assert sub.has_coin_subscription(coin1) is True
    assert sub.has_coin_subscription(coin2) is False
    assert sub.has_coin_subscription(coin3) is False
    assert sub.has_coin_subscription(coin4) is False

    assert sub.peers_for_coin_id(coin1) == {peer1}
    assert sub.peers_for_coin_id(coin2) == set()
    assert sub.peers_for_coin_id(coin3) == set()
    assert sub.peers_for_coin_id(coin4) == set()

    # this will cross the limit. Only coin2 will be added
    sub.add_coin_subscriptions(peer1, [coin2, coin3], 2)

    assert sub.has_coin_subscription(coin1) is True
    assert sub.has_coin_subscription(coin2) is True
    assert sub.has_coin_subscription(coin3) is False
    assert sub.has_coin_subscription(coin4) is False

    assert sub.peers_for_coin_id(coin1) == {peer1}
    assert sub.peers_for_coin_id(coin2) == {peer1}
    assert sub.peers_for_coin_id(coin3) == set()
    assert sub.peers_for_coin_id(coin4) == set()

    sub.remove_peer(peer1)


def test_ph_subscription_duplicates() -> None:
    sub = PeerSubscriptions()

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.has_puzzle_subscription(ph2) is False
    assert sub.has_puzzle_subscription(ph3) is False
    assert sub.has_puzzle_subscription(ph4) is False

    ret = sub.add_puzzle_subscriptions(peer1, [ph1, ph2, ph3], 100)
    assert ret == {ph1, ph2, ph3}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is True
    assert sub.has_puzzle_subscription(ph3) is True
    assert sub.has_puzzle_subscription(ph4) is False

    # only ph4 is new, the others are duplicates and ignored
    ret = sub.add_puzzle_subscriptions(peer1, [ph1, ph2, ph3, ph4], 100)
    assert ret == {ph4}

    assert sub.has_puzzle_subscription(ph1) is True
    assert sub.has_puzzle_subscription(ph2) is True
    assert sub.has_puzzle_subscription(ph3) is True
    assert sub.has_puzzle_subscription(ph4) is True

    sub.remove_peer(peer1)

    assert sub.has_puzzle_subscription(ph1) is False
    assert sub.has_puzzle_subscription(ph2) is False
    assert sub.has_puzzle_subscription(ph3) is False
    assert sub.has_puzzle_subscription(ph4) is False


def test_remove_ph_subscriptions() -> None:
    sub = PeerSubscriptions()

    added = sub.add_puzzle_subscriptions(peer1, [ph1, ph2, ph3, ph4, ph4], 100)
    assert added == {ph1, ph2, ph3, ph4}

    removed = sub.remove_puzzle_subscriptions(peer1, list(added))
    assert removed == added

    # These have already been removed.
    assert len(sub.remove_puzzle_subscriptions(peer1, [ph1, ph2])) == 0

    assert sub.peer_subscription_count(peer1) == 0

    for ph in removed:
        assert not sub.has_puzzle_subscription(ph)


def test_remove_coin_subscriptions() -> None:
    sub = PeerSubscriptions()

    added = sub.add_coin_subscriptions(peer1, [coin1, coin2, coin3, coin4, coin4], 100)
    assert added == {coin1, coin2, coin3, coin4}

    removed = sub.remove_coin_subscriptions(peer1, list(added))
    assert removed == added

    # These have already been removed.
    assert len(sub.remove_coin_subscriptions(peer1, [coin1, coin2])) == 0

    assert sub.peer_subscription_count(peer1) == 0

    for coin_id in removed:
        assert not sub.has_coin_subscription(coin_id)


def test_subscription_list() -> None:
    sub = PeerSubscriptions()

    sub.add_coin_subscriptions(peer1, [coin1, coin2], 4)
    sub.add_puzzle_subscriptions(peer1, [ph1, ph2], 4)

    assert sub.coin_subscriptions(peer1) == {coin1, coin2}
    assert sub.puzzle_subscriptions(peer1) == {ph1, ph2}


def test_clear_subscriptions() -> None:
    subs = PeerSubscriptions()

    subs.add_puzzle_subscriptions(peer1, [ph1, ph2], 4)
    subs.add_coin_subscriptions(peer1, [coin1, coin2], 4)

    subs.clear_puzzle_subscriptions(peer1)
    assert subs.coin_subscriptions(peer1) == {coin1, coin2}
    assert subs.puzzle_subscription_count() == 0

    subs.add_puzzle_subscriptions(peer1, [ph1, ph2], 4)
    subs.clear_coin_subscriptions(peer1)
    assert subs.puzzle_subscriptions(peer1) == {ph1, ph2}
    assert subs.coin_subscription_count() == 0

    subs.clear_puzzle_subscriptions(peer1)
    assert subs.peer_subscription_count(peer1) == 0


def test_peers_for_spent_coin() -> None:
    subs = PeerSubscriptions()

    subs.add_puzzle_subscriptions(peer1, [IDENTITY_PUZZLE_HASH], 1)
    subs.add_puzzle_subscriptions(peer2, [HINT_PUZZLE_HASH], 1)
    subs.add_coin_subscriptions(peer3, [IDENTITY_COIN.name()], 1)
    subs.add_coin_subscriptions(peer4, [OTHER_COIN.name()], 1)

    coin_spends = [CoinSpend(IDENTITY_COIN, IDENTITY_PUZZLE, Program.to([]))]

    spend_bundle = SpendBundle(coin_spends, AugSchemeMPL.aggregate([]))
    generator = simple_solution_generator(spend_bundle)
    npc_result = get_name_puzzle_conditions(
        generator=generator, max_cost=INFINITE_COST, mempool_mode=True, height=uint32(0), constants=DEFAULT_CONSTANTS
    )
    assert npc_result.conds is not None

    peers = peers_for_spend_bundle(subs, npc_result.conds, {HINT_PUZZLE_HASH})
    assert peers == {peer1, peer2, peer3}


def test_peers_for_created_coin() -> None:
    subs = PeerSubscriptions()

    new_coin = Coin(IDENTITY_COIN.name(), OTHER_PUZZLE_HASH, uint64(1000))

    subs.add_puzzle_subscriptions(peer1, [OTHER_PUZZLE_HASH], 1)
    subs.add_puzzle_subscriptions(peer2, [HINT_PUZZLE_HASH], 1)
    subs.add_coin_subscriptions(peer3, [new_coin.name()], 1)
    subs.add_coin_subscriptions(peer4, [OTHER_COIN.name()], 1)

    coin_spends = [
        CoinSpend(IDENTITY_COIN, IDENTITY_PUZZLE, Program.to([[51, OTHER_PUZZLE_HASH, 1000, [HINT_PUZZLE_HASH]]]))
    ]

    spend_bundle = SpendBundle(coin_spends, AugSchemeMPL.aggregate([]))
    generator = simple_solution_generator(spend_bundle)
    npc_result = get_name_puzzle_conditions(
        generator=generator, max_cost=INFINITE_COST, mempool_mode=True, height=uint32(0), constants=DEFAULT_CONSTANTS
    )
    assert npc_result.conds is not None

    peers = peers_for_spend_bundle(subs, npc_result.conds, set())
    assert peers == {peer1, peer2, peer3}
