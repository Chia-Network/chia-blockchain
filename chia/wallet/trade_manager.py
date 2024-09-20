from __future__ import annotations

import dataclasses
import logging
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Optional, Set, Tuple, Union

from typing_extensions import Literal

from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import estimate_fees
from chia.util.db_wrapper import DBWrapper2
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    Condition,
    ConditionValidTimes,
    CreateCoinAnnouncement,
    parse_conditions_non_consensus,
    parse_timelock_info,
)
from chia.wallet.db_wallet.db_wallet_puzzles import ACS_MU_PH
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import NotarizedPayment, Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.trading.trade_store import TradeStore
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.compute_hints import compute_spend_hints_and_additions
from chia.wallet.util.query_filter import HashFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.cr_cat_drivers import ProofsChecker, construct_pending_approval_state
from chia.wallet.vc_wallet.vc_wallet import VCWallet
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_protocol import WalletProtocol

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

OFFER_MOD = load_clvm_maybe_recompile("settlement_payments.clsp")


class TradeManager:
    """
    This class is a driver for creating and accepting settlement_payments.clsp style offers.

    By default, standard XCH is supported but to support other types of assets you must implement certain functions on
    the asset's wallet as well as create a driver for its puzzle(s).  Here is a guide to integrating a new types of
    assets with this trade manager:

    Puzzle Drivers:
      - See chia/wallet/outer_puzzles.py for a full description of how to build these
      - The `solve` method must be able to be solved by a Solver that looks like this:
            Solver(
                {
                    "coin": bytes
                    "parent_spend": bytes
                    "siblings": List[bytes]  # other coins of the same type being offered
                    "sibling_spends": List[bytes]  # The parent spends for the siblings
                    "sibling_puzzles": List[Program]  # The inner puzzles of the siblings (always OFFER_MOD)
                    "sibling_solutions": List[Program]  # The inner solution of the siblings
            }
            )

    Wallet:
      - Segments in this code that call general wallet methods are highlighted by comments: # ATTENTION: new wallets
      - To be able to be traded, a wallet must implement these methods on itself:
        - generate_signed_transaction(...) -> List[TransactionRecord]  (See cat_wallet.py for full API)
        - convert_puzzle_hash(puzzle_hash: bytes32) -> bytes32  # Converts a puzzlehash from outer to inner puzzle
        - get_puzzle_info(asset_id: bytes32) -> PuzzleInfo
        - get_coins_to_offer(asset_id: bytes32, amount: uint64) -> Set[Coin]
      - If you would like assets from your wallet to be referenced with just a wallet ID, you must also implement:
        - get_asset_id() -> bytes32
      - Finally, you must make sure that your wallet will respond appropriately when these WSM methods are called:
        - get_wallet_for_puzzle_info(puzzle_info: PuzzleInfo) -> <Your wallet>
        - create_wallet_for_puzzle_info(..., puzzle_info: PuzzleInfo) -> <Your wallet>  (See cat_wallet.py for full API)
        - get_wallet_for_asset_id(asset_id: bytes32) -> <Your wallet>
    """

    wallet_state_manager: WalletStateManager
    log: logging.Logger
    trade_store: TradeStore
    most_recently_deserialized_trade: Optional[Tuple[bytes32, Offer]]

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        db_wrapper: DBWrapper2,
        name: Optional[str] = None,
    ) -> TradeManager:
        self = TradeManager()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.trade_store = await TradeStore.create(db_wrapper)
        self.most_recently_deserialized_trade = None
        return self

    async def get_offers_with_status(self, status: TradeStatus) -> List[TradeRecord]:
        records = await self.trade_store.get_trade_record_with_status(status)
        return records

    async def get_coins_of_interest(
        self,
    ) -> Set[bytes32]:
        """
        Returns list of coins we want to check if they are included in filter,
        These will include coins that belong to us and coins that that on other side of treade
        """
        coin_ids = await self.trade_store.get_coin_ids_of_interest_with_trade_statuses(
            trade_statuses=[TradeStatus.PENDING_ACCEPT, TradeStatus.PENDING_CONFIRM, TradeStatus.PENDING_CANCEL]
        )
        return coin_ids

    async def get_trade_by_coin(self, coin: Coin) -> Optional[TradeRecord]:
        all_trades = await self.get_all_trades()
        for trade in all_trades:
            if trade.status == TradeStatus.CANCELLED.value:
                continue
            if coin in trade.coins_of_interest:
                return trade
        return None

    async def coins_of_interest_farmed(
        self, coin_state: CoinState, fork_height: Optional[uint32], peer: WSChiaConnection
    ) -> None:
        """
        If both our coins and other coins in trade got removed that means that trade was successfully executed
        If coins from other side of trade got farmed without ours, that means that trade failed because either someone
        else completed trade or other side of trade canceled the trade by doing a spend.
        If our coins got farmed but coins from other side didn't, we successfully canceled trade by spending inputs.
        """
        self.log.info(f"coins_of_interest_farmed: {coin_state}")
        trade = await self.get_trade_by_coin(coin_state.coin)
        if trade is None:
            self.log.error(f"Coin: {coin_state.coin}, not in any trade")
            return
        if coin_state.spent_height is None:
            self.log.error(f"Coin: {coin_state.coin}, has not been spent so trade can remain valid")
        # Then let's filter the offer into coins that WE offered
        if (
            self.most_recently_deserialized_trade is not None
            and trade.trade_id == self.most_recently_deserialized_trade[0]
        ):
            offer = self.most_recently_deserialized_trade[1]
        else:
            offer = Offer.from_bytes(trade.offer)
            self.most_recently_deserialized_trade = (trade.trade_id, offer)
        primary_coin_ids = [c.name() for c in offer.removals()]
        # TODO: Add `WalletCoinStore.get_coins`.
        result = await self.wallet_state_manager.coin_store.get_coin_records(
            coin_id_filter=HashFilter.include(primary_coin_ids)
        )
        our_primary_coins: List[Coin] = [cr.coin for cr in result.records]
        our_additions: List[Coin] = list(
            filter(lambda c: offer.get_root_removal(c) in our_primary_coins, offer.additions())
        )
        our_addition_ids: List[bytes32] = [c.name() for c in our_additions]

        # And get all relevant coin states
        coin_states = await self.wallet_state_manager.wallet_node.get_coin_state(
            our_addition_ids,
            peer=peer,
            fork_height=fork_height,
        )
        assert coin_states is not None
        coin_state_names: List[bytes32] = [cs.coin.name() for cs in coin_states]
        # If any of our settlement_payments were spent, this offer was a success!
        if set(our_addition_ids) == set(coin_state_names):
            height = coin_state.spent_height
            assert height is not None
            await self.trade_store.set_status(trade.trade_id, TradeStatus.CONFIRMED, index=height)
            tx_records: List[TransactionRecord] = await self.calculate_tx_records_for_offer(offer, False)
            for tx in tx_records:
                if TradeStatus(trade.status) == TradeStatus.PENDING_ACCEPT:
                    await self.wallet_state_manager.add_transaction(
                        dataclasses.replace(tx, confirmed_at_height=height, confirmed=True)
                    )

            self.log.info(f"Trade with id: {trade.trade_id} confirmed at height: {height}")
        else:
            # In any other scenario this trade failed
            await self.wallet_state_manager.delete_trade_transactions(trade.trade_id)
            if trade.status == TradeStatus.PENDING_CANCEL.value:
                await self.trade_store.set_status(trade.trade_id, TradeStatus.CANCELLED)
                self.log.info(f"Trade with id: {trade.trade_id} canceled")
            elif trade.status == TradeStatus.PENDING_CONFIRM.value:
                await self.trade_store.set_status(trade.trade_id, TradeStatus.FAILED)
                self.log.warning(f"Trade with id: {trade.trade_id} failed")

    async def get_locked_coins(self) -> Dict[bytes32, WalletCoinRecord]:
        """Returns a dictionary of confirmed coins that are locked by a trade."""
        all_pending = []
        pending_accept = await self.get_offers_with_status(TradeStatus.PENDING_ACCEPT)
        pending_confirm = await self.get_offers_with_status(TradeStatus.PENDING_CONFIRM)
        pending_cancel = await self.get_offers_with_status(TradeStatus.PENDING_CANCEL)
        all_pending.extend(pending_accept)
        all_pending.extend(pending_confirm)
        all_pending.extend(pending_cancel)

        coins_of_interest = []
        for trade_offer in all_pending:
            coins_of_interest.extend([c.name() for c in trade_offer.coins_of_interest])

        # TODO:
        #  - No need to get the coin records here, we are only interested in the coin_id on the call site.
        return (
            await self.wallet_state_manager.coin_store.get_coin_records(
                coin_id_filter=HashFilter.include(coins_of_interest)
            )
        ).coin_id_to_record

    async def get_all_trades(self) -> List[TradeRecord]:
        all: List[TradeRecord] = await self.trade_store.get_all_trades()
        return all

    async def get_trade_by_id(self, trade_id: bytes32) -> Optional[TradeRecord]:
        record = await self.trade_store.get_trade_record(trade_id)
        return record

    async def fail_pending_offer(self, trade_id: bytes32) -> None:
        await self.trade_store.set_status(trade_id, TradeStatus.FAILED)
        self.wallet_state_manager.state_changed("offer_failed")

    async def cancel_pending_offers(
        self,
        trades: List[bytes32],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        secure: bool = True,  # Cancel with a transaction on chain
        trade_cache: Dict[bytes32, TradeRecord] = {},  # Optional pre-fetched trade records for optimization
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        """This will create a transaction that includes coins that were offered"""

        # Need to do some pre-figuring of announcements that will be need to be made
        announcement_nonce: bytes32 = std_hash(b"".join(trades))
        trade_records: List[TradeRecord] = []
        all_cancellation_coins: List[List[Coin]] = []
        announcement_creations: Deque[CreateCoinAnnouncement] = deque()
        announcement_assertions: Deque[AssertCoinAnnouncement] = deque()
        for trade_id in trades:
            if trade_id in trade_cache:
                trade = trade_cache[trade_id]
            else:
                potential_trade = await self.trade_store.get_trade_record(trade_id)
                if potential_trade is None:
                    self.log.error(f"Cannot find offer {trade_id.hex()}, skip cancellation.")
                    continue
                else:
                    trade = potential_trade

            cancellation_coins = Offer.from_bytes(trade.offer).get_cancellation_coins()
            for coin in cancellation_coins:
                creation = CreateCoinAnnouncement(msg=announcement_nonce, coin_id=coin.name())
                announcement_creations.append(creation)
                announcement_assertions.append(creation.corresponding_assertion())

            trade_records.append(trade)
            all_cancellation_coins.append(cancellation_coins)

        # Make every coin assert the announcement from the one before them
        announcement_assertions.rotate(1)

        all_txs: List[TransactionRecord] = []
        fee_to_pay: uint64 = fee
        for trade, cancellation_coins in zip(trade_records, all_cancellation_coins):
            self.log.info(f"Secure-Cancel pending offer with id trade_id {trade.trade_id.hex()}")

            if not secure:
                self.wallet_state_manager.state_changed("offer_cancelled")
                await self.trade_store.set_status(trade.trade_id, TradeStatus.CANCELLED)
                continue

            cancellation_additions: List[Coin] = []
            valid_times: ConditionValidTimes = parse_timelock_info(extra_conditions)
            for coin in cancellation_coins:
                wallet = await self.wallet_state_manager.get_wallet_for_coin(coin.name())

                if wallet is None:
                    self.log.error(f"Cannot find wallet for offer {trade.trade_id}, skip cancellation.")
                    continue

                new_ph = await wallet.wallet_state_manager.main_wallet.get_puzzle_hash(
                    new=(not action_scope.config.tx_config.reuse_puzhash)
                )

                if len(trade_records) > 1 or len(cancellation_coins) > 1:
                    announcement_conditions: Tuple[Condition, ...] = (
                        announcement_creations.popleft(),
                        announcement_assertions.popleft(),
                    )
                else:
                    announcement_conditions = tuple()
                async with action_scope.use() as interface:
                    interface.side_effects.selected_coins.append(coin)
                # This should probably not switch on whether or not we're spending a XCH but it has to for now
                if wallet.type() == WalletType.STANDARD_WALLET:
                    assert isinstance(wallet, Wallet)
                    if fee_to_pay > coin.amount:
                        selected_coins: Set[Coin] = await wallet.select_coins(
                            uint64(fee_to_pay - coin.amount),
                            action_scope,
                        )
                        selected_coins.add(coin)
                    else:
                        selected_coins = {coin}
                    async with self.wallet_state_manager.new_action_scope(
                        action_scope.config.tx_config.override(
                            excluded_coin_ids=[],
                        ),
                        push=False,
                    ) as inner_action_scope:
                        await wallet.generate_signed_transaction(
                            uint64(sum(c.amount for c in selected_coins) - fee_to_pay),
                            new_ph,
                            inner_action_scope,
                            origin_id=coin.name(),
                            fee=fee_to_pay,
                            coins=selected_coins,
                            extra_conditions=(*extra_conditions, *announcement_conditions),
                        )
                else:
                    # ATTENTION: new_wallets
                    assert isinstance(wallet, (CATWallet, DataLayerWallet, NFTWallet))
                    async with self.wallet_state_manager.new_action_scope(
                        action_scope.config.tx_config.override(
                            excluded_coin_ids=[],
                        ),
                        push=False,
                    ) as inner_action_scope:
                        await wallet.generate_signed_transaction(
                            [coin.amount],
                            [new_ph],
                            inner_action_scope,
                            fee=fee_to_pay,
                            coins={coin},
                            extra_conditions=(*extra_conditions, *announcement_conditions),
                        )

                cancellation_additions.extend(
                    [
                        add
                        for tx in inner_action_scope.side_effects.transactions
                        if tx.spend_bundle is not None
                        for add in tx.spend_bundle.additions()
                    ]
                )
                all_txs.extend(inner_action_scope.side_effects.transactions)
                fee_to_pay = uint64(0)
                extra_conditions = tuple()

                incoming_tx = TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=new_ph,
                    amount=uint64(coin.amount),
                    fee_amount=fee,
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=None,
                    additions=cancellation_additions,
                    removals=[coin],
                    wallet_id=wallet.id(),
                    sent_to=[],
                    trade_id=None,
                    type=uint32(TransactionType.INCOMING_TX.value),
                    name=cancellation_additions[0].name(),
                    memos=[],
                    valid_times=valid_times,
                )
                all_txs.append(incoming_tx)

            await self.trade_store.set_status(trade.trade_id, TradeStatus.PENDING_CANCEL)

        if secure:
            async with action_scope.use() as interface:
                # We have to combine the spend bundle for these since they are tied with announcements
                all_tx_names = [tx.name for tx in all_txs]
                interface.side_effects.transactions = [
                    tx for tx in interface.side_effects.transactions if tx.name not in all_tx_names
                ]
                final_spend_bundle = WalletSpendBundle.aggregate(
                    [tx.spend_bundle for tx in all_txs if tx.spend_bundle is not None]
                )
                interface.side_effects.transactions.append(
                    dataclasses.replace(all_txs[0], spend_bundle=final_spend_bundle, name=final_spend_bundle.name())
                )
                interface.side_effects.transactions.extend(
                    [dataclasses.replace(tx, spend_bundle=None, fee_amount=fee) for tx in all_txs[1:]]
                )

    async def save_trade(self, trade: TradeRecord, offer: Offer) -> None:
        offer_name: bytes32 = offer.name()
        await self.trade_store.add_trade_record(trade, offer_name)

        # We want to subscribe to the coin IDs of all coins that are not the ephemeral offer coins
        offered_coins: Set[Coin] = {value for values in offer.get_offered_coins().values() for value in values}
        non_offer_additions: Set[Coin] = set(offer.additions()) ^ offered_coins
        non_offer_removals: Set[Coin] = set(offer.removals()) ^ offered_coins
        await self.wallet_state_manager.add_interested_coin_ids(
            [coin.name() for coin in (*non_offer_removals, *non_offer_additions)]
        )

        self.wallet_state_manager.state_changed("offer_added")

    async def create_offer_for_ids(
        self,
        offer: Dict[Union[int, bytes32], int],
        action_scope: WalletActionScope,
        driver_dict: Optional[Dict[bytes32, PuzzleInfo]] = None,
        solver: Optional[Solver] = None,
        fee: uint64 = uint64(0),
        validate_only: bool = False,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        taking: bool = False,
    ) -> Union[Tuple[Literal[True], TradeRecord, None], Tuple[Literal[False], None, str]]:
        if driver_dict is None:
            driver_dict = {}
        if solver is None:
            solver = Solver({})
        result = await self._create_offer_for_ids(
            offer,
            action_scope,
            driver_dict,
            solver,
            fee=fee,
            extra_conditions=extra_conditions,
            taking=taking,
        )
        if not result[0] or result[1] is None:
            raise Exception(f"Error creating offer: {result[2]}")

        success, created_offer, error = result

        now = uint64(int(time.time()))
        trade_offer: TradeRecord = TradeRecord(
            confirmed_at_index=uint32(0),
            accepted_at_time=None,
            created_at_time=now,
            is_my_offer=True,
            sent=uint32(0),
            offer=bytes(created_offer),
            taken_offer=None,
            coins_of_interest=created_offer.get_involved_coins(),
            trade_id=created_offer.name(),
            status=uint32(TradeStatus.PENDING_ACCEPT.value),
            sent_to=[],
            valid_times=parse_timelock_info(extra_conditions),
        )

        if success is True and trade_offer is not None and not validate_only:
            await self.save_trade(trade_offer, created_offer)

        return success, trade_offer, error

    async def _create_offer_for_ids(
        self,
        offer_dict: Dict[Union[int, bytes32], int],
        action_scope: WalletActionScope,
        driver_dict: Optional[Dict[bytes32, PuzzleInfo]] = None,
        solver: Optional[Solver] = None,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
        taking: bool = False,
    ) -> Union[Tuple[Literal[True], Offer, None], Tuple[Literal[False], None, str]]:
        """
        Offer is dictionary of wallet ids and amount
        """
        if driver_dict is None:
            driver_dict = {}
        if solver is None:
            solver = Solver({})
        try:
            coins_to_offer: Dict[Union[int, bytes32], Set[Coin]] = {}
            requested_payments: Dict[Optional[bytes32], List[Payment]] = {}
            offer_dict_no_ints: Dict[Optional[bytes32], int] = {}
            for id, amount in offer_dict.items():
                asset_id: Optional[bytes32] = None
                # asset_id can either be none if asset is XCH or
                # bytes32 if another asset (e.g. NFT, CAT)
                if amount > 0:
                    # this is what we are receiving in the trade
                    memos: List[bytes] = []
                    if isinstance(id, int):
                        wallet_id = uint32(id)
                        wallet = self.wallet_state_manager.wallets.get(wallet_id)
                        assert isinstance(wallet, (CATWallet, Wallet))
                        p2_ph: bytes32 = await wallet.get_puzzle_hash(
                            new=not action_scope.config.tx_config.reuse_puzhash
                        )
                        if wallet.type() != WalletType.STANDARD_WALLET:
                            if callable(getattr(wallet, "get_asset_id", None)):  # ATTENTION: new wallets
                                assert isinstance(wallet, CATWallet)
                                asset_id = bytes32(bytes.fromhex(wallet.get_asset_id()))
                                memos = [p2_ph]
                            else:
                                raise ValueError(
                                    f"Cannot request assets from wallet id {wallet.id()} without more information"
                                )
                    else:
                        p2_ph = await self.wallet_state_manager.main_wallet.get_puzzle_hash(
                            new=not action_scope.config.tx_config.reuse_puzhash
                        )
                        asset_id = id
                        wallet = await self.wallet_state_manager.get_wallet_for_asset_id(asset_id.hex())
                        memos = [p2_ph]
                    requested_payments[asset_id] = [Payment(p2_ph, uint64(amount), memos)]
                elif amount < 0:
                    # this is what we are sending in the trade
                    if isinstance(id, int):
                        wallet_id = uint32(id)
                        wallet = self.wallet_state_manager.wallets[wallet_id]
                        if wallet.type() != WalletType.STANDARD_WALLET:
                            if callable(getattr(wallet, "get_asset_id", None)):  # ATTENTION: new wallets
                                assert isinstance(wallet, CATWallet)
                                asset_id = bytes32(bytes.fromhex(wallet.get_asset_id()))
                            else:
                                raise ValueError(
                                    f"Cannot offer assets from wallet id {wallet.id()} without more information"
                                )
                    else:
                        asset_id = id
                        wallet = await self.wallet_state_manager.get_wallet_for_asset_id(asset_id.hex())
                    assert wallet is not None
                    if not callable(getattr(wallet, "get_coins_to_offer", None)):  # ATTENTION: new wallets
                        raise ValueError(f"Cannot offer coins from wallet id {wallet.id()}")
                    # For the XCH wallet also include the fee amount to the coins we use to pay this offer
                    amount_to_select = abs(amount)
                    if wallet.type() == WalletType.STANDARD_WALLET:
                        amount_to_select += fee
                    assert isinstance(wallet, (CATWallet, DataLayerWallet, NFTWallet, Wallet))
                    if isinstance(wallet, DataLayerWallet):
                        assert asset_id is not None
                        coins_to_offer[id] = await wallet.get_coins_to_offer(launcher_id=asset_id)
                    elif isinstance(wallet, NFTWallet):
                        assert asset_id is not None
                        coins_to_offer[id] = await wallet.get_coins_to_offer(nft_id=asset_id)
                    else:
                        coins_to_offer[id] = await wallet.get_coins_to_offer(
                            asset_id=asset_id,
                            amount=uint64(amount_to_select),
                            action_scope=action_scope,
                        )
                    # Note: if we use check_for_special_offer_making, this is not used.
                elif amount == 0:
                    raise ValueError("You cannot offer nor request 0 amount of something")

                offer_dict_no_ints[asset_id] = amount

                if asset_id is not None and wallet is not None:  # if this asset is not XCH
                    if callable(getattr(wallet, "get_puzzle_info", None)):
                        assert isinstance(wallet, (CATWallet, DataLayerWallet, NFTWallet))
                        puzzle_driver: PuzzleInfo = await wallet.get_puzzle_info(asset_id)
                        if asset_id in driver_dict and driver_dict[asset_id] != puzzle_driver:
                            # ignore the case if we're an nft transferring the did owner
                            if self.check_for_owner_change_in_drivers(puzzle_driver, driver_dict[asset_id]):
                                driver_dict[asset_id] = puzzle_driver
                            else:
                                raise ValueError(
                                    f"driver_dict specified {driver_dict[asset_id]}, was expecting {puzzle_driver}"
                                )
                        else:
                            driver_dict[asset_id] = puzzle_driver
                    else:
                        raise ValueError(f"Wallet for asset id {asset_id} is not properly integrated with TradeManager")

            requested_payments = await self.check_for_requested_payment_modifications(
                requested_payments, driver_dict, taking
            )

            potential_special_offer: Optional[Offer] = await self.check_for_special_offer_making(
                offer_dict_no_ints,
                driver_dict,
                action_scope,
                solver,
                fee,
                extra_conditions,
            )

            if potential_special_offer is not None:
                return True, potential_special_offer, None

            all_coins: List[Coin] = [c for coins in coins_to_offer.values() for c in coins]
            notarized_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
                requested_payments, all_coins
            )
            announcements_to_assert = Offer.calculate_announcements(notarized_payments, driver_dict)

            all_transactions: List[TransactionRecord] = []
            fee_left_to_pay: uint64 = fee
            # The access of the sorted keys here makes sure we create the XCH transaction first to make sure we pay fee
            # with the XCH side of the offer and don't create an extra fee transaction in other wallets.
            for id in sorted(coins_to_offer.keys(), key=lambda id: id != 1):
                selected_coins = coins_to_offer[id]
                if isinstance(id, int):
                    wallet = self.wallet_state_manager.wallets.get(uint32(id))
                else:
                    wallet = await self.wallet_state_manager.get_wallet_for_asset_id(id.hex())
                async with self.wallet_state_manager.new_action_scope(
                    action_scope.config.tx_config, push=False
                ) as inner_action_scope:
                    # This should probably not switch on whether or not we're spending XCH but it has to for now
                    assert wallet is not None
                    if wallet.type() == WalletType.STANDARD_WALLET:
                        assert isinstance(wallet, Wallet)
                        await wallet.generate_signed_transaction(
                            uint64(abs(offer_dict[id])),
                            Offer.ph(),
                            inner_action_scope,
                            fee=fee_left_to_pay,
                            coins=selected_coins,
                            extra_conditions=(*extra_conditions, *announcements_to_assert),
                        )
                    elif wallet.type() == WalletType.NFT:
                        assert isinstance(wallet, NFTWallet)
                        # This is to generate the tx for specific nft assets, i.e. not using
                        # wallet_id as the selector which would select any coins from nft_wallet
                        amounts = [coin.amount for coin in selected_coins]
                        await wallet.generate_signed_transaction(
                            # [abs(offer_dict[id])],
                            amounts,
                            [Offer.ph()],
                            inner_action_scope,
                            fee=fee_left_to_pay,
                            coins=selected_coins,
                            extra_conditions=(*extra_conditions, *announcements_to_assert),
                        )
                    else:
                        # ATTENTION: new_wallets
                        assert isinstance(wallet, (CATWallet, DataLayerWallet))
                        await wallet.generate_signed_transaction(
                            [uint64(abs(offer_dict[id]))],
                            [Offer.ph()],
                            inner_action_scope,
                            fee=fee_left_to_pay,
                            coins=selected_coins,
                            extra_conditions=(*extra_conditions, *announcements_to_assert),
                            add_authorizations_to_cr_cats=False,
                        )

                all_transactions.extend(inner_action_scope.side_effects.transactions)

                fee_left_to_pay = uint64(0)
                extra_conditions = tuple()

            async with action_scope.use() as interface:
                interface.side_effects.transactions.extend(all_transactions)

            total_spend_bundle = WalletSpendBundle.aggregate(
                [x.spend_bundle for x in all_transactions if x.spend_bundle is not None]
            )

            offer = Offer(notarized_payments, total_spend_bundle, driver_dict)
            return True, offer, None

        except Exception as e:
            self.log.exception("Error creating trade offer")
            return False, None, str(e)

    async def maybe_create_wallets_for_offer(self, offer: Offer) -> None:
        for key in offer.arbitrage():
            wsm = self.wallet_state_manager
            if key is None:
                continue
            # ATTENTION: new_wallets
            exists = await wsm.get_wallet_for_puzzle_info(offer.driver_dict[key])
            if exists is None:
                await wsm.create_wallet_for_puzzle_info(offer.driver_dict[key])

    async def check_offer_validity(self, offer: Offer, peer: WSChiaConnection) -> bool:
        all_removals: List[Coin] = offer.removals()
        all_removal_names: List[bytes32] = [c.name() for c in all_removals]
        non_ephemeral_removals: List[Coin] = list(
            filter(lambda c: c.parent_coin_info not in all_removal_names, all_removals)
        )
        coin_states = await self.wallet_state_manager.wallet_node.get_coin_state(
            [c.name() for c in non_ephemeral_removals], peer=peer
        )

        return len(coin_states) == len(non_ephemeral_removals) and all([cs.spent_height is None for cs in coin_states])

    async def calculate_tx_records_for_offer(self, offer: Offer, validate: bool) -> List[TransactionRecord]:
        if validate:
            final_spend_bundle: WalletSpendBundle = offer.to_valid_spend()
            hint_dict: Dict[bytes32, bytes32] = {}
            additions_dict: Dict[bytes32, Coin] = {}
            for hinted_coins, _ in (
                compute_spend_hints_and_additions(spend) for spend in final_spend_bundle.coin_spends
            ):
                hint_dict.update({id: hc.hint for id, hc in hinted_coins.items() if hc.hint is not None})
                additions_dict.update({id: hc.coin for id, hc in hinted_coins.items()})
            all_additions: List[Coin] = list(a for a in additions_dict.values())
        else:
            final_spend_bundle = offer._bundle
            hint_dict = offer.hints()
            all_additions = offer.additions()

        settlement_coins: List[Coin] = [c for coins in offer.get_offered_coins().values() for c in coins]
        settlement_coin_ids: List[bytes32] = [c.name() for c in settlement_coins]

        removals: List[Coin] = final_spend_bundle.removals()
        additions: List[Coin] = list(a for a in all_additions if a not in removals)
        valid_times: ConditionValidTimes = parse_timelock_info(
            parse_conditions_non_consensus(
                condition
                for spend in final_spend_bundle.coin_spends
                for condition in spend.puzzle_reveal.to_program().run(spend.solution.to_program()).as_iter()
            )
        )
        # this executes the puzzles again
        all_fees = uint64(estimate_fees(final_spend_bundle))

        txs = []

        addition_dict: Dict[uint32, List[Coin]] = {}
        for addition in additions:
            wallet_identifier = await self.wallet_state_manager.get_wallet_identifier_for_coin(
                addition,
                hint_dict,
            )
            if wallet_identifier is not None:
                if addition.parent_coin_info in settlement_coin_ids:
                    wallet = self.wallet_state_manager.wallets[wallet_identifier.id]
                    assert isinstance(wallet, (CATWallet, NFTWallet, Wallet))
                    to_puzzle_hash = await wallet.convert_puzzle_hash(addition.puzzle_hash)  # ATTENTION: new wallets
                    txs.append(
                        TransactionRecord(
                            confirmed_at_height=uint32(0),
                            created_at_time=uint64(int(time.time())),
                            to_puzzle_hash=to_puzzle_hash,
                            amount=uint64(addition.amount),
                            fee_amount=uint64(0),
                            confirmed=False,
                            sent=uint32(10),
                            spend_bundle=None,
                            additions=[addition],
                            removals=[],
                            wallet_id=wallet_identifier.id,
                            sent_to=[],
                            trade_id=offer.name(),
                            type=uint32(TransactionType.INCOMING_TRADE.value),
                            name=std_hash(final_spend_bundle.name() + addition.name()),
                            memos=[(coin_id, [hint]) for coin_id, hint in hint_dict.items()],
                            valid_times=valid_times,
                        )
                    )
                else:  # This is change
                    addition_dict.setdefault(wallet_identifier.id, [])
                    addition_dict[wallet_identifier.id].append(addition)

        # While we want additions to show up as separate records, removals of the same wallet should show as one
        removal_dict: Dict[uint32, List[Coin]] = {}
        for removal in removals:
            wallet_identifier = await self.wallet_state_manager.get_wallet_identifier_for_coin(
                removal,
                hint_dict,
            )
            if wallet_identifier is not None:
                removal_dict.setdefault(wallet_identifier.id, [])
                removal_dict[wallet_identifier.id].append(removal)

        all_removals: List[bytes32] = [r.name() for removals in removal_dict.values() for r in removals]

        for wid, grouped_removals in removal_dict.items():
            wallet = self.wallet_state_manager.wallets[wid]
            to_puzzle_hash = bytes32([1] * 32)  # We use all zeros to be clear not to send here
            removal_tree_hash = Program.to([coin_as_list(rem) for rem in grouped_removals]).get_tree_hash()
            # We also need to calculate the sent amount
            removed: int = sum(c.amount for c in grouped_removals)
            removed_ids: List[bytes32] = [c.name() for c in grouped_removals]
            all_additions_from_grouped_removals: List[Coin] = [
                c for c in all_additions if c.parent_coin_info in removed_ids
            ]
            potential_change_coins: List[Coin] = addition_dict[wid] if wid in addition_dict else []
            change_coins: List[Coin] = [c for c in potential_change_coins if c.parent_coin_info in all_removals]
            change_amount: int = sum(c.amount for c in change_coins)
            sent_amount: int = (
                removed
                - change_amount
                - (
                    removed - sum(c.amount for c in all_additions_from_grouped_removals)  # removals - additions == fees
                    if wallet == self.wallet_state_manager.main_wallet
                    else 0
                )
            )
            txs.append(
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=to_puzzle_hash,
                    amount=uint64(sent_amount),
                    fee_amount=all_fees,
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=None,
                    additions=change_coins,
                    removals=grouped_removals,
                    wallet_id=wallet.id(),
                    sent_to=[],
                    trade_id=offer.name(),
                    type=uint32(TransactionType.OUTGOING_TRADE.value),
                    name=std_hash(final_spend_bundle.name() + removal_tree_hash),
                    memos=[(coin_id, [hint]) for coin_id, hint in hint_dict.items()],
                    valid_times=valid_times,
                )
            )

        return txs

    async def respond_to_offer(
        self,
        offer: Offer,
        peer: WSChiaConnection,
        action_scope: WalletActionScope,
        solver: Optional[Solver] = None,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> TradeRecord:
        if solver is None:
            solver = Solver({})
        take_offer_dict: Dict[Union[bytes32, int], int] = {}
        arbitrage: Dict[Optional[bytes32], int] = offer.arbitrage()

        for asset_id, amount in arbitrage.items():
            if asset_id is None:
                wallet: Optional[WalletProtocol[Any]] = self.wallet_state_manager.main_wallet
                assert wallet is not None
                key: Union[bytes32, int] = int(wallet.id())
            else:
                # ATTENTION: new wallets
                wallet = await self.wallet_state_manager.get_wallet_for_asset_id(asset_id.hex())
                if wallet is None and amount < 0:
                    raise ValueError(f"Do not have a wallet for asset ID: {asset_id} to fulfill offer")
                elif wallet is None or wallet.type() in [WalletType.NFT, WalletType.DATA_LAYER]:
                    key = asset_id
                else:
                    key = int(wallet.id())
            take_offer_dict[key] = amount

        # First we validate that all of the coins in this offer exist
        valid: bool = await self.check_offer_validity(offer, peer)
        if not valid:
            raise ValueError("This offer is no longer valid")
        # We need to sandbox the transactions here because we're going to make our own
        async with self.wallet_state_manager.new_action_scope(
            action_scope.config.tx_config, push=False
        ) as inner_action_scope:
            result = await self._create_offer_for_ids(
                take_offer_dict,
                inner_action_scope,
                offer.driver_dict,
                solver,
                fee=fee,
                extra_conditions=extra_conditions,
                taking=True,
            )
            if not result[0] or result[1] is None:
                raise ValueError(result[2])

            success, take_offer, error = result

            complete_offer, valid_spend_solver = await self.check_for_final_modifications(
                Offer.aggregate([offer, take_offer]), solver, inner_action_scope
            )
        self.log.info("COMPLETE OFFER: %s", complete_offer.to_bech32())
        assert complete_offer.is_valid()
        final_spend_bundle: WalletSpendBundle = complete_offer.to_valid_spend(
            solver=Solver({**valid_spend_solver.info, **solver.info})
        )
        await self.maybe_create_wallets_for_offer(complete_offer)

        tx_records: List[TransactionRecord] = await self.calculate_tx_records_for_offer(complete_offer, True)

        trade_record: TradeRecord = TradeRecord(
            confirmed_at_index=uint32(0),
            accepted_at_time=uint64(int(time.time())),
            created_at_time=uint64(int(time.time())),
            is_my_offer=False,
            sent=uint32(0),
            offer=bytes(complete_offer),
            taken_offer=bytes(offer),
            coins_of_interest=complete_offer.get_involved_coins(),
            trade_id=complete_offer.name(),
            status=uint32(TradeStatus.PENDING_CONFIRM.value),
            sent_to=[],
            valid_times=parse_timelock_info(extra_conditions),
        )

        await self.save_trade(trade_record, offer)

        async with action_scope.use() as interface:
            interface.side_effects.transactions.extend(tx_records)
            interface.side_effects.extra_spends.append(final_spend_bundle)

        return trade_record

    async def check_for_special_offer_making(
        self,
        offer_dict: Dict[Optional[bytes32], int],
        driver_dict: Dict[bytes32, PuzzleInfo],
        action_scope: WalletActionScope,
        solver: Solver,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> Optional[Offer]:
        for puzzle_info in driver_dict.values():
            if (
                puzzle_info.check_type([AssetType.SINGLETON.value, AssetType.METADATA.value, AssetType.OWNERSHIP.value])
                and isinstance(puzzle_info.also().also()["transfer_program"], PuzzleInfo)  # type: ignore
                and puzzle_info.also().also()["transfer_program"].type()  # type: ignore
                == AssetType.ROYALTY_TRANSFER_PROGRAM.value
            ):
                return await NFTWallet.make_nft1_offer(
                    self.wallet_state_manager, offer_dict, driver_dict, action_scope, fee, extra_conditions
                )
            elif (
                puzzle_info.check_type(
                    [
                        AssetType.SINGLETON.value,
                        AssetType.METADATA.value,
                    ]
                )
                and puzzle_info.also()["updater_hash"] == ACS_MU_PH  # type: ignore
            ):
                return await DataLayerWallet.make_update_offer(
                    self.wallet_state_manager,
                    offer_dict,
                    driver_dict,
                    solver,
                    action_scope,
                    fee,
                    extra_conditions,
                )
        return None

    def check_for_owner_change_in_drivers(self, puzzle_info: PuzzleInfo, driver_info: PuzzleInfo) -> bool:
        if puzzle_info.check_type(
            [
                AssetType.SINGLETON.value,
                AssetType.METADATA.value,
                AssetType.OWNERSHIP.value,
            ]
        ) and driver_info.check_type(
            [
                AssetType.SINGLETON.value,
                AssetType.METADATA.value,
                AssetType.OWNERSHIP.value,
            ]
        ):
            old_owner = driver_info.also().also().info["owner"]  # type: ignore
            puzzle_info.also().also().info["owner"] = old_owner  # type: ignore
            if driver_info == puzzle_info:
                return True
        return False

    async def get_offer_summary(self, offer: Offer) -> Dict[str, Any]:
        for puzzle_info in offer.driver_dict.values():
            if (
                puzzle_info.check_type(
                    [
                        AssetType.SINGLETON.value,
                        AssetType.METADATA.value,
                    ]
                )
                and puzzle_info.also()["updater_hash"] == ACS_MU_PH  # type: ignore
            ):
                return await DataLayerWallet.get_offer_summary(offer)
        # Otherwise just return the same thing as the RPC normally does
        offered, requested, infos, valid_times = offer.summary()
        return {
            "offered": offered,
            "requested": requested,
            "fees": offer.fees(),
            "additions": [c.name().hex() for c in offer.additions()],
            "removals": [c.name().hex() for c in offer.removals()],
            "infos": infos,
            "valid_times": {
                k: v
                for k, v in valid_times.to_json_dict().items()
                if k
                not in (
                    "max_secs_after_created",
                    "min_secs_since_created",
                    "max_blocks_after_created",
                    "min_blocks_since_created",
                )
            },
        }

    async def check_for_final_modifications(
        self, offer: Offer, solver: Solver, action_scope: WalletActionScope
    ) -> Tuple[Offer, Solver]:
        for puzzle_info in offer.driver_dict.values():
            if (
                puzzle_info.check_type(
                    [
                        AssetType.SINGLETON.value,
                        AssetType.METADATA.value,
                    ]
                )
                and puzzle_info.also()["updater_hash"] == ACS_MU_PH  # type: ignore
            ):
                return (await DataLayerWallet.finish_graftroot_solutions(offer, solver), Solver({}))
            elif puzzle_info.check_type(
                [
                    AssetType.CAT.value,
                    AssetType.CR.value,
                ]
            ):
                # get VC wallet
                for _, wallet in self.wallet_state_manager.wallets.items():
                    if WalletType(wallet.type()) == WalletType.VC:
                        assert isinstance(wallet, VCWallet)
                        return await wallet.add_vc_authorization(offer, solver, action_scope)
                else:
                    raise ValueError("No VCs to approve CR-CATs with")  # pragma: no cover

        return offer, Solver({})

    async def check_for_requested_payment_modifications(
        self,
        requested_payments: Dict[Optional[bytes32], List[Payment]],
        driver_dict: Dict[bytes32, PuzzleInfo],
        taking: bool,
    ) -> Dict[Optional[bytes32], List[Payment]]:
        # This function exclusively deals with CR-CATs for now
        if not taking:
            for asset_id, puzzle_info in driver_dict.items():
                if puzzle_info.check_type(
                    [
                        AssetType.CAT.value,
                        AssetType.CR.value,
                    ]
                ):
                    vc = await (
                        await self.wallet_state_manager.get_or_create_vc_wallet()
                    ).get_vc_with_provider_in_and_proofs(
                        puzzle_info["also"]["authorized_providers"],
                        ProofsChecker.from_program(uncurry_puzzle(puzzle_info["also"]["proofs_checker"])).flags,
                    )
                    if vc is None:
                        raise ValueError("Cannot request CR-CATs that you cannot approve with a VC")  # pragma: no cover

            return {
                asset_id: (
                    [
                        dataclasses.replace(
                            payment,
                            puzzle_hash=construct_pending_approval_state(
                                payment.puzzle_hash, payment.amount
                            ).get_tree_hash(),
                        )
                        for payment in payments
                    ]
                    if asset_id is not None
                    and driver_dict[asset_id].check_type(
                        [
                            AssetType.CAT.value,
                            AssetType.CR.value,
                        ]
                    )
                    else payments
                )
                for asset_id, payments in requested_payments.items()
            }
        else:
            return requested_payments
