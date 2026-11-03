"""
Regression test for the 2.6.1 wallet fix that stopped ``take_offer`` from auto-signing
spends the taker did not authorize.

Background (Chia 2.6.1 security release, "Wallet -- offer acceptance and signing"):
before the fix, the wallet RPC layer signed every coin spend in the merged maker+taker
transaction.  A malicious maker could therefore add an *unsigned* spend of a taker-owned
coin to their offer, paying it to an attacker puzzle hash, and the taker's wallet would
happily provide the missing signature while the user thought they were accepting a
normal offer.

The fix is a caller-side switch in the wallet RPC layer (``sign=False`` for
``take_offer``), not an ownership check in the signer, so this test drives the real RPC
endpoint (``WalletRpcClient.take_offer``) rather than calling
``TradeManager.respond_to_offer`` directly.  It asserts the invariant behaviourally:

* the taker's signature does NOT cover the maker-injected spend of the taker's coin,
* everything else in the merged bundle is still properly signed, and
* the full node rejects the merged bundle, so the injected payment can never land.

A second test takes a clean offer through the same path and asserts it still confirms,
which proves the harness is not trivially passing because ``take_offer`` fails for
everyone.
"""

from __future__ import annotations

import pytest
from chia_rs import AugSchemeMPL, CoinSpend, ConsensusConstants, G1Element, G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.environments.wallet import WalletEnvironment, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.types.blockchain_format.coin import Coin
from chia.util.errors import Err
from chia.wallet.trading.offer import Offer
from chia.wallet.wallet_request_types import GetWalletBalance, TakeOffer
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

# A puzzle hash that belongs to nobody in the test.  The malicious spend pays the
# taker's coin here; the test asserts that no coin ever shows up at this address.
ATTACKER_PUZZLE_HASH = bytes32(b"\x42" * 32)
OFFER_AMOUNT = uint64(1_000)


async def _make_signed_offer(wallet_environments: WalletTestFramework, amount: uint64 = OFFER_AMOUNT) -> Offer:
    """Create a normal maker offer (XCH for nothing) and sign it."""
    maker = wallet_environments.environments[0]
    async with maker.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=False) as action_scope:
        _success, trade_record, error = await maker.wallet_state_manager.trade_manager.create_offer_for_ids(
            {1: -int(amount)}, action_scope
        )
    assert error is None
    assert trade_record is not None
    [signed_offer], _signing_responses = await maker.wallet_state_manager.signer.sign_offers(
        [Offer.from_bytes(trade_record.offer)]
    )
    return signed_offer


async def _make_unsigned_taker_spend(
    wallet_environments: WalletTestFramework,
    taker: WalletEnvironment,
    target_puzzle_hash: bytes32,
) -> tuple[Coin, CoinSpend]:
    """Build (but do not sign) a spend of a taker coin paying ``target_puzzle_hash``.

    This is the shape a malicious maker puts into their offer: a perfectly valid spend of
    a victim coin with an AGG_SIG condition over a solution the victim never approved,
    missing only the victim's signature.
    """
    async with taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False, sign=False
    ) as action_scope:
        coins = await taker.xch_wallet.select_coins(uint64(1), action_scope)
        coin = max(coins, key=lambda candidate: candidate.amount)
        await taker.xch_wallet.generate_signed_transaction(
            [coin.amount], [target_puzzle_hash], action_scope, fee=uint64(0), coins={coin}
        )
    [transaction] = action_scope.side_effects.transactions
    assert transaction.spend_bundle is not None
    assert transaction.spend_bundle.aggregated_signature == G2Element()
    [coin_spend] = transaction.spend_bundle.coin_spends
    assert coin_spend.coin == coin
    return coin, coin_spend


def _inject_spend(offer: Offer, spend: CoinSpend) -> Offer:
    """Return ``offer`` with an extra, unsigned coin spend appended to its bundle."""
    augmented_bundle = WalletSpendBundle.aggregate([offer._bundle, WalletSpendBundle([spend], G2Element())])
    return Offer(offer.requested_payments, augmented_bundle, offer.driver_dict)


def _agg_sig_pairs_by_coin(
    bundle: WalletSpendBundle, constants: ConsensusConstants
) -> dict[bytes32, list[tuple[G1Element, bytes]]]:
    pairs: dict[bytes32, list[tuple[G1Element, bytes]]] = {}
    for coin_spend in bundle.coin_spends:
        conditions = conditions_dict_for_solution(
            coin_spend.puzzle_reveal, coin_spend.solution, constants.MAX_BLOCK_COST_CLVM
        )
        pairs[coin_spend.coin.name()] = pkm_pairs_for_conditions_dict(
            conditions, coin_spend.coin, constants.AGG_SIG_ME_ADDITIONAL_DATA
        )
    return pairs


def _aggregate_verify(pairs: list[tuple[G1Element, bytes]], signature: G2Element) -> bool:
    # Duplicate (pk, message) pairs would be counted twice by the signer as well, but
    # deduplicating keeps this helper robust to bundles that repeat a condition.
    unique_pairs = {(bytes(pk), message): (pk, message) for pk, message in pairs}
    if len(unique_pairs) == 0:
        return False
    return AugSchemeMPL.aggregate_verify(
        [pk for pk, _ in unique_pairs.values()],
        [message for _, message in unique_pairs.values()],
        signature,
    )


async def _confirmed_balance(environment: WalletEnvironment) -> int:
    response = await environment.rpc_client.get_wallet_balance(GetWalletBalance(wallet_id=uint32(1)))
    return int(response.wallet_balance.confirmed_wallet_balance)


async def _balance_is(environment: WalletEnvironment, expected: int) -> bool:
    return await _confirmed_balance(environment) == expected


async def _transaction_got_expected_error(environment: WalletEnvironment, transaction_id: bytes32, error: Err) -> bool:
    transaction = await environment.wallet_state_manager.tx_store.get_transaction_record(transaction_id)
    return transaction is not None and any(peer_error == error.name for _, _, peer_error in transaction.sent_to)


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1], "trusted": True, "reuse_puzhash": False}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_take_offer_does_not_sign_maker_injected_spend(wallet_environments: WalletTestFramework) -> None:
    _maker, taker = wallet_environments.environments

    maker_offer = await _make_signed_offer(wallet_environments)
    taker_coin, injected_spend = await _make_unsigned_taker_spend(wallet_environments, taker, ATTACKER_PUZZLE_HASH)
    malicious_offer = _inject_spend(maker_offer, injected_spend)

    response = await taker.rpc_client.take_offer(
        TakeOffer(offer=malicious_offer.to_bech32(), fee=uint64(0), push=True),
        tx_config=wallet_environments.tx_config,
    )

    bundles = [
        transaction.spend_bundle for transaction in response.transactions if transaction.spend_bundle is not None
    ]
    assert len(bundles) == 1
    final_bundle = bundles[0]

    pairs_by_coin = _agg_sig_pairs_by_coin(final_bundle, taker.wallet_state_manager.constants)
    injected_coin_id = taker_coin.name()
    assert injected_coin_id in pairs_by_coin
    injected_pairs = pairs_by_coin[injected_coin_id]
    assert injected_pairs != [], "test setup error: the injected spend must carry an AGG_SIG condition"
    other_pairs = [
        pair for coin_id, coin_pairs in pairs_by_coin.items() if coin_id != injected_coin_id for pair in coin_pairs
    ]

    # The regression: the taker's wallet must never sign the maker-injected spend of a
    # taker coin.  If this signature verifies over the full bundle, take_offer supplied
    # the missing signature (the 2.6.0 behaviour).
    assert not _aggregate_verify([*other_pairs, *injected_pairs], final_bundle.aggregated_signature), (
        "take_offer signed a coin spend that the taker's wallet did not create (2.6.1 regression)"
    )
    # Sanity check: the rest of the merged bundle is correctly signed.  This makes the
    # failure above specific to the injected spend rather than a broken test setup.
    assert _aggregate_verify(other_pairs, final_bundle.aggregated_signature)

    # The wallet pushes the merged bundle just like a real taker would; the full node must
    # reject it because the injected spend is unsigned.
    final_transaction = next(
        transaction for transaction in response.transactions if transaction.spend_bundle is not None
    )
    await time_out_assert(
        15,
        _transaction_got_expected_error,
        True,
        taker,
        final_transaction.name,
        Err.BAD_AGGREGATE_SIGNATURE,
    )

    await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
    peak = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert peak is not None
    await wallet_environments.full_node.wait_for_wallet_synced(wallet_node=taker.node, timeout=20, peak_height=peak)

    taker_coin_record = await taker.wallet_state_manager.coin_store.get_coin_record(taker_coin.name())
    assert taker_coin_record is not None
    assert not taker_coin_record.spent
    attacker_coins = await wallet_environments.full_node.full_node.coin_store.get_coin_records_by_puzzle_hash(
        include_spent_coins=True, puzzle_hash=ATTACKER_PUZZLE_HASH
    )
    assert attacker_coins == []


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1], "trusted": True, "reuse_puzhash": False}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_take_offer_clean_offer_still_confirms(wallet_environments: WalletTestFramework) -> None:
    """Positive control: the same RPC flow with no injected spend still works."""
    _maker, taker = wallet_environments.environments

    offer = await _make_signed_offer(wallet_environments)
    balance_before = await _confirmed_balance(taker)

    response = await taker.rpc_client.take_offer(
        TakeOffer(offer=offer.to_bech32(), fee=uint64(0), push=True),
        tx_config=wallet_environments.tx_config,
    )

    bundles = [
        transaction.spend_bundle for transaction in response.transactions if transaction.spend_bundle is not None
    ]
    assert len(bundles) == 1
    clean_bundle = bundles[0]
    clean_pairs = [
        pair
        for coin_pairs in _agg_sig_pairs_by_coin(clean_bundle, taker.wallet_state_manager.constants).values()
        for pair in coin_pairs
    ]
    assert _aggregate_verify(clean_pairs, clean_bundle.aggregated_signature)

    await wallet_environments.full_node.wait_transaction_records_entered_mempool(
        response.transactions, wallet_node=taker.node
    )
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
    peak = wallet_environments.full_node.full_node.blockchain.get_peak_height()
    assert peak is not None
    await wallet_environments.full_node.wait_for_wallet_synced(wallet_node=taker.node, timeout=20, peak_height=peak)
    await time_out_assert(15, _balance_is, True, taker, balance_before + int(OFFER_AMOUNT))

    # The maker really paid the offer amount to the taker.
    assert await _confirmed_balance(taker) == balance_before + int(OFFER_AMOUNT)
