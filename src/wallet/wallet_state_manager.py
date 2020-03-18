import time
from pathlib import Path

from typing import Dict, Optional, List, Set, Tuple, Callable
import logging
import asyncio
from chiabip158 import PyBIP158

from src.types.hashable.coin import Coin
from src.types.hashable.coin_record import CoinRecord
from src.types.hashable.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.types.challenge import Challenge
from src.types.header_block import HeaderBlock
from src.util.ints import uint32, uint64
from src.util.hash import std_hash
from src.wallet.transaction_record import TransactionRecord
from src.wallet.block_record import BlockRecord
from src.wallet.wallet_puzzle_store import WalletPuzzleStore
from src.wallet.wallet_store import WalletStore
from src.wallet.wallet_transaction_store import WalletTransactionStore
from src.consensus.block_rewards import calculate_block_reward
from src.full_node.blockchain import ReceiveBlockResult
from src.consensus.pot_iterations import calculate_iterations_quality
from src.util.significant_bits import truncate_to_significant_bits


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
    sync_mode: bool
    genesis: FullBlock

    state_changed_callback: Optional[Callable]

    @staticmethod
    async def create(
        config: Dict, db_path: Path, constants: Dict, name: str = None,
    ):
        self = WalletStateManager()
        self.config = config
        self.constants = constants

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)
        self.lock = asyncio.Lock()

        self.wallet_store = await WalletStore.create(db_path)
        self.tx_store = await WalletTransactionStore.create(db_path)
        self.puzzle_store = await WalletPuzzleStore.create(db_path)
        self.lca = None
        self.sync_mode = False
        self.height_to_hash = {}
        self.block_records = await self.wallet_store.get_lca_path()
        genesis = FullBlock.from_bytes(self.constants["GENESIS_BLOCK"])
        self.genesis = genesis
        self.state_changed_callback = None

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
            await self.receive_block(
                BlockRecord(
                    genesis.header_hash,
                    genesis.prev_header_hash,
                    uint32(0),
                    genesis.weight,
                    [],
                    [],
                    genesis_hb.header.data.total_iters,
                    genesis_challenge.get_hash(),
                ),
                genesis_hb,
            )
        return self

    def set_callback(self, callback: Callable):
        self.state_changed_callback = callback

    def state_changed(self, state: str):
        if self.state_changed_callback is None:
            return
        self.state_changed_callback(state)

    def set_sync_mode(self, mode: bool):
        self.sync_mode = mode
        self.state_changed("sync_changed")

    async def get_confirmed_spendable(self, current_index: uint32) -> uint64:
        """
        Returns the balance amount of all coins that are spendable.
        Spendable - (Coinbase freeze period has passed.)
        """
        coinbase_freeze_period = self.constants["COINBASE_FREEZE_PERIOD"]
        if current_index <= coinbase_freeze_period:
            return uint64(0)

        valid_index = current_index - coinbase_freeze_period

        record_list: Set[
            CoinRecord
        ] = await self.wallet_store.get_coin_records_by_spent_and_index(
            False, valid_index
        )

        amount: uint64 = uint64(0)

        for record in record_list:
            amount = uint64(amount + record.coin.amount)

        return uint64(amount)

    async def get_unconfirmed_spendable(self, current_index: uint32) -> uint64:
        """
        Returns the confirmed balance amount - sum of unconfirmed transactions.
        """

        confirmed = await self.get_confirmed_spendable(current_index)
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
        """ Returns a set of coins that can be used for generating a new transaction. """
        if self.lca is None:
            return None

        current_index = self.block_records[self.lca].height
        if amount > await self.get_unconfirmed_spendable(current_index):
            return None

        unspent: Set[CoinRecord] = await self.wallet_store.get_coin_records_by_spent(
            False
        )
        sum = 0
        used_coins: Set = set()

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals = await self.unconfirmed_removals()
        for coinrecord in unspent:
            if sum >= amount:
                break
            if coinrecord.coin.name() in unconfirmed_removals:
                continue
            sum += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)

        # This happens when we couldn't use one of the coins because it's already used
        # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
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
            # This shouldn't happen because of: if amount > self.get_unconfirmed_balance_spendable():
            return None

    async def coin_removed(self, coin_name: bytes32, index: uint32):
        """
        Called when coin gets spent
        """
        await self.wallet_store.set_spent(coin_name, index)

        unconfirmed_record = await self.tx_store.unconfirmed_with_removal_coin(
            coin_name
        )
        if unconfirmed_record:
            await self.tx_store.set_confirmed(unconfirmed_record.name(), index)

        self.state_changed("coin_removed")

    async def coin_added(self, coin: Coin, index: uint32, coinbase: bool):
        """
        Adding coin to the db
        """
        if coinbase:
            now = uint64(int(time.time()))
            tx_record = TransactionRecord(
                confirmed_at_index=uint32(index),
                created_at_time=now,
                to_puzzle_hash=coin.puzzle_hash,
                amount=coin.amount,
                fee_amount=uint64(0),
                incoming=True,
                confirmed=True,
                sent=True,
                spend_bundle=None,
                additions=[coin],
                removals=[],
            )
            await self.tx_store.add_transaction_record(tx_record)
        else:
            unconfirmed_record = await self.tx_store.unconfirmed_with_addition_coin(
                coin.name()
            )

            if unconfirmed_record:
                # This is the change from this transaction
                await self.tx_store.set_confirmed(unconfirmed_record.name(), index)
            else:
                now = uint64(int(time.time()))
                tx_record = TransactionRecord(
                    confirmed_at_index=uint32(index),
                    created_at_time=now,
                    to_puzzle_hash=coin.puzzle_hash,
                    amount=coin.amount,
                    fee_amount=uint64(0),
                    incoming=True,
                    confirmed=True,
                    sent=True,
                    spend_bundle=None,
                    additions=[coin],
                    removals=[],
                )
                await self.tx_store.add_transaction_record(tx_record)

        coin_record: CoinRecord = CoinRecord(coin, index, uint32(0), False, coinbase)
        await self.wallet_store.add_coin_record(coin_record)
        self.state_changed("coin_added")

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
        self.state_changed("pending_transaction")

    async def remove_from_queue(self, spendbundle_id: bytes32):
        """
        Full node received our transaction, no need to keep it in queue anymore
        """
        await self.tx_store.set_sent(spendbundle_id)
        self.state_changed("tx_sent")

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
                if not await self.validate_header_block(block, header_block):
                    return ReceiveBlockResult.INVALID_BLOCK

            if block.height % self.constants["DIFFICULTY_EPOCH"] == 0:
                assert block.total_iters is not None

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
                    if tip_hash == fork_hash or tip_hash == self.genesis.header_hash:
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
                self.state_changed("new_block")
                return ReceiveBlockResult.ADDED_TO_HEAD

            return ReceiveBlockResult.ADDED_AS_ORPHAN

    def get_min_iters(self, block_record: BlockRecord) -> uint64:
        curr = block_record
        if (
            curr.height
            < self.constants["DIFFICULTY_EPOCH"] + self.constants["DIFFICULTY_DELAY"]
        ):
            return self.constants["MIN_ITERS_STARTING"]
        if (
            curr.height % self.constants["DIFFICULTY_EPOCH"]
            < self.constants["DIFFICULTY_DELAY"]
        ):
            # First few blocks of epoch (using old difficulty and min_iters)
            height2 = (
                curr.height
                - (curr.height % self.constants["DIFFICULTY_EPOCH"])
                - self.constants["DIFFICULTY_EPOCH"]
                - 1
            )
        else:
            # The rest of the blocks of epoch (using new difficulty and min iters)
            height2 = (
                curr.height - (curr.height % self.constants["DIFFICULTY_EPOCH"]) - 1
            )
        height1 = height2 - self.constants["DIFFICULTY_EPOCH"]
        assert height2 > 0

        iters1: Optional[uint64] = uint64(0)
        iters2: Optional[uint64] = None
        while curr.height > height1 and curr.height > 0:
            if curr.height == height2:
                iters2 = curr.total_iters
            curr = self.block_records[curr.prev_header_hash]
        if height1 > -1:  # For height of -1, total iters is 0
            iters1 = curr.total_iters
        assert iters1 is not None
        assert iters2 is not None
        return uint64(
            (iters2 - iters1)
            // (
                self.constants["DIFFICULTY_EPOCH"]
                * self.constants["MIN_ITERS_PROPORTION"]
            )
        )

    async def validate_header_block(
        self, br: BlockRecord, header_block: HeaderBlock
    ) -> bool:
        # POS challenge hash == POT challenge hash == Challenge prev challenge hash
        if (
            header_block.proof_of_space.challenge_hash
            != header_block.proof_of_time.challenge_hash
        ):
            return False
        if (
            header_block.proof_of_space.challenge_hash
            != header_block.challenge.prev_challenge_hash
        ):
            return False

        if br.height > 0:
            prev_br = self.block_records[br.prev_header_hash]
            # If prev header block, check prev header block hash matchs
            if prev_br.new_challenge_hash is not None:
                if (
                    header_block.proof_of_space.challenge_hash
                    != prev_br.new_challenge_hash
                ):
                    return False

        # Validate PoS and get quality
        quality_str: Optional[
            bytes32
        ] = header_block.proof_of_space.verify_and_get_quality_string()
        if quality_str is None:
            return False

        difficulty: uint64
        min_iters: uint64 = self.get_min_iters(br)
        prev_block: Optional[BlockRecord]
        if (
            br.height % self.constants["DIFFICULTY_EPOCH"]
            != self.constants["DIFFICULTY_DELAY"]
        ):
            # Only allow difficulty changes once per epoch
            if br.height > 1:
                prev_block = self.block_records[br.prev_header_hash]
                assert prev_block is not None
                prev_prev_block = self.block_records[prev_block.prev_header_hash]
                assert prev_prev_block is not None
                difficulty = uint64(br.weight - prev_block.weight)
                assert difficulty == prev_block.weight - prev_prev_block.weight
            elif br.height == 1:
                prev_block = self.block_records[br.prev_header_hash]
                assert prev_block is not None
                difficulty = uint64(br.weight - prev_block.weight)
                assert difficulty == prev_block.weight
            else:
                difficulty = uint64(br.weight)
                assert difficulty == self.constants["DIFFICULTY_STARTING"]
        else:
            # This is a difficulty change, so check whether it's within the allowed range.
            # (But don't check whether it's the right amount).
            prev_block = self.block_records[br.prev_header_hash]
            assert prev_block is not None
            prev_prev_block = self.block_records[prev_block.prev_header_hash]
            assert prev_prev_block is not None
            difficulty = uint64(br.weight - prev_block.weight)
            prev_difficulty = uint64(prev_block.weight - prev_prev_block.weight)
            max_diff = uint64(
                truncate_to_significant_bits(
                    prev_difficulty * self.constants["DIFFICULTY_FACTOR"],
                    self.constants["SIGNIFICANT_BITS"],
                )
            )
            min_diff = uint64(
                truncate_to_significant_bits(
                    prev_difficulty // self.constants["DIFFICULTY_FACTOR"],
                    self.constants["SIGNIFICANT_BITS"],
                )
            )

            if difficulty < min_diff or difficulty > max_diff:
                return False

        number_of_iters: uint64 = calculate_iterations_quality(
            quality_str, header_block.proof_of_space.size, difficulty, min_iters,
        )

        if header_block.proof_of_time is None:
            return False

        if number_of_iters != header_block.proof_of_time.number_of_iterations:
            return False

        # Check PoT
        if not header_block.proof_of_time.is_valid(
            self.constants["DISCRIMINANT_SIZE_BITS"]
        ):
            return False

        # Validate challenge
        proofs_hash = std_hash(
            header_block.proof_of_space.get_hash()
            + header_block.proof_of_time.output.get_hash()
        )
        if proofs_hash != header_block.challenge.proofs_hash:
            return False

        if header_block.challenge.new_work_difficulty is not None:
            if header_block.challenge.new_work_difficulty != difficulty:
                return False

        # Validate header:
        if header_block.header.header_hash != br.header_hash:
            return False
        if header_block.header.prev_header_hash != br.prev_header_hash:
            return False
        if header_block.height != br.height:
            return False
        if header_block.weight != br.weight:
            return False
        if br.height > 0:
            assert prev_block is not None
            if prev_block.weight + difficulty != br.weight:
                return False
            if prev_block.total_iters is not None and br.total_iters is not None:
                if prev_block.total_iters + number_of_iters != br.total_iters:
                    return False
            if prev_block.height + 1 != br.height:
                return False
        else:
            if br.weight != difficulty:
                return False
            if br.total_iters != number_of_iters:
                return False

        # Check that block is not far in the future
        if (
            header_block.header.data.timestamp
            > time.time() + self.constants["MAX_FUTURE_TIME"]
        ):
            return False

        # Check header pos hash
        if (
            header_block.proof_of_space.get_hash()
            != header_block.header.data.proof_of_space_hash
        ):
            return False

        # Check coinbase sig
        pair = header_block.header.data.coinbase_signature.PkMessagePair(
            header_block.proof_of_space.pool_pubkey,
            header_block.header.data.coinbase.name(),
        )

        if not header_block.header.data.coinbase_signature.validate([pair]):
            return False

        # Check coinbase and fees amount
        coinbase_reward = calculate_block_reward(br.height)
        if coinbase_reward != header_block.header.data.coinbase.amount:
            return False
        return True

    def find_fork_for_lca(self, new_lca: BlockRecord) -> uint32:
        """ Tries to find height where new chain (current) diverged from the old chain where old_lca was the LCA"""
        tmp_old: BlockRecord = self.block_records[self.lca]
        while new_lca.height > 0 or tmp_old.height > 0:
            if new_lca.height > tmp_old.height:
                new_lca = self.block_records[new_lca.prev_header_hash]
            elif tmp_old.height > new_lca.height:
                tmp_old = self.block_records[tmp_old.prev_header_hash]
            else:
                if new_lca.header_hash == tmp_old.header_hash:
                    return new_lca.height
                new_lca = self.block_records[new_lca.prev_header_hash]
                tmp_old = self.block_records[tmp_old.prev_header_hash]
        assert new_lca == tmp_old  # Genesis block is the same, genesis fork
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
