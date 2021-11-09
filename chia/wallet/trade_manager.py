import logging
import time
import traceback
from pathlib import Path
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Tuple

from blspy import AugSchemeMPL

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.cat_wallet import cat_utils
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    unsigned_spend_bundle_for_spendable_cats,
    match_cat_puzzle,
)
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.trading.trade_store import TradeStore
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.trade_utils import (
    get_discrepancies_for_spend_bundle,
    get_output_amount_for_puzzle_and_solution,
    get_output_discrepancy_for_puzzle_and_solution,
)
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
    ) -> Tuple[Dict[bytes32, Coin], Dict[bytes32, Coin]]:
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
        removals = {}
        additions = {}

        for trade in all_pending:
            for coin in trade.removals:
                removals[coin.name()] = coin
            for coin in trade.additions:
                additions[coin.name()] = coin

        return removals, additions

    async def get_trade_by_coin(self, coin: Coin) -> Optional[TradeRecord]:
        all_trades = await self.get_all_trades()
        for trade in all_trades:
            if trade.status == TradeStatus.CANCELED.value:
                continue
            if coin in trade.removals:
                return trade
            if coin in trade.additions:
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
            self.log.error(f"Coin: {Coin}, not in any trade")
            return

        # Check if all coins that are part of the trade got farmed
        # If coin is missing, trade failed
        failed = False
        all_coin_names_in_trade = []
        for removed_coin in trade.removals:
            all_coin_names_in_trade.append(removed_coin.name())
        for added_coin in trade.additions:
            all_coin_names_in_trade.append(added_coin.name())

        coin_states = await self.wallet_state_manager.get_coin_state(all_coin_names_in_trade)
        assert coin_states is not None

        #  For this trade to be confirmed all coins involved in a trade must be created/spent on same height
        coin_states_dict: Dict[bytes32, CoinState] = {}
        for cs in coin_states:
            coin_states_dict[cs.coin.name()] = cs

        all_heights = set()

        for removed_coin in trade.removals:
            removed_coin_state = coin_states_dict.get(removed_coin.name(), None)
            if removed_coin_state is None:
                failed = True
                break
            if removed_coin_state.spent_height is None:
                failed = True
                break
            all_heights.add(removed_coin_state.spent_height)

        for added_coin in trade.additions:
            added_coin_state = coin_states_dict.get(added_coin.name(), None)
            if added_coin_state is None:
                failed = True
                break
            if added_coin_state.created_height is None:
                failed = True
                break
            all_heights.add(added_coin_state.created_height)

        if len(all_heights) > 1:
            failed = True

        if failed is False:
            # Mark this trade as successful
            height = all_heights.pop()
            await self.trade_store.set_status(trade.trade_id, TradeStatus.CONFIRMED, True, height)
            self.log.info(f"Trade with id: {trade.trade_id} confirmed at height: {height}")
        else:
            # Either we canceled this trade or this trade failed
            if trade.status == TradeStatus.PENDING_CANCEL.value:
                await self.trade_store.set_status(trade.trade_id, TradeStatus.CANCELED, True)
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
        if len(all_pending) == 0:
            return {}

        result = {}
        for trade_offer in all_pending:
            if trade_offer.tx_spend_bundle is None:
                locked = await self.get_locked_coins_in_spend_bundle(trade_offer.spend_bundle)
            else:
                locked = await self.get_locked_coins_in_spend_bundle(trade_offer.tx_spend_bundle)
            for name, record in locked.items():
                if wallet_id is None or record.wallet_id == wallet_id:
                    result[name] = record

        return result

    async def get_all_trades(self):
        all: List[TradeRecord] = await self.trade_store.get_all_trades()
        return all

    async def get_trade_by_id(self, trade_id: bytes) -> Optional[TradeRecord]:
        record = await self.trade_store.get_trade_record(trade_id)
        return record

    async def get_locked_coins_in_spend_bundle(self, bundle: SpendBundle) -> Dict[bytes32, WalletCoinRecord]:
        """Returns a list of coin records that are used in this SpendBundle"""
        result = {}
        removals = bundle.removals()
        for coin in removals:
            coin_record = await self.wallet_state_manager.coin_store.get_coin_record(coin.name())
            if coin_record is None:
                continue
            result[coin_record.name()] = coin_record
        return result

    async def cancel_pending_offer(self, trade_id: bytes32):
        await self.trade_store.set_status(trade_id, TradeStatus.CANCELED, False)

    async def cancel_pending_offer_safely(self, trade_id: bytes32):
        """This will create a transaction that includes coins that were offered"""
        self.log.info(f"Secure-Cancel pending offer with id trade_id {trade_id.hex()}")
        trade = await self.trade_store.get_trade_record(trade_id)
        if trade is None:
            return None

        all_coins = trade.removals

        for coin in all_coins:
            wallet = await self.wallet_state_manager.get_wallet_for_coin(coin.name())

            if wallet is None:
                continue
            new_ph = await wallet.get_new_puzzlehash()
            if wallet.type() == WalletType.CAT.value:
                txs = await wallet.generate_signed_transaction(
                    [coin.amount], [new_ph], 0, coins={coin}, ignore_max_send_amount=True
                )
                tx = txs[0]
            else:
                tx = await wallet.generate_signed_transaction(
                    coin.amount, new_ph, 0, coins={coin}, ignore_max_send_amount=True
                )
            await self.wallet_state_manager.add_pending_transaction(tx_record=tx)

        await self.trade_store.set_status(trade_id, TradeStatus.PENDING_CANCEL, False)
        return None

    async def save_trade(self, trade: TradeRecord):
        await self.trade_store.add_trade_record(trade, False)

    async def create_offer_for_ids(
        self, offer: Dict[int, int], file_name: str
    ) -> Tuple[bool, Optional[TradeRecord], Optional[str]]:
        success, trade_offer, error = await self._create_offer_for_ids(offer)

        if success is True and trade_offer is not None:
            self.write_offer_to_disk(Path(file_name), trade_offer)
            await self.save_trade(trade_offer)

        return success, trade_offer, error

    async def _create_offer_for_ids(self, offer: Dict[int, int]) -> Tuple[bool, Optional[TradeRecord], Optional[str]]:
        """
        Offer is dictionary of wallet ids and amount
        """
        spend_bundle = None
        try:
            for id in offer.keys():
                amount = offer[id]
                wallet_id = uint32(int(id))
                wallet = self.wallet_state_manager.wallets[wallet_id]
                if isinstance(wallet, CATWallet):
                    balance = await wallet.get_confirmed_balance()
                    if balance < abs(amount) and amount < 0:
                        raise Exception(f"insufficient funds in wallet {wallet_id}")
                    if amount > 0:
                        if spend_bundle is None:
                            to_exclude: List[Coin] = []
                        else:
                            to_exclude = spend_bundle.removals()
                        zero_spend_bundle: SpendBundle = await wallet.generate_zero_val_coin(  # type: ignore
                            False, to_exclude
                        )

                        if spend_bundle is None:
                            spend_bundle = zero_spend_bundle
                        else:
                            spend_bundle = SpendBundle.aggregate([spend_bundle, zero_spend_bundle])

                        additions = zero_spend_bundle.additions()
                        removals = zero_spend_bundle.removals()
                        zero_val_coin: Optional[Coin] = None
                        for add in additions:
                            if add not in removals and add.amount == 0:
                                zero_val_coin = add
                        new_spend_bundle = await wallet.create_spend_bundle_relative_amount(  # type: ignore
                            amount, zero_val_coin
                        )
                    else:
                        new_spend_bundle = await wallet.create_spend_bundle_relative_amount(amount)  # type: ignore
                elif isinstance(wallet, Wallet):
                    if spend_bundle is None:
                        to_exclude = []
                    else:
                        to_exclude = spend_bundle.removals()
                    new_spend_bundle = await wallet.create_spend_bundle_relative_chia(amount, to_exclude)
                else:
                    return False, None, "unsupported wallet type"
                if new_spend_bundle is None or new_spend_bundle.removals() == []:
                    raise Exception(f"Wallet {id} was unable to create offer.")
                if spend_bundle is None:
                    spend_bundle = new_spend_bundle
                else:
                    spend_bundle = SpendBundle.aggregate([spend_bundle, new_spend_bundle])

            if spend_bundle is None:
                return False, None, None

            now = uint64(int(time.time()))
            trade_offer: TradeRecord = TradeRecord(
                confirmed_at_index=uint32(0),
                accepted_at_time=None,
                created_at_time=now,
                my_offer=True,
                sent=uint32(0),
                spend_bundle=spend_bundle,
                tx_spend_bundle=None,
                additions=spend_bundle.additions(),
                removals=spend_bundle.removals(),
                trade_id=std_hash(spend_bundle.name() + bytes(now)),
                status=uint32(TradeStatus.PENDING_ACCEPT.value),
                sent_to=[],
            )
            return True, trade_offer, None
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Error with creating trade offer: {type(e)}{tb}")
            return False, None, str(e)

    def write_offer_to_disk(self, file_path: Path, offer: TradeRecord):
        if offer is not None:
            file_path.write_text(bytes(offer).hex())

    async def get_discrepancies_for_offer(self, file_path: Path) -> Tuple[bool, Optional[Dict], Optional[Exception]]:
        self.log.info(f"trade offer: {file_path}")
        trade_offer_hex = file_path.read_text()
        trade_offer = TradeRecord.from_bytes(bytes.fromhex(trade_offer_hex))
        return get_discrepancies_for_spend_bundle(trade_offer.spend_bundle)

    async def get_inner_puzzle_for_puzzle_hash(self, puzzle_hash) -> Program:
        info = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(puzzle_hash)
        assert info is not None
        puzzle = self.wallet_state_manager.main_wallet.puzzle_for_pk(bytes(info.pubkey))
        return puzzle

    async def maybe_create_wallets_for_offer(self, file_path: Path) -> bool:
        success, result, error = await self.get_discrepancies_for_offer(file_path)
        if not success or result is None:
            return False

        for key, value in result.items():
            wsm = self.wallet_state_manager
            wallet: Wallet = wsm.main_wallet
            if key == "chia":
                continue
            self.log.info(f"value is {key}")
            exists = await wsm.get_wallet_for_asset_id(key)
            if exists is not None:
                continue

            await CATWallet.create_wallet_for_cat(wsm, wallet, key)

        return True

    async def respond_to_offer(self, file_path: Path) -> Tuple[bool, Optional[TradeRecord], Optional[str]]:
        has_wallets = await self.maybe_create_wallets_for_offer(file_path)
        if not has_wallets:
            return False, None, "Unknown Error"
        trade_offer = None
        try:
            trade_offer_hex = file_path.read_text()
            trade_offer = TradeRecord.from_bytes(hexstr_to_bytes(trade_offer_hex))
        except Exception as e:
            return False, None, f"Error: {e}"
        if trade_offer is not None:
            offer_spend_bundle: SpendBundle = trade_offer.spend_bundle

        coinsols: List[CoinSpend] = []  # [] of CoinSpends
        cat_coinsol_outamounts: Dict[bytes32, List[Tuple[CoinSpend, int]]] = dict()
        aggsig = offer_spend_bundle.aggregated_signature
        cat_discrepancies: Dict[bytes32, int] = dict()
        chia_discrepancy = None
        wallets: Dict[bytes32, Any] = dict()  # asset_id to wallet dict

        for coinsol in offer_spend_bundle.coin_spends:
            puzzle: Program = Program.from_bytes(bytes(coinsol.puzzle_reveal))
            solution: Program = Program.from_bytes(bytes(coinsol.solution))

            # work out the deficits between coin amount and expected output for each
            matched, curried_args = cat_utils.match_cat_puzzle(puzzle)
            if matched:
                # Calculate output amounts
                mod_hash, tail_hash, inner_puzzle = curried_args
                asset_id = bytes(tail_hash).hex()
                if asset_id not in wallets:
                    wallets[asset_id] = await self.wallet_state_manager.get_wallet_for_asset_id(asset_id)
                unspent = await self.wallet_state_manager.get_spendable_coins_for_wallet(wallets[asset_id].id())
                if coinsol.coin in [record.coin for record in unspent]:
                    return False, None, "can't respond to own offer"

                innersol = solution.first()

                total = get_output_amount_for_puzzle_and_solution(inner_puzzle, innersol)
                if asset_id in cat_discrepancies:
                    cat_discrepancies[asset_id] += coinsol.coin.amount - total
                else:
                    cat_discrepancies[asset_id] = coinsol.coin.amount - total
                # Store coinsol and output amount for later
                if asset_id in cat_coinsol_outamounts:
                    cat_coinsol_outamounts[asset_id].append((coinsol, total))
                else:
                    cat_coinsol_outamounts[asset_id] = [(coinsol, total)]

            else:
                # standard chia coin
                unspent = await self.wallet_state_manager.get_spendable_coins_for_wallet(1)
                if coinsol.coin in [record.coin for record in unspent]:
                    return False, None, "can't respond to own offer"
                if chia_discrepancy is None:
                    chia_discrepancy = get_output_discrepancy_for_puzzle_and_solution(coinsol.coin, puzzle, solution)
                else:
                    chia_discrepancy += get_output_discrepancy_for_puzzle_and_solution(coinsol.coin, puzzle, solution)
                coinsols.append(coinsol)

        chia_spend_bundle: Optional[SpendBundle] = None
        if chia_discrepancy is not None:
            chia_spend_bundle = await self.wallet_state_manager.main_wallet.create_spend_bundle_relative_chia(
                chia_discrepancy, []
            )
            if chia_spend_bundle is not None:
                for coinsol in coinsols:
                    chia_spend_bundle.coin_spends.append(coinsol)

        zero_spend_list: List[SpendBundle] = []
        spend_bundle = None
        # create CAT
        self.log.info(cat_discrepancies)
        for asset_id in cat_discrepancies.keys():
            if cat_discrepancies[asset_id] < 0:
                my_cat_spends = await wallets[asset_id].select_coins(abs(cat_discrepancies[asset_id]))
            else:
                if chia_spend_bundle is None:
                    to_exclude: List = []
                else:
                    to_exclude = chia_spend_bundle.removals()
                my_cat_spends = await wallets[asset_id].select_coins(0)
                if my_cat_spends is None or my_cat_spends == set():
                    zero_spend_bundle: SpendBundle = await wallets[asset_id].generate_zero_val_coin(False, to_exclude)
                    if zero_spend_bundle is None:
                        return (
                            False,
                            None,
                            "Unable to generate zero value coin. Confirm that you have chia available",
                        )
                    zero_spend_list.append(zero_spend_bundle)

                    additions = zero_spend_bundle.additions()
                    removals = zero_spend_bundle.removals()
                    my_cat_spends = set()
                    for add in additions:
                        if add not in removals and add.amount == 0:
                            my_cat_spends.add(add)

            if my_cat_spends == set() or my_cat_spends is None:
                return False, None, "insufficient funds"

            # Create SpendableCAT list with both my coins and the offered coins
            # Firstly get the output coin
            my_output_coin = my_cat_spends.pop()
            spendable_cat_list = []
            tail = Program.from_bytes(bytes.fromhex(asset_id))
            # Make the rest of the coins assert the output coin is consumed
            for cat in my_cat_spends:
                inner_solution = self.wallet_state_manager.main_wallet.make_solution(consumed=[my_output_coin.name()])
                inner_puzzle = await self.get_inner_puzzle_for_puzzle_hash(cat.puzzle_hash)
                assert inner_puzzle is not None

                sigs = await wallets[asset_id].get_sigs(inner_puzzle, inner_solution, cat.name())
                sigs.append(aggsig)
                aggsig = AugSchemeMPL.aggregate(sigs)

                lineage_proof = await wallets[asset_id].get_lineage_proof_for_coin(cat)
                spendable_cat_list.append(
                    SpendableCAT(
                        cat,
                        tail.get_tree_hash(),
                        inner_puzzle,
                        inner_solution,
                        lineage_proof=lineage_proof,
                    )
                )

            # Create SpendableCAT for each of the CATs received
            for cat_coinsol_out in cat_coinsol_outamounts[asset_id]:
                cat_coinsol = cat_coinsol_out[0]
                puzzle = Program.from_bytes(bytes(cat_coinsol.puzzle_reveal))
                solution = Program.from_bytes(bytes(cat_coinsol.solution))

                matched, curried_args = match_cat_puzzle(puzzle)
                if matched:
                    mod_hash, tail_hash, inner_puzzle = curried_args
                    spendable_cat_list.append(
                        SpendableCAT(
                            cat_coinsol.coin,
                            tail_hash,
                            inner_puzzle,
                            solution.first(),
                            lineage_proof=solution.rest().rest().first(),
                        )
                    )

            # Finish the output coin SpendableCAT with new information
            newinnerpuzhash = await wallets[asset_id].get_new_inner_hash()
            outputamount = sum([c.amount for c in my_cat_spends]) + cat_discrepancies[asset_id] + my_output_coin.amount
            inner_solution = self.wallet_state_manager.main_wallet.make_solution(
                primaries=[{"puzzlehash": newinnerpuzhash, "amount": outputamount}]
            )
            inner_puzzle = await self.get_inner_puzzle_for_puzzle_hash(my_output_coin.puzzle_hash)
            assert inner_puzzle is not None

            lineage_proof = await wallets[asset_id].get_lineage_proof_for_coin(my_output_coin)
            spendable_cat_list.append(
                SpendableCAT(
                    my_output_coin,
                    tail_hash,
                    inner_puzzle,
                    inner_solution,
                    lineage_proof=lineage_proof,
                )
            )

            sigs = await wallets[asset_id].get_sigs(inner_puzzle, inner_solution, my_output_coin.name())
            sigs.append(aggsig)
            aggsig = AugSchemeMPL.aggregate(sigs)
            if spend_bundle is None:
                spend_bundle = unsigned_spend_bundle_for_spendable_cats(
                    CAT_MOD,
                    spendable_cat_list,
                )
            else:
                new_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
                    CAT_MOD,
                    spendable_cat_list,
                )
                spend_bundle = SpendBundle.aggregate([spend_bundle, new_spend_bundle])
            spend_bundle = SpendBundle.aggregate([spend_bundle, SpendBundle([], aggsig)])  # "Signing" the spend bundle
            # reset sigs and aggsig so that they aren't included next time around
            sigs = []
            aggsig = AugSchemeMPL.aggregate(sigs)
        my_tx_records = []
        if zero_spend_list is not None and spend_bundle is not None:
            zero_spend_list.append(spend_bundle)
            spend_bundle = SpendBundle.aggregate(zero_spend_list)

        if spend_bundle is None:
            return False, None, "spend_bundle missing"

        # Add transaction history for this trade
        now = uint64(int(time.time()))
        if chia_spend_bundle is not None:
            spend_bundle = SpendBundle.aggregate([spend_bundle, chia_spend_bundle])
            if chia_discrepancy < 0:
                tx_record = TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=now,
                    to_puzzle_hash=token_bytes(),
                    amount=uint64(abs(chia_discrepancy)),
                    fee_amount=uint64(0),
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=chia_spend_bundle,
                    additions=chia_spend_bundle.additions(),
                    removals=chia_spend_bundle.removals(),
                    wallet_id=uint32(1),
                    sent_to=[],
                    trade_id=std_hash(spend_bundle.name() + bytes(now)),
                    type=uint32(TransactionType.OUTGOING_TRADE.value),
                    name=chia_spend_bundle.name(),
                    memos=list(chia_spend_bundle.get_memos().items()),
                )
            else:
                tx_record = TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=token_bytes(),
                    amount=uint64(abs(chia_discrepancy)),
                    fee_amount=uint64(0),
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=chia_spend_bundle,
                    additions=chia_spend_bundle.additions(),
                    removals=chia_spend_bundle.removals(),
                    wallet_id=uint32(1),
                    sent_to=[],
                    trade_id=std_hash(spend_bundle.name() + bytes(now)),
                    type=uint32(TransactionType.INCOMING_TRADE.value),
                    name=chia_spend_bundle.name(),
                    memos=list(chia_spend_bundle.get_memos().items()),
                )
            my_tx_records.append(tx_record)

        for asset_id, amount in cat_discrepancies.items():
            wallet = wallets[asset_id]
            if chia_discrepancy > 0:
                tx_record = TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=token_bytes(),
                    amount=uint64(abs(amount)),
                    fee_amount=uint64(0),
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=spend_bundle,
                    additions=spend_bundle.additions(),
                    removals=spend_bundle.removals(),
                    wallet_id=wallet.id(),
                    sent_to=[],
                    trade_id=std_hash(spend_bundle.name() + bytes(now)),
                    type=uint32(TransactionType.OUTGOING_TRADE.value),
                    name=spend_bundle.name(),
                    memos=list(spend_bundle.get_memos().items()),
                )
            else:
                tx_record = TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=token_bytes(),
                    amount=uint64(abs(amount)),
                    fee_amount=uint64(0),
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=spend_bundle,
                    additions=spend_bundle.additions(),
                    removals=spend_bundle.removals(),
                    wallet_id=wallet.id(),
                    sent_to=[],
                    trade_id=std_hash(spend_bundle.name() + bytes(now)),
                    type=uint32(TransactionType.INCOMING_TRADE.value),
                    name=token_bytes(),
                    memos=list(spend_bundle.get_memos().items()),
                )
            my_tx_records.append(tx_record)

        tx_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=token_bytes(),
            amount=uint64(0),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=uint32(0),
            sent_to=[],
            trade_id=std_hash(spend_bundle.name() + bytes(now)),
            type=uint32(TransactionType.OUTGOING_TRADE.value),
            name=spend_bundle.name(),
            memos=list(spend_bundle.get_memos().items()),
        )

        now = uint64(int(time.time()))
        trade_record: TradeRecord = TradeRecord(
            confirmed_at_index=uint32(0),
            accepted_at_time=now,
            created_at_time=now,
            my_offer=False,
            sent=uint32(0),
            spend_bundle=offer_spend_bundle,
            tx_spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            trade_id=std_hash(spend_bundle.name() + bytes(now)),
            status=uint32(TradeStatus.PENDING_CONFIRM.value),
            sent_to=[],
        )

        await self.save_trade(trade_record)
        await self.wallet_state_manager.add_pending_transaction(tx_record)
        for tx in my_tx_records:
            await self.wallet_state_manager.add_transaction(tx)

        return True, trade_record, None
