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
from src.types.proof_of_space import ProofOfSpace
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
from src.consensus.pot_iterations import (
    calculate_ips_from_iterations,
    calculate_iterations_quality,
)


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
                    genesis_hb.header.data.timestamp,
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

        valid_index = current_index - coinbase_freeze_period + 3

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

    def get_next_difficulty(self, header_hash: bytes32) -> uint64:
        """
        Returns the difficulty of the next block that extends onto header_hash.
        Used to calculate the number of iterations. Based on the implementation in blockchain.py.
        """
        block: BlockRecord = self.block_records[header_hash]

        next_height: uint32 = uint32(block.height + 1)
        if next_height < self.constants["DIFFICULTY_EPOCH"]:
            # We are in the first epoch
            return uint64(self.constants["DIFFICULTY_STARTING"])

        # Epochs are diffined as intervals of DIFFICULTY_EPOCH blocks, inclusive and indexed at 0.
        # For example, [0-2047], [2048-4095], etc. The difficulty changes DIFFICULTY_DELAY into the
        # epoch, as opposed to the first block (as in Bitcoin).
        elif (
            next_height % self.constants["DIFFICULTY_EPOCH"]
            != self.constants["DIFFICULTY_DELAY"]
        ):
            # Not at a point where difficulty would change
            prev_block: BlockRecord = self.block_records[block.prev_header_hash]
            assert prev_block is not None
            if prev_block is None:
                raise Exception("Previous block is invalid.")
            return uint64(block.weight - prev_block.weight)

        #       old diff                  curr diff       new diff
        # ----------|-----|----------------------|-----|-----...
        #           h1    h2                     h3   i-1
        # Height1 is the last block 2 epochs ago, so we can include the time to mine 1st block in previous epoch
        height1 = uint32(
            next_height
            - self.constants["DIFFICULTY_EPOCH"]
            - self.constants["DIFFICULTY_DELAY"]
            - 1
        )
        # Height2 is the DIFFICULTY DELAYth block in the previous epoch
        height2 = uint32(next_height - self.constants["DIFFICULTY_EPOCH"] - 1)
        # Height3 is the last block in the previous epoch
        height3 = uint32(next_height - self.constants["DIFFICULTY_DELAY"] - 1)

        # h1 to h2 timestamps are mined on previous difficulty, while  and h2 to h3 timestamps are mined on the
        # current difficulty

        block1, block2, block3 = None, None, None
        # Once we are before the fork point (and before the LCA), we can use the height_to_hash map
        if height1 >= 0:
            # height1 could be -1, for the first difficulty calculation
            block1 = self.block_records[self.height_to_hash[height1]]
        block2 = self.block_records[self.height_to_hash[height2]]
        block3 = self.block_records[self.height_to_hash[height3]]

        # Current difficulty parameter (diff of block h = i - 1)
        Tc = self.get_next_difficulty(block.prev_header_hash)

        # Previous difficulty parameter (diff of block h = i - 2048 - 1)
        Tp = self.get_next_difficulty(block2.prev_header_hash)
        timestamp1: uint64
        if block1:
            assert block1.timestamp is not None
            timestamp1 = block1.timestamp  # i - 512 - 1
        else:
            # In the case of height == -1, there is no timestamp here, so assume the genesis block
            # took constants["BLOCK_TIME_TARGET"] seconds to mine.
            genesis = self.block_records[self.height_to_hash[uint32(0)]]
            timestamp1 = genesis.timestamp - self.constants["BLOCK_TIME_TARGET"]
        assert block2.timestamp is not None and block3.timestamp is not None
        timestamp2: uint64 = block2.timestamp  # i - 2048 + 512 - 1
        timestamp3: uint64 = block3.timestamp  # i - 512 - 1

        # Numerator fits in 128 bits, so big int is not necessary
        # We multiply by the denominators here, so we only have one fraction in the end (avoiding floating point)
        term1 = (
            self.constants["DIFFICULTY_DELAY"]
            * Tp
            * (timestamp3 - timestamp2)
            * self.constants["BLOCK_TIME_TARGET"]
        )
        term2 = (
            (self.constants["DIFFICULTY_WARP_FACTOR"] - 1)
            * (self.constants["DIFFICULTY_EPOCH"] - self.constants["DIFFICULTY_DELAY"])
            * Tc
            * (timestamp2 - timestamp1)
            * self.constants["BLOCK_TIME_TARGET"]
        )

        # Round down after the division
        new_difficulty: uint64 = uint64(
            (term1 + term2)
            // (
                self.constants["DIFFICULTY_WARP_FACTOR"]
                * (timestamp3 - timestamp2)
                * (timestamp2 - timestamp1)
            )
        )

        # Only change by a max factor, to prevent attacks, as in greenpaper, and must be at least 1
        if new_difficulty >= Tc:
            return min(new_difficulty, uint64(self.constants["DIFFICULTY_FACTOR"] * Tc))
        else:
            return max(
                [
                    uint64(1),
                    new_difficulty,
                    uint64(Tc // self.constants["DIFFICULTY_FACTOR"]),
                ]
            )

    def get_next_ips(
        self, block: BlockRecord, proof_of_space: ProofOfSpace, iterations: uint64
    ) -> uint64:
        """
        Returns the VDF speed in iterations per seconds, to be used for the next block. This depends on
        the number of iterations of the last epoch, and changes at the same block as the difficulty.
        Based on the implementation in blockchain.py.
        """
        next_height: uint32 = uint32(block.height + 1)
        if next_height < self.constants["DIFFICULTY_EPOCH"]:
            # First epoch has a hardcoded vdf speed
            return self.constants["VDF_IPS_STARTING"]

        prev_block: BlockRecord = self.block_records[block.prev_header_hash]

        difficulty = self.get_next_difficulty(prev_block.header_hash)
        prev_ips = calculate_ips_from_iterations(
            proof_of_space, difficulty, iterations, self.constants["MIN_BLOCK_TIME"]
        )

        if (
            next_height % self.constants["DIFFICULTY_EPOCH"]
            != self.constants["DIFFICULTY_DELAY"]
        ):
            # Not at a point where ips would change, so return the previous ips
            # TODO: cache this for efficiency
            return prev_ips

        # ips (along with difficulty) will change in this block, so we need to calculate the new one.
        # The calculation is (iters_2 - iters_1) // (timestamp_2 - timestamp_1).
        # 1 and 2 correspond to height_1 and height_2, being the last block of the second to last, and last
        # block of the last epochs. Basically, it's total iterations over time, of previous epoch.

        # Height1 is the last block 2 epochs ago, so we can include the iterations taken for mining first block in epoch
        height1 = uint32(
            next_height
            - self.constants["DIFFICULTY_EPOCH"]
            - self.constants["DIFFICULTY_DELAY"]
            - 1
        )
        # Height2 is the last block in the previous epoch
        height2 = uint32(next_height - self.constants["DIFFICULTY_DELAY"] - 1)

        block1: Optional[BlockRecord] = None
        block2: Optional[BlockRecord] = None
        # Once we are before the fork point (and before the LCA), we can use the height_to_hash map
        if block1 is None and height1 >= 0:
            # height1 could be -1, for the first difficulty calculation
            block1 = self.block_records[self.height_to_hash[height1]]
        block2 = self.block_records[self.height_to_hash[height2]]
        assert block2 is not None

        if block1 is not None:
            timestamp1 = block1.timestamp
            iters1 = block1.total_iters
        else:
            # In the case of height == -1, there is no timestamp here, so assume the genesis block
            # took constants["BLOCK_TIME_TARGET"] seconds to mine.
            genesis: BlockRecord = self.block_records[self.height_to_hash[uint32(0)]]
            timestamp1 = genesis.timestamp - self.constants["BLOCK_TIME_TARGET"]
            iters1 = genesis.total_iters

        timestamp2 = block2.timestamp
        iters2 = block2.total_iters
        assert iters1 is not None and iters2 is not None
        assert timestamp1 is not None and timestamp2 is not None

        new_ips = uint64((iters2 - iters1) // (timestamp2 - timestamp1))

        # Only change by a max factor, and must be at least 1
        if new_ips >= prev_ips:
            return min(new_ips, uint64(self.constants["IPS_FACTOR"] * new_ips))
        else:
            return max(
                [uint64(1), new_ips, uint64(prev_ips // self.constants["IPS_FACTOR"])]
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

        # Calculate iters
        difficulty: uint64
        ips: uint64
        prev_block: Optional[BlockRecord]
        if br.height > 0:
            prev_block = self.block_records[br.prev_header_hash]
            difficulty = self.get_next_difficulty(br.prev_header_hash)
            assert prev_block is not None
            ips = self.get_next_ips(
                prev_block,
                header_block.proof_of_space,
                header_block.proof_of_time.number_of_iterations,
            )
        else:
            difficulty = uint64(self.constants["DIFFICULTY_STARTING"])
            ips = uint64(self.constants["VDF_IPS_STARTING"])

        number_of_iters: uint64 = calculate_iterations_quality(
            quality_str,
            header_block.proof_of_space.size,
            difficulty,
            ips,
            self.constants["MIN_BLOCK_TIME"],
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
