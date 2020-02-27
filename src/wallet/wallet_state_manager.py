import time
from typing import Dict, Optional, List, Set
import logging
from src.types.hashable.coin import Coin
from src.types.hashable.coin_record import CoinRecord
from src.types.hashable.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.wallet.transaction_record import TransactionRecord
from src.wallet.wallet_store import WalletStore
from src.wallet.wallet_transaction_store import WalletTransactionStore


class WalletStateManager:
    key_config: Dict
    config: Dict
    wallet_store: WalletStore
    tx_store: WalletTransactionStore
    header_hash: List[bytes32]
    start_index: int
    next_address: int

    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    synced: bool
    puzzlehash_set: set

    @staticmethod
    async def create(
        config: Dict,
        key_config: Dict,
        wallet_store: WalletStore,
        tx_store: WalletTransactionStore,
        name: str = None,
    ):
        self = WalletStateManager()
        self.config = config

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.header_hash = []
        self.wallet_store = wallet_store
        self.tx_store = tx_store
        self.synced = False
        self.next_address = 0

        self.puzzlehash_set = set()
        return self

    async def get_confirmed_balance(self) -> uint64:
        record_list: Set[
            CoinRecord
        ] = await self.wallet_store.get_coin_records_by_spent(False)
        amount: uint64 = uint64(0)

        for record in record_list:
            amount = uint64(amount + record.coin.amount)

        return uint64(amount)

    async def get_unconfirmed_balance(self) -> uint64:
        confirmed = await self.get_confirmed_balance()
        unconfirmed_tx = await self.tx_store.get_not_confirmed()
        addition_amount = 0
        removal_amount = 0

        for record in unconfirmed_tx:
            for coin in record.additions:
                if coin.puzzle_hash in self.puzzlehash_set:
                    addition_amount += coin.amount
            for coin in record.removals:
                removal_amount += coin.amount

        result = confirmed - removal_amount + addition_amount
        return uint64(result)

    async def unconfirmed_additions(self) -> Dict[bytes32, Coin]:
        additions: Dict[bytes32, Coin] = {}
        unconfirmed_tx = await self.tx_store.get_not_confirmed()
        for record in unconfirmed_tx:
            for coin in record.additions:
                additions[coin.name()] = coin
        return additions

    async def unconfirmed_removals(self) -> Dict[bytes32, Coin]:
        removals: Dict[bytes32, Coin] = {}
        unconfirmed_tx = await self.tx_store.get_not_confirmed()
        for record in unconfirmed_tx:
            for coin in record.removals:
                removals[coin.name()] = coin
        return removals

    async def select_coins(self, amount) -> Optional[Set[Coin]]:

        if amount > await self.get_unconfirmed_balance():
            return None

        unspent: Set[CoinRecord] = await self.wallet_store.get_coin_records_by_spent(
            False
        )
        sum = 0
        used_coins: Set = set()

        """
        Try to use coins from the store, if there isn't enough of "unused"
        coins use change coins that are not confirmed yet
        """
        for coinrecord in unspent:
            if sum >= amount:
                break
            if coinrecord.coin.name in await self.unconfirmed_removals():
                continue
            sum += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)

        """
        This happens when we couldn't use one of the coins because it's already used
        but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
        """
        if sum < amount:
            for coin in (await self.unconfirmed_additions()).values():
                if sum > amount:
                    break
                if coin.name in (await self.unconfirmed_removals()).values():
                    continue
                sum += coin.amount
                used_coins.add(coin)

        if sum >= amount:
            return used_coins
        else:
            # This shouldn't happen because of: if amount > self.get_unconfirmed_balance():
            return None

    async def coin_removed(self, coin_name: bytes32, index: uint32):
        """
        Called when coin gets spent
        """
        await self.wallet_store.set_spent(coin_name, index)

    async def coin_added(self, coin: Coin, index: uint32, coinbase: bool):
        """
        Adding coin to the db
        """
        coin_record: CoinRecord = CoinRecord(coin, index, uint32(0), False, coinbase)
        await self.wallet_store.add_coin_record(coin_record)

    async def add_pending_transaction(self, spend_bundle: SpendBundle):
        """
        Called from wallet_node before new transaction is sent to the full_node
        """
        now = uint64(int(time.time()))
        add_list: List[Coin] = []
        rem_list: List[Coin] = []
        for add in spend_bundle.additions():
            add_list.append(add)
        for rem in spend_bundle.removals():
            rem_list.append(rem)

        # Wallet node will use this queue to retry sending this transaction until full nodes receives it
        tx_record = TransactionRecord(
            uint32(0), uint32(0), False, False, now, spend_bundle, add_list, rem_list
        )
        await self.tx_store.add_transaction_record(tx_record)

    async def remove_from_queue(self, spendbundle_id: bytes32):
        """
        Full node received our transaction, no need to keep it in queue anymore
        """
        await self.tx_store.set_sent(spendbundle_id)

    async def get_send_queue(self) -> List[TransactionRecord]:
        """
        Wallet Node uses this to retry sending transactions
        """
        records = await self.tx_store.get_not_sent()
        return records

    async def get_all_transactions(self) -> List[TransactionRecord]:
        """
        Retrieves all confirmed and pending transactions
        """
        records = await self.tx_store.get_all_transactions()
        return records
