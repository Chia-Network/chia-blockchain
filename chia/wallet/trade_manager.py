import logging
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple, Union, Set

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.db_wrapper import DBWrapper
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.payment import Payment
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer, NotarizedPayment
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.trading.trade_store import TradeStore
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord


class TradeManager:
    wallet_state_manager: Any
    log: logging.Logger
    trade_store: TradeStore

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        db_wrapper: DBWrapper,
        name: str = None,
    ):
        self = TradeManager()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.trade_store = await TradeStore.create(db_wrapper)
        return self

    async def get_offers_with_status(self, status: TradeStatus) -> List[TradeRecord]:
        records = await self.trade_store.get_trade_record_with_status(status)
        return records

    async def get_coins_of_interest(
        self,
    ) -> Dict[bytes32, Coin]:
        """
        Returns list of coins we want to check if they are included in filter,
        These will include coins that belong to us and coins that that on other side of treade
        """
        all_pending = []
        pending_accept = await self.get_offers_with_status(TradeStatus.PENDING_ACCEPT)
        pending_confirm = await self.get_offers_with_status(TradeStatus.PENDING_CONFIRM)
        pending_cancel = await self.get_offers_with_status(TradeStatus.PENDING_CANCEL)
        all_pending.extend(pending_accept)
        all_pending.extend(pending_confirm)
        all_pending.extend(pending_cancel)
        interested_dict = {}

        for trade in all_pending:
            for coin in trade.coins_of_interest:
                interested_dict[coin.name()] = coin

        return interested_dict

    async def get_trade_by_coin(self, coin: Coin) -> Optional[TradeRecord]:
        all_trades = await self.get_all_trades()
        for trade in all_trades:
            if trade.status == TradeStatus.CANCELLED.value:
                continue
            if coin in trade.coins_of_interest:
                return trade
        return None

    async def coins_of_interest_farmed(self, coin_state: CoinState):
        """
        If both our coins and other coins in trade got removed that means that trade was successfully executed
        If coins from other side of trade got farmed without ours, that means that trade failed because either someone
        else completed trade or other side of trade canceled the trade by doing a spend.
        If our coins got farmed but coins from other side didn't, we successfully canceled trade by spending inputs.
        """
        trade = await self.get_trade_by_coin(coin_state.coin)
        if trade is None:
            self.log.error(f"Coin: {coin_state.coin}, not in any trade")
            return
        if coin_state.spent_height is None:
            self.log.error(f"Coin: {coin_state.coin}, has not been spent so trade can remain valid")

        # Then let's filter the offer into coins that WE offered
        offer = Offer.from_bytes(trade.offer)
        primary_coin_ids = [c.name() for c in offer.get_primary_coins()]
        our_coin_records: List[WalletCoinRecord] = await self.wallet_state_manager.coin_store.get_multiple_coin_records(
            primary_coin_ids
        )
        our_primary_coins: List[bytes32] = [cr.coin.name() for cr in our_coin_records]
        all_settlement_payments: List[Coin] = [c for coins in offer.get_offered_coins().values() for c in coins]
        our_settlement_payments: List[Coin] = list(
            filter(lambda c: offer.get_root_removal(c).name() in our_primary_coins, all_settlement_payments)
        )
        our_settlement_ids: List[bytes32] = [c.name() for c in our_settlement_payments]

        # And get all relevant coin states
        coin_states = await self.wallet_state_manager.get_coin_state(our_settlement_ids)
        assert coin_states is not None
        coin_state_names: List[bytes32] = [cs.coin.name() for cs in coin_states]

        # If any of our settlement_payments were spent, this offer was a success!
        if set(our_settlement_ids) & set(coin_state_names):
            height = coin_states[0].spent_height
            await self.trade_store.set_status(trade.trade_id, TradeStatus.CONFIRMED, True, height)
            self.log.info(f"Trade with id: {trade.trade_id} confirmed at height: {height}")
        else:
            # In any other scenario this trade failed
            await self.wallet_state_manager.delete_trade_transactions(trade.trade_id)
            if trade.status == TradeStatus.PENDING_CANCEL.value:
                await self.trade_store.set_status(trade.trade_id, TradeStatus.CANCELLED, True)
                self.log.info(f"Trade with id: {trade.trade_id} canceled")
            elif trade.status == TradeStatus.PENDING_CONFIRM.value:
                await self.trade_store.set_status(trade.trade_id, TradeStatus.FAILED, True)
                self.log.warning(f"Trade with id: {trade.trade_id} failed")

    async def get_locked_coins(self, wallet_id: int = None) -> Dict[bytes32, WalletCoinRecord]:
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
            coins_of_interest.extend([c.name() for c in Offer.from_bytes(trade_offer.offer).get_involved_coins()])

        result = {}
        coin_records = await self.wallet_state_manager.coin_store.get_multiple_coin_records(coins_of_interest)
        for record in coin_records:
            if wallet_id is None or record.wallet_id == wallet_id:
                result[record.name()] = record

        return result

    async def get_all_trades(self):
        all: List[TradeRecord] = await self.trade_store.get_all_trades()
        return all

    async def get_trade_by_id(self, trade_id: bytes32) -> Optional[TradeRecord]:
        record = await self.trade_store.get_trade_record(trade_id)
        return record

    async def cancel_pending_offer(self, trade_id: bytes32):
        await self.trade_store.set_status(trade_id, TradeStatus.CANCELLED, False)

    async def cancel_pending_offer_safely(
        self, trade_id: bytes32, fee: uint64 = uint64(0)
    ) -> Optional[List[TransactionRecord]]:
        """This will create a transaction that includes coins that were offered"""
        self.log.info(f"Secure-Cancel pending offer with id trade_id {trade_id.hex()}")
        trade = await self.trade_store.get_trade_record(trade_id)
        if trade is None:
            return None

        all_txs: List[TransactionRecord] = []
        fee_to_pay: uint64 = fee
        for coin in Offer.from_bytes(trade.offer).get_primary_coins():
            wallet = await self.wallet_state_manager.get_wallet_for_coin(coin.name())

            if wallet is None:
                continue
            new_ph = await wallet.get_new_puzzlehash()
            # This should probably not switch on whether or not we're spending a CAT but it has to for now
            if wallet.type() == WalletType.CAT:
                txs = await wallet.generate_signed_transaction(
                    [coin.amount], [new_ph], fee=fee_to_pay, coins={coin}, ignore_max_send_amount=True
                )
                all_txs.extend(txs)
            else:
                if fee_to_pay > coin.amount:
                    selected_coins: Set[Coin] = await wallet.select_coins(
                        uint64(fee_to_pay - coin.amount),
                        exclude=[coin],
                    )
                    selected_coins.add(coin)
                else:
                    selected_coins = {coin}
                tx = await wallet.generate_signed_transaction(
                    uint64(sum([c.amount for c in selected_coins]) - fee_to_pay),
                    new_ph,
                    fee=fee_to_pay,
                    coins=selected_coins,
                    ignore_max_send_amount=True,
                )
                all_txs.append(tx)
            fee_to_pay = uint64(0)

        for tx in all_txs:
            await self.wallet_state_manager.add_pending_transaction(tx_record=tx)

        await self.trade_store.set_status(trade_id, TradeStatus.PENDING_CANCEL, False)

        return all_txs

    async def save_trade(self, trade: TradeRecord):
        await self.trade_store.add_trade_record(trade, False)

    async def create_offer_for_ids(
        self, offer: Dict[Union[int, bytes32], int], fee: uint64 = uint64(0), validate_only: bool = False
    ) -> Tuple[bool, Optional[TradeRecord], Optional[str]]:
        success, created_offer, error = await self._create_offer_for_ids(offer, fee=fee)
        if not success or created_offer is None:
            raise Exception(f"Error creating offer: {error}")

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
        )

        if success is True and trade_offer is not None and not validate_only:
            await self.save_trade(trade_offer)

        return success, trade_offer, error

    async def _create_offer_for_ids(
        self, offer_dict: Dict[Union[int, bytes32], int], fee: uint64 = uint64(0)
    ) -> Tuple[bool, Optional[Offer], Optional[str]]:
        """
        Offer is dictionary of wallet ids and amount
        """
        try:
            coins_to_offer: Dict[uint32, List[Coin]] = {}
            requested_payments: Dict[Optional[bytes32], List[Payment]] = {}
            for id, amount in offer_dict.items():
                if amount > 0:
                    if isinstance(id, int):
                        wallet_id = uint32(id)
                        wallet = self.wallet_state_manager.wallets[wallet_id]
                        p2_ph: bytes32 = await wallet.get_new_puzzlehash()
                        if wallet.type() == WalletType.STANDARD_WALLET:
                            key: Optional[bytes32] = None
                            memos: List[bytes] = []
                        elif wallet.type() == WalletType.CAT:
                            key = bytes32(bytes.fromhex(wallet.get_asset_id()))
                            memos = [p2_ph]
                        else:
                            raise ValueError(f"Offers are not implemented for {wallet.type()}")
                    else:
                        p2_ph = await self.wallet_state_manager.main_wallet.get_new_puzzlehash()
                        key = id
                        memos = [p2_ph]
                    requested_payments[key] = [Payment(p2_ph, uint64(amount), memos)]
                elif amount < 0:
                    assert isinstance(id, int)
                    wallet_id = uint32(id)
                    wallet = self.wallet_state_manager.wallets[wallet_id]
                    balance = await wallet.get_confirmed_balance()
                    if balance < abs(amount):
                        raise Exception(f"insufficient funds in wallet {wallet_id}")
                    coins_to_offer[wallet_id] = await wallet.select_coins(uint64(abs(amount)))
                elif amount == 0:
                    raise ValueError("You cannot offer nor request 0 amount of something")

            all_coins: List[Coin] = [c for coins in coins_to_offer.values() for c in coins]
            notarized_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
                requested_payments, all_coins
            )
            announcements_to_assert = Offer.calculate_announcements(notarized_payments)

            all_transactions: List[TransactionRecord] = []
            fee_left_to_pay: uint64 = fee
            for wallet_id, selected_coins in coins_to_offer.items():
                wallet = self.wallet_state_manager.wallets[wallet_id]
                # This should probably not switch on whether or not we're spending a CAT but it has to for now

                if wallet.type() == WalletType.CAT:
                    txs = await wallet.generate_signed_transaction(
                        [abs(offer_dict[int(wallet_id)])],
                        [Offer.ph()],
                        fee=fee_left_to_pay,
                        coins=set(selected_coins),
                        puzzle_announcements_to_consume=announcements_to_assert,
                    )
                    all_transactions.extend(txs)
                else:
                    tx = await wallet.generate_signed_transaction(
                        abs(offer_dict[int(wallet_id)]),
                        Offer.ph(),
                        fee=fee_left_to_pay,
                        coins=set(selected_coins),
                        puzzle_announcements_to_consume=announcements_to_assert,
                    )
                    all_transactions.append(tx)

                fee_left_to_pay = uint64(0)

            transaction_bundles: List[Optional[SpendBundle]] = [tx.spend_bundle for tx in all_transactions]
            total_spend_bundle = SpendBundle.aggregate(list(filter(lambda b: b is not None, transaction_bundles)))
            offer = Offer(notarized_payments, total_spend_bundle)
            return True, offer, None

        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Error with creating trade offer: {type(e)}{tb}")
            return False, None, str(e)

    async def maybe_create_wallets_for_offer(self, offer: Offer):

        for key in offer.arbitrage():
            wsm = self.wallet_state_manager
            wallet: Wallet = wsm.main_wallet
            if key is None:
                continue
            exists: Optional[Wallet] = await wsm.get_wallet_for_asset_id(key.hex())
            if exists is None:
                self.log.info(f"Creating wallet for asset ID: {key}")
                await CATWallet.create_wallet_for_cat(wsm, wallet, key.hex())

    async def check_offer_validity(self, offer: Offer) -> bool:
        all_removals: List[Coin] = offer.bundle.removals()
        all_removal_names: List[bytes32] = [c.name() for c in all_removals]
        non_ephemeral_removals: List[Coin] = list(
            filter(lambda c: c.parent_coin_info not in all_removal_names, all_removals)
        )
        coin_states = await self.wallet_state_manager.get_coin_state([c.name() for c in non_ephemeral_removals])
        assert coin_states is not None
        return not any([cs.spent_height is not None for cs in coin_states])

    async def respond_to_offer(self, offer: Offer, fee=uint64(0)) -> Tuple[bool, Optional[TradeRecord], Optional[str]]:
        take_offer_dict: Dict[Union[bytes32, int], int] = {}
        arbitrage: Dict[Optional[bytes32], int] = offer.arbitrage()
        for asset_id, amount in arbitrage.items():
            if asset_id is None:
                wallet = self.wallet_state_manager.main_wallet
                key: Union[bytes32, int] = int(wallet.id())
            else:
                wallet = await self.wallet_state_manager.get_wallet_for_asset_id(asset_id.hex())
                if wallet is None and amount < 0:
                    return False, None, f"Do not have a CAT of asset ID: {asset_id} to fulfill offer"
                elif wallet is None:
                    key = asset_id
                else:
                    key = int(wallet.id())
            take_offer_dict[key] = amount

        # First we validate that all of the coins in this offer exist
        valid: bool = await self.check_offer_validity(offer)
        if not valid:
            return False, None, "This offer is no longer valid"

        success, take_offer, error = await self._create_offer_for_ids(take_offer_dict, fee=fee)
        if not success or take_offer is None:
            return False, None, error

        complete_offer = Offer.aggregate([offer, take_offer])
        assert complete_offer.is_valid()
        final_spend_bundle: SpendBundle = complete_offer.to_valid_spend()

        await self.maybe_create_wallets_for_offer(complete_offer)

        # Now to deal with transaction history before pushing the spend
        settlement_coins: List[Coin] = [c for coins in complete_offer.get_offered_coins().values() for c in coins]
        settlement_coin_ids: List[bytes32] = [c.name() for c in settlement_coins]
        additions: List[Coin] = final_spend_bundle.not_ephemeral_additions()
        removals: List[Coin] = final_spend_bundle.removals()
        all_fees = uint64(final_spend_bundle.fees())

        txs = []

        addition_dict: Dict[uint32, List[Coin]] = {}
        for addition in additions:
            wallet_info = await self.wallet_state_manager.get_wallet_id_for_puzzle_hash(addition.puzzle_hash)
            if wallet_info is not None:
                wallet_id, _ = wallet_info
                if addition.parent_coin_info in settlement_coin_ids:
                    wallet = self.wallet_state_manager.wallets[wallet_id]
                    to_puzzle_hash = await wallet.convert_puzzle_hash(addition.puzzle_hash)
                    txs.append(
                        TransactionRecord(
                            confirmed_at_height=uint32(0),
                            created_at_time=uint64(int(time.time())),
                            to_puzzle_hash=to_puzzle_hash,
                            amount=addition.amount,
                            fee_amount=uint64(0),
                            confirmed=False,
                            sent=uint32(10),
                            spend_bundle=None,
                            additions=[addition],
                            removals=[],
                            wallet_id=wallet_id,
                            sent_to=[],
                            trade_id=complete_offer.name(),
                            type=uint32(TransactionType.INCOMING_TRADE.value),
                            name=std_hash(final_spend_bundle.name() + addition.name()),
                            memos=[],
                        )
                    )
                else:  # This is change
                    addition_dict.setdefault(wallet_id, [])
                    addition_dict[wallet_id].append(addition)

        # While we want additions to show up as separate records, removals of the same wallet should show as one
        removal_dict: Dict[uint32, List[Coin]] = {}
        for removal in removals:
            wallet_info = await self.wallet_state_manager.get_wallet_id_for_puzzle_hash(removal.puzzle_hash)
            if wallet_info is not None:
                wallet_id, _ = wallet_info
                removal_dict.setdefault(wallet_id, [])
                removal_dict[wallet_id].append(removal)

        for wid, grouped_removals in removal_dict.items():
            wallet = self.wallet_state_manager.wallets[wid]
            to_puzzle_hash = bytes32([1] * 32)  # We use all zeros to be clear not to send here
            removal_tree_hash = Program.to([rem.as_list() for rem in grouped_removals]).get_tree_hash()
            # We also need to calculate the sent amount
            removed: int = sum(c.amount for c in grouped_removals)
            change_coins: List[Coin] = addition_dict[wid] if wid in addition_dict else []
            change_amount: int = sum(c.amount for c in change_coins)
            sent_amount: int = removed - change_amount
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
                    trade_id=complete_offer.name(),
                    type=uint32(TransactionType.OUTGOING_TRADE.value),
                    name=std_hash(final_spend_bundle.name() + removal_tree_hash),
                    memos=[],
                )
            )

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
        )

        await self.save_trade(trade_record)

        # Dummy transaction for the sake of the wallet push
        push_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=bytes32([1] * 32),
            amount=uint64(0),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=final_spend_bundle,
            additions=final_spend_bundle.additions(),
            removals=final_spend_bundle.removals(),
            wallet_id=uint32(0),
            sent_to=[],
            trade_id=complete_offer.name(),
            type=uint32(TransactionType.OUTGOING_TRADE.value),
            name=final_spend_bundle.name(),
            memos=list(final_spend_bundle.get_memos().items()),
        )
        await self.wallet_state_manager.add_pending_transaction(push_tx)
        for tx in txs:
            await self.wallet_state_manager.add_transaction(tx)

        return True, trade_record, None
