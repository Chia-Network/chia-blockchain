import time
from pathlib import Path

from typing import Dict, Optional, List, Set, Tuple
import logging
import asyncio
from chiabip158 import PyBIP158

from src.types.hashable.coin import Coin
from src.types.hashable.coin_record import CoinRecord
from src.types.hashable.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.types.challenge import Challenge
from src.consensus.constants import constants as consensus_constants
from src.types.header_block import HeaderBlock
from src.util.ints import uint32, uint64
from src.util.hash import std_hash
from src.wallet.transaction_record import TransactionRecord
from src.wallet.block_record import BlockRecord
from src.wallet.wallet_puzzle_store import WalletPuzzleStore
from src.wallet.wallet_store import WalletStore
from src.wallet.wallet_transaction_store import WalletTransactionStore
from src.full_node.blockchain import ReceiveBlockResult


class WalletStateManager:
    constants: Dict
    key_config: Dict
    config: Dict
    wallet_store: WalletStore
    tx_store: WalletTransactionStore
    puzzle_store: WalletPuzzleStore
    # Map from header hash to BlockRecord
    block_records: Dict[bytes32, BlockRecord]
    # Specifies the LCA path
    height_to_hash: Dict[uint32, bytes32]
    # Header hash of tip (least common ancestor)
    lca: Optional[bytes32]
    start_index: int

    # Makes sure only one asyncio thread is changing the blockchain state at one time
    lock: asyncio.Lock

    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    synced: bool

    @staticmethod
    async def create(
        config: Dict,
        db_path: Path,
        name: str = None,
        override_constants: Optional[Dict] = None,
    ):
        self = WalletStateManager()
        self.config = config
        self.constants = consensus_constants.copy()

        if override_constants:
            for key, value in override_constants.items():
                self.constants[key] = value

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)
        self.lock = asyncio.Lock()

        self.wallet_store = await WalletStore.create(db_path)
        self.tx_store = await WalletTransactionStore.create(db_path)
        self.puzzle_store = await WalletPuzzleStore.create(db_path)
        self.lca = None
        self.synced = False
        self.height_to_hash = {}
        self.block_records = await self.wallet_store.get_lca_path()
        genesis = FullBlock.from_bytes(self.constants["GENESIS_BLOCK"])

        if len(self.block_records) > 0:
            # Header hash with the highest weight
            self.lca = max(
                (item[1].weight, item[0]) for item in self.block_records.items()
            )[1]
            for key, value in self.block_records.items():
                self.height_to_hash[value.height] = value.header_hash

            # Checks genesis block is the same in config, as in DB
            assert self.block_records[genesis.header_hash].height == 0
            assert self.block_records[genesis.header_hash].weight == genesis.weight
        else:
            # Loads the genesis block if there are no blocks
            genesis_challenge = Challenge(
                genesis.proof_of_space.challenge_hash,
                std_hash(
                    genesis.proof_of_space.get_hash()
                    + genesis.proof_of_time.output.get_hash()
                ),
                None,
            )
            genesis_hb = HeaderBlock(
                genesis.proof_of_space,
                genesis.proof_of_time,
                genesis_challenge,
                genesis.header,
            )
            # TODO(mariano): also check coinbase and fees coin
            await self.receive_block(
                BlockRecord(
                    genesis.header_hash,
                    genesis.prev_header_hash,
                    uint32(0),
                    genesis.weight,
                    [],
                    [],
                ),
                genesis_hb,
            )
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
                if await self.puzzle_store.puzzle_hash_exists(coin.puzzle_hash):
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
        total_removed = 0
        total_added = 0
        outgoing_amount = 0

        for add in spend_bundle.additions():
            total_added += add.amount
            add_list.append(add)
        for rem in spend_bundle.removals():
            total_removed += rem.amount
            rem_list.append(rem)

        fee_amount = total_removed - total_added

        # Figure out if we are sending to ourself or someone else.
        to_puzzle_hash: Optional[bytes32] = None
        for add in add_list:
            if not await self.puzzle_store.puzzle_hash_exists(add.puzzle_hash):
                to_puzzle_hash = add.puzzle_hash
                outgoing_amount += add.amount
                break

        # If there is no addition for outside puzzlehash we are sending tx to ourself
        if to_puzzle_hash is None:
            to_puzzle_hash = add_list[0].puzzle_hash
            outgoing_amount += total_added

        tx_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=now,
            to_puzzle_hash=to_puzzle_hash,
            amount=uint64(outgoing_amount),
            fee_amount=uint64(fee_amount),
            incoming=False,
            confirmed=False,
            sent=False,
            spend_bundle=spend_bundle,
            additions=add_list,
            removals=rem_list,
        )
        # Wallet node will use this queue to retry sending this transaction until full nodes receives it
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

    def find_fork_point(self, alternate_chain: List[bytes32]) -> uint32:
        """
        Takes in an alternate blockchain (headers), and compares it to self. Returns the last header
        where both blockchains are equal.
        """
        lca: BlockRecord = self.block_records[self.lca]

        if lca.height >= len(alternate_chain) - 1:
            raise ValueError("Alternate chain is shorter")
        low: uint32 = uint32(0)
        high = lca.height
        while low + 1 < high:
            mid = uint32((low + high) // 2)
            if self.height_to_hash[uint32(mid)] != alternate_chain[mid]:
                high = mid
            else:
                low = mid
        if low == high and low == 0:
            assert self.height_to_hash[uint32(0)] == alternate_chain[0]
            return uint32(0)
        assert low + 1 == high
        if self.height_to_hash[uint32(low)] == alternate_chain[low]:
            if self.height_to_hash[uint32(high)] == alternate_chain[high]:
                return high
            else:
                return low
        elif low > 0:
            assert self.height_to_hash[uint32(low - 1)] == alternate_chain[low - 1]
            return uint32(low - 1)
        else:
            raise ValueError("Invalid genesis block")

    async def receive_block(
        self, block: BlockRecord, header_block: Optional[HeaderBlock] = None,
    ) -> ReceiveBlockResult:
        async with self.lock:
            if block.header_hash in self.block_records:
                return ReceiveBlockResult.ALREADY_HAVE_BLOCK

            if block.prev_header_hash not in self.block_records and block.height != 0:
                return ReceiveBlockResult.DISCONNECTED_BLOCK

            if header_block is not None:
                if not await self.validate_header_block(header_block):
                    return ReceiveBlockResult.INVALID_BLOCK

            self.block_records[block.header_hash] = block
            await self.wallet_store.add_block_record(block, False)

            # Genesis case
            if self.lca is None:
                assert block.height == 0
                await self.wallet_store.add_block_to_path(block.header_hash)
                self.lca = block.header_hash
                for coin in block.additions:
                    await self.coin_added(coin, block.height, False)
                for coin_name in block.removals:
                    await self.coin_removed(coin_name, block.height)
                self.height_to_hash[uint32(0)] = block.header_hash
                return ReceiveBlockResult.ADDED_TO_HEAD

            # Not genesis, updated LCA
            if block.weight > self.block_records[self.lca].weight:

                fork_h = self.find_fork_for_lca(block)
                await self.reorg_rollback(fork_h)

                # Add blocks between fork point and new lca
                fork_hash = self.height_to_hash[fork_h]
                blocks_to_add: List[BlockRecord] = []
                tip_hash: bytes32 = block.header_hash
                while True:
                    if tip_hash == fork_hash:
                        break
                    record = self.block_records[tip_hash]
                    blocks_to_add.append(record)
                    tip_hash = record.prev_header_hash
                blocks_to_add.reverse()

                for path_block in blocks_to_add:
                    self.height_to_hash[path_block.height] = path_block.header_hash
                    await self.wallet_store.add_block_to_path(path_block.header_hash)
                    if header_block is not None:
                        coinbase = header_block.header.data.coinbase
                        fees_coin = header_block.header.data.fees_coin
                        if await self.is_addition_relevant(coinbase):
                            await self.coin_added(coinbase, path_block.height, True)
                        if await self.is_addition_relevant(fees_coin):
                            await self.coin_added(fees_coin, path_block.height, True)
                    for coin in path_block.additions:
                        await self.coin_added(coin, path_block.height, False)
                    for coin_name in path_block.removals:
                        await self.coin_removed(coin_name, path_block.height)
                self.lca = block.header_hash
                return ReceiveBlockResult.ADDED_TO_HEAD

            return ReceiveBlockResult.ADDED_AS_ORPHAN

    async def validate_header_block(self, header_block: HeaderBlock) -> bool:
        # POS challenge hash == POT challenge hash == prev challenge hash == Challenge prev challenge hash
        # Validate PoS and get quality
        # Calculate iters
        # Validate PoT
        # Valudate challenge
        #   - proofs hash is goo
        #   - new work difficulty is good if necessary
        # Validate header:
        #  - header hash and prev header hash match BR
        #  - height and weight match BR
        #  - add
        # TODO(mariano): implement
        return True

    def find_fork_for_lca(self, new_lca: BlockRecord) -> uint32:
        """ Tries to find height where new chain (current) diverged from the old chain where old_lca was the LCA"""
        tmp_old: BlockRecord = self.block_records[self.lca]
        while tmp_old.header_hash != self.height_to_hash[uint32(0)]:
            if tmp_old.header_hash == self.height_to_hash[uint32(0)]:
                return uint32(0)
            if tmp_old.height in self.height_to_hash:
                chain_hash_at_h = self.height_to_hash[tmp_old.height]
                if (
                    chain_hash_at_h == tmp_old.header_hash
                    and chain_hash_at_h != new_lca.header_hash
                ):
                    return tmp_old.height
            tmp_old = self.block_records[tmp_old.prev_header_hash]
        return uint32(0)

    async def get_filter_additions_removals(
        self, transactions_fitler: bytes
    ) -> Tuple[List[bytes32], List[bytes32]]:
        """ Returns a list of our coin ids, and a list of puzzle_hashes that positively match with provided filter. """
        tx_filter = PyBIP158([b for b in transactions_fitler])
        my_coin_records: Set[
            CoinRecord
        ] = await self.wallet_store.get_coin_records_by_spent(False)
        my_puzzle_hashes = await self.puzzle_store.get_all_puzzle_hashes()

        removals_of_interest: bytes32 = []
        additions_of_interest: bytes32 = []

        for record in my_coin_records:
            if tx_filter.Match(bytearray(record.name)):
                removals_of_interest.append(record.name)

        for puzzle_hash in my_puzzle_hashes:
            if tx_filter.Match(bytearray(puzzle_hash)):
                additions_of_interest.append(puzzle_hash)

        return (additions_of_interest, removals_of_interest)

    async def get_relevant_additions(self, additions: List[Coin]) -> List[Coin]:
        """ Returns the list of coins that are relevant to us.(We can spend them) """

        result: List[Coin] = []
        my_puzzle_hashes: Set[bytes32] = await self.puzzle_store.get_all_puzzle_hashes()

        for coin in additions:
            if coin.puzzle_hash in my_puzzle_hashes:
                result.append(coin)

        return result

    async def is_addition_relevant(self, addition: Coin):
        result = await self.puzzle_store.puzzle_hash_exists(addition.puzzle_hash)
        return result

    async def get_relevant_removals(self, removals: List[Coin]) -> List[Coin]:
        """ Returns a list of our unspent coins that are in the passed list. """

        result: List[Coin] = []
        my_coins: Dict[bytes32, Coin] = await self.wallet_store.get_unspent_coins()

        for coin in removals:
            if coin.name() in my_coins:
                result.append(coin)

        return result

    async def reorg_rollback(self, index: uint32):
        """
        Rolls back and updates the coin_store and transaction store. It's possible this height
        is the tip, or even beyond the tip.
        """
        await self.wallet_store.rollback_lca_to_block(index)

        reorged: List[TransactionRecord] = await self.tx_store.get_transaction_above(
            index
        )
        await self.tx_store.rollback_to_block(index)

        await self.retry_sending_after_reorg(reorged)

    async def retry_sending_after_reorg(self, records: List[TransactionRecord]):
        """
        Retries sending spend_bundle to the Full_Node, after confirmed tx
        get's excluded from chain because of the reorg.
        """
        print("Resending...")
        # TODO Straya

    async def close_all_stores(self):
        await self.wallet_store.close()
        await self.tx_store.close()
        await self.puzzle_store.close()

    async def clear_all_stores(self):
        await self.wallet_store._clear_database()
        await self.tx_store._clear_database()
        await self.puzzle_store._clear_database()
