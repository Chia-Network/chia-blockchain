import asyncio
import collections
import logging
from enum import Enum
import multiprocessing
import concurrent
from typing import Dict, List, Optional, Set, Tuple

from chiabip158 import PyBIP158
from clvm.casts import int_from_bytes

from src.consensus.constants import constants as consensus_constants
from src.consensus.block_rewards import calculate_base_fee
from src.full_node.block_header_validation import (
    validate_unfinished_block_header,
    validate_finished_block_header,
    pre_validate_finished_block_header,
)
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.full_node.difficulty_adjustment import get_next_difficulty, get_next_min_iters
from src.types.challenge import Challenge
from src.types.coin import Coin, hash_coin_list
from src.types.coin_record import CoinRecord
from src.types.condition_opcodes import ConditionOpcode
from src.types.condition_var_pair import ConditionVarPair
from src.types.full_block import FullBlock, additions_for_npc
from src.types.header import Header
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.blockchain_check_conditions import blockchain_check_conditions_dict
from src.util.condition_tools import hash_key_pairs_for_conditions_dict
from src.util.cost_calculator import calculate_cost_of_program
from src.util.errors import ConsensusError, Err
from src.util.hash import std_hash
from src.util.ints import uint32, uint64
from src.util.merkle_set import MerkleSet

log = logging.getLogger(__name__)


class ReceiveBlockResult(Enum):
    """
    When Blockchain.receive_block(b) is called, one of these results is returned,
    showing whether the block was added to the chain (extending a head or not),
    and if not, why it was not added.
    """

    ADDED_TO_HEAD = 1  # Added to one of the heads, this block is now a new head
    ADDED_AS_ORPHAN = 2  # Added as an orphan/stale block (block that is not a head or ancestor of a head)
    INVALID_BLOCK = 3  # Block was not added because it was invalid
    ALREADY_HAVE_BLOCK = 4  # Block is already present in this blockchain
    DISCONNECTED_BLOCK = (
        5  # Block's parent (previous pointer) is not in this blockchain
    )


class Blockchain:
    # Allow passing in custom overrides for any consesus parameters
    constants: Dict
    # Tips of the blockchain
    tips: List[Header]
    # Least common ancestor of tips
    lca_block: Header
    # Defines the path from genesis to the lca
    height_to_hash: Dict[uint32, bytes32]
    # All headers (but not orphans) from genesis to the tip are guaranteed to be in headers
    headers: Dict[bytes32, Header]
    # Genesis block
    genesis: FullBlock
    # Unspent Store
    coin_store: CoinStore
    # Store
    block_store: BlockStore
    # Coinbase freeze period
    coinbase_freeze: uint32
    # Used to verify blocks in parallel
    pool: concurrent.futures.ProcessPoolExecutor

    # Whether blockchain is shut down or not
    _shut_down: bool

    # Lock to prevent simultaneous reads and writes
    lock: asyncio.Lock

    @staticmethod
    async def create(
        coin_store: CoinStore, block_store: BlockStore, override_constants: Dict = {},
    ):
        """
        Initializes a blockchain with the header blocks from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = Blockchain()
        self.lock = asyncio.Lock()  # External lock handled by full node
        cpu_count = multiprocessing.cpu_count()
        self.pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=max(cpu_count - 1, 1)
        )
        self.constants = consensus_constants.copy()
        for key, value in override_constants.items():
            self.constants[key] = value
        self.tips = []
        self.height_to_hash = {}
        self.headers = {}
        self.coin_store = coin_store
        self.block_store = block_store
        self._shut_down = False
        self.genesis = FullBlock.from_bytes(self.constants["GENESIS_BLOCK"])
        self.coinbase_freeze = self.constants["COINBASE_FREEZE_PERIOD"]
        await self._load_chain_from_store()
        return self

    def shut_down(self):
        self._shut_down = True
        self.pool.shutdown(wait=True)

    async def _load_chain_from_store(self,) -> None:
        """
        Initializes the state of the Blockchain class from the database. Sets the LCA, tips,
        headers, height_to_hash, and block_store DiffStores.
        """
        lca_db: Optional[Header] = await self.block_store.get_lca()
        tips_db: List[Header] = await self.block_store.get_tips()
        headers_db: Dict[bytes32, Header] = await self.block_store.get_headers()

        assert (lca_db is None) == (len(tips_db) == 0) == (len(headers_db) == 0)
        if lca_db is None:
            result, removed, error_code = await self.receive_block(
                self.genesis, sync_mode=False
            )
            if result != ReceiveBlockResult.ADDED_TO_HEAD:
                if error_code is not None:
                    raise ConsensusError(error_code)
                else:
                    raise RuntimeError(f"Invalid genesis block {self.genesis}")
            return

        await self.block_store.init_challenge_hashes()

        # Set the state (lca block and tips)
        self.lca_block = lca_db
        self.tips = tips_db

        # Find the common ancestor of the tips, and add intermediate blocks to headers
        cur: List[Header] = self.tips[:]
        while any(b.header_hash != cur[0].header_hash for b in cur):
            heights = [b.height for b in cur]
            i = heights.index(max(heights))
            self.headers[cur[i].header_hash] = cur[i]
            prev: Header = headers_db[cur[i].prev_header_hash]
            challenge_hash = self.block_store.get_challenge_hash(cur[i].header_hash)
            self.block_store.add_proof_of_time(
                challenge_hash,
                uint64(cur[i].data.total_iters - prev.data.total_iters),
                cur[i].data.height,
            )
            cur[i] = prev

        # Consistency check, tips should have an LCA equal to the DB LCA
        assert cur[0] == self.lca_block

        # Sets the header for remaining blocks, and height_to_hash dict
        cur_b: Header = self.lca_block
        while True:
            self.headers[cur_b.header_hash] = cur_b
            self.height_to_hash[cur_b.height] = cur_b.header_hash
            if cur_b.height == 0:
                break
            prev_b: Header = headers_db[cur_b.prev_header_hash]
            challenge_hash = self.block_store.get_challenge_hash(cur_b.header_hash)
            self.block_store.add_proof_of_time(
                challenge_hash,
                uint64(cur_b.data.total_iters - prev_b.data.total_iters),
                cur_b.data.height,
            )
            cur_b = prev_b

        # Asserts that the DB genesis block is correct
        assert cur_b == self.genesis.header

        # Adds the blocks to the db between LCA and tip
        await self.recreate_diff_stores()

    def get_current_tips(self) -> List[Header]:
        """
        Return the heads.
        """
        return self.tips[:]

    async def get_full_tips(self) -> List[FullBlock]:
        """ Return list of FullBlocks that are tips"""
        result: List[FullBlock] = []
        for tip in self.tips:
            block = await self.block_store.get_block(tip.header_hash)
            if not block:
                continue
            result.append(block)
        return result

    def is_child_of_head(self, block: FullBlock) -> bool:
        """
        True iff the block is the direct ancestor of a head.
        """
        for head in self.tips:
            if block.prev_header_hash == head.header_hash:
                return True
        return False

    def contains_block(self, header_hash: bytes32) -> bool:
        return header_hash in self.headers

    def get_challenge(self, block: FullBlock) -> Optional[Challenge]:
        if block.proof_of_time is None:
            return None
        if block.prev_header_hash not in self.headers and block.height > 0:
            return None

        prev_challenge_hash = block.proof_of_space.challenge_hash

        new_difficulty: Optional[uint64]
        if (block.height + 1) % self.constants["DIFFICULTY_EPOCH"] == self.constants[
            "DIFFICULTY_DELAY"
        ]:
            new_difficulty = get_next_difficulty(
                self.constants, self.headers, self.height_to_hash, block.header
            )
        else:
            new_difficulty = None
        return Challenge(
            prev_challenge_hash,
            std_hash(
                block.proof_of_space.get_hash() + block.proof_of_time.output.get_hash()
            ),
            new_difficulty,
        )

    def get_header_block(self, block: FullBlock) -> Optional[HeaderBlock]:
        challenge: Optional[Challenge] = self.get_challenge(block)
        if challenge is None or block.proof_of_time is None:
            return None
        return HeaderBlock(
            block.proof_of_space, block.proof_of_time, challenge, block.header
        )

    def get_header_hashes(self, tip_header_hash: bytes32) -> List[bytes32]:
        if tip_header_hash not in self.headers:
            raise ValueError("Invalid tip requested")

        curr = self.headers[tip_header_hash]
        ret_hashes = [tip_header_hash]
        while curr.height != 0:
            curr = self.headers[curr.prev_header_hash]
            ret_hashes.append(curr.header_hash)
        return list(reversed(ret_hashes))

    def find_fork_point_alternate_chain(self, alternate_chain: List[bytes32]) -> uint32:
        """
        Takes in an alternate blockchain (headers), and compares it to self. Returns the last header
        where both blockchains are equal.
        """
        lca: Header = self.lca_block

        if lca.height >= len(alternate_chain) - 1:
            raise ValueError("Alternate chain is shorter")
        low: uint32 = uint32(0)
        high = lca.height
        while low + 1 < high:
            mid = (low + high) // 2
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
        self,
        block: FullBlock,
        pre_validated: bool = False,
        pos_quality_string: bytes32 = None,
        sync_mode: bool = False,
    ) -> Tuple[ReceiveBlockResult, Optional[Header], Optional[Err]]:
        """
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid.
        """
        genesis: bool = block.height == 0 and not self.tips

        if block.header_hash in self.headers:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None, None

        if block.prev_header_hash not in self.headers and not genesis:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None, None

        prev_header_block: Optional[HeaderBlock] = None
        if not genesis:
            prev_full_block = await self.block_store.get_block(block.prev_header_hash)
            assert prev_full_block is not None
            prev_header_block = self.get_header_block(prev_full_block)
            assert prev_header_block is not None

        curr_header_block = self.get_header_block(block)
        assert curr_header_block is not None
        # Validate block header
        error_code: Optional[Err] = await validate_finished_block_header(
            self.constants,
            self.headers,
            self.height_to_hash,
            curr_header_block,
            prev_header_block,
            genesis,
            pre_validated,
            pos_quality_string,
        )

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, None, error_code

        # Validate block body
        error_code = await self.validate_block_body(block)

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, None, error_code

        # Cache header in memory
        self.headers[block.header_hash] = block.header

        # Always immediately add the block to the database, after updating blockchain state
        await self.block_store.add_block(block)
        assert block.proof_of_time is not None
        self.block_store.add_proof_of_time(
            block.proof_of_time.challenge_hash,
            block.proof_of_time.number_of_iterations,
            block.height,
        )
        res, header = await self._reconsider_heads(block.header, genesis, sync_mode)
        if res:
            return ReceiveBlockResult.ADDED_TO_HEAD, header, None
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN, None, None

    async def _reconsider_heads(
        self, block: Header, genesis: bool, sync_mode: bool
    ) -> Tuple[bool, Optional[Header]]:
        """
        When a new block is added, this is called, to check if the new block is heavier
        than one of the heads.
        """
        removed: Optional[Header] = None
        if len(self.tips) == 0 or block.weight > min([b.weight for b in self.tips]):
            self.tips.append(block)
            while len(self.tips) > self.constants["NUMBER_OF_HEADS"]:
                self.tips.sort(key=lambda b: b.weight, reverse=True)
                # This will loop only once
                removed = self.tips.pop()
            await self.block_store.set_tips([t.header_hash for t in self.tips])
            await self._reconsider_lca(genesis, sync_mode)
            return True, removed
        return False, None

    async def _reconsider_lca(self, genesis: bool, sync_mode: bool):
        """
        Update the least common ancestor of the heads. This is useful, since we can just assume
        there is one block per height before the LCA (and use the height_to_hash dict).
        """
        cur: List[Header] = self.tips[:]
        old_lca: Optional[Header]
        try:
            old_lca = self.lca_block
        except AttributeError:
            old_lca = None
        while any(b.header_hash != cur[0].header_hash for b in cur):
            heights = [b.height for b in cur]
            i = heights.index(max(heights))
            cur[i] = self.headers[cur[i].prev_header_hash]
        if genesis:
            self._reconsider_heights(None, cur[0])
        else:
            self._reconsider_heights(self.lca_block, cur[0])
        self.lca_block = cur[0]
        await self.block_store.set_lca(self.lca_block.header_hash)

        if old_lca is None:
            full: Optional[FullBlock] = await self.block_store.get_block(
                self.lca_block.header_hash
            )
            assert full is not None
            await self.coin_store.new_lca(full)
            await self._create_diffs_for_tips(self.lca_block)
        # If LCA changed update the unspent store
        elif old_lca.header_hash != self.lca_block.header_hash:
            # New LCA is lower height but not the a parent of old LCA (Reorg)
            fork_h = self._find_fork_point_in_chain(old_lca, self.lca_block)
            # Rollback to fork
            await self.coin_store.rollback_lca_to_block(fork_h)

            # Add blocks between fork point and new lca
            fork_hash = self.height_to_hash[fork_h]
            fork_head = self.headers[fork_hash]
            await self._from_fork_to_lca(fork_head, self.lca_block)
            if not sync_mode:
                await self.recreate_diff_stores()
        else:
            # If LCA has not changed just update the difference
            self.coin_store.nuke_diffs()
            # Create DiffStore
            await self._create_diffs_for_tips(self.lca_block)

    async def recreate_diff_stores(self):
        # Nuke DiffStore
        self.coin_store.nuke_diffs()
        # Create DiffStore
        await self._create_diffs_for_tips(self.lca_block)

    def _reconsider_heights(self, old_lca: Optional[Header], new_lca: Header):
        """
        Update the mapping from height to block hash, when the lca changes.
        """
        curr_old: Optional[Header] = old_lca if old_lca else None
        curr_new: Header = new_lca
        while True:
            fetched: Optional[Header]
            if not curr_old or curr_old.height < curr_new.height:
                self.height_to_hash[uint32(curr_new.height)] = curr_new.header_hash
                self.headers[curr_new.header_hash] = curr_new
                if curr_new.height == 0:
                    return
                curr_new = self.headers[curr_new.prev_header_hash]
            elif curr_old.height > curr_new.height:
                del self.height_to_hash[uint32(curr_old.height)]
                curr_old = self.headers[curr_old.prev_header_hash]
            else:
                if curr_new.header_hash == curr_old.header_hash:
                    return
                self.height_to_hash[uint32(curr_new.height)] = curr_new.header_hash
                curr_new = self.headers[curr_new.prev_header_hash]
                curr_old = self.headers[curr_old.prev_header_hash]

    def _find_fork_point_in_chain(self, block_1: Header, block_2: Header) -> uint32:
        """ Tries to find height where new chain (block_2) diverged from block_1 (assuming prev blocks
        are all included in chain)"""
        while block_2.height > 0 or block_1.height > 0:
            if block_2.height > block_1.height:
                block_2 = self.headers[block_2.prev_header_hash]
            elif block_1.height > block_2.height:
                block_1 = self.headers[block_1.prev_header_hash]
            else:
                if block_2.header_hash == block_1.header_hash:
                    return block_2.height
                block_2 = self.headers[block_2.prev_header_hash]
                block_1 = self.headers[block_1.prev_header_hash]
        assert block_2 == block_1  # Genesis block is the same, genesis fork
        return uint32(0)

    async def _create_diffs_for_tips(self, target: Header):
        """ Adds to unspent store from tips down to target"""
        for tip in self.tips:
            await self._from_tip_to_lca_unspent(tip, target)

    async def _from_tip_to_lca_unspent(self, head: Header, target: Header):
        """ Adds diffs to unspent store, from tip to lca target"""
        blocks: List[FullBlock] = []
        tip_hash: bytes32 = head.header_hash
        while True:
            if tip_hash == target.header_hash:
                break
            full = await self.block_store.get_block(tip_hash)
            if full is None:
                return
            blocks.append(full)
            tip_hash = full.prev_header_hash
        if len(blocks) == 0:
            return
        blocks.reverse()
        await self.coin_store.new_heads(blocks)

    async def _from_fork_to_lca(self, fork_point: Header, lca: Header):
        """ Selects blocks between fork_point and LCA, and then adds them to coin_store. """
        blocks: List[FullBlock] = []
        tip_hash: bytes32 = lca.header_hash
        while True:
            if tip_hash == fork_point.header_hash:
                break
            full = await self.block_store.get_block(tip_hash)
            if not full:
                return
            blocks.append(full)
            tip_hash = full.prev_header_hash
        blocks.reverse()

        await self.coin_store.add_lcas(blocks)

    def get_next_difficulty(self, header_hash: bytes32) -> uint64:
        return get_next_difficulty(
            self.constants, self.headers, self.height_to_hash, header_hash
        )

    def get_next_min_iters(self, header_hash: bytes32) -> uint64:
        return get_next_min_iters(
            self.constants, self.headers, self.height_to_hash, header_hash
        )

    async def pre_validate_blocks_multiprocessing(
        self, blocks: List[FullBlock]
    ) -> List[Tuple[bool, Optional[bytes32]]]:
        futures = []
        # Pool of workers to validate blocks concurrently
        for block in blocks:
            if self._shut_down:
                return [(False, None) for _ in range(len(blocks))]
            futures.append(
                asyncio.get_running_loop().run_in_executor(
                    self.pool,
                    pre_validate_finished_block_header,
                    self.constants,
                    bytes(block),
                )
            )
        results = await asyncio.gather(*futures)

        for i, (val, pos) in enumerate(results):
            if pos is not None:
                pos = bytes32(pos)
            results[i] = val, pos
        return results

    async def validate_unfinished_block(
        self, block: FullBlock, prev_full_block: FullBlock
    ) -> Tuple[Optional[Err], Optional[uint64]]:
        prev_hb = self.get_header_block(prev_full_block)
        assert prev_hb is not None
        return await validate_unfinished_block_header(
            self.constants,
            self.headers,
            self.height_to_hash,
            block.header,
            block.proof_of_space,
            prev_hb,
            False,
        )

    async def validate_block_body(self, block: FullBlock) -> Optional[Err]:
        """
        Validates the transactions and body of the block. Returns None if everything
        validates correctly, or an Err if something does not validate.
        """

        # 6. The compact block filter must be correct, according to the body (BIP158)
        if block.header.data.filter_hash != bytes32([0] * 32):
            if block.transactions_filter is None:
                return Err.INVALID_TRANSACTIONS_FILTER_HASH
            if std_hash(block.transactions_filter) != block.header.data.filter_hash:
                return Err.INVALID_TRANSACTIONS_FILTER_HASH
        elif block.transactions_filter is not None:
            return Err.INVALID_TRANSACTIONS_FILTER_HASH

        fee_base = calculate_base_fee(block.height)
        # target reward_fee = 1/8 coinbase reward + tx fees
        if block.transactions_generator is not None:
            # 14. Make sure transactions generator hash is valid (or all 0 if not present)
            if (
                block.transactions_generator.get_tree_hash()
                != block.header.data.generator_hash
            ):
                return Err.INVALID_TRANSACTIONS_GENERATOR_HASH

            # 15. If not genesis, the transactions must be valid and fee must be valid
            # Verifies that fee_base + TX fees = fee_coin.amount
            err = await self._validate_transactions(block, fee_base)
            if err is not None:
                return err
        else:
            # Make sure transactions generator hash is valid (or all 0 if not present)
            if block.header.data.generator_hash != bytes32(bytes([0] * 32)):
                return Err.INVALID_TRANSACTIONS_GENERATOR_HASH

            # 16. If genesis, the fee must be the base fee, agg_sig must be None, and merkle roots must be valid
            if fee_base != block.header.data.fees_coin.amount:
                return Err.INVALID_BLOCK_FEE_AMOUNT
            root_error = self._validate_merkle_root(block)
            if root_error:
                return root_error
            if block.header.data.aggregated_signature is not None:
                log.error("1")
                return Err.BAD_AGGREGATE_SIGNATURE
        return None

    def _validate_merkle_root(
        self,
        block: FullBlock,
        tx_additions: List[Coin] = None,
        tx_removals: List[bytes32] = None,
    ) -> Optional[Err]:
        additions = []
        removals = []
        if tx_additions:
            additions.extend(tx_additions)
        if tx_removals:
            removals.extend(tx_removals)

        removal_merkle_set = MerkleSet()
        addition_merkle_set = MerkleSet()

        # Create removal Merkle set
        for coin_name in removals:
            removal_merkle_set.add_already_hashed(coin_name)

        # Create addition Merkle set
        puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
        for coin in additions:
            if coin.puzzle_hash in puzzlehash_coins_map:
                puzzlehash_coins_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coins_map[coin.puzzle_hash] = [coin]

        # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
        for puzzle, coins in puzzlehash_coins_map.items():
            addition_merkle_set.add_already_hashed(puzzle)
            addition_merkle_set.add_already_hashed(hash_coin_list(coins))

        additions_root = addition_merkle_set.get_root()
        removals_root = removal_merkle_set.get_root()

        if block.header.data.additions_root != additions_root:
            return Err.BAD_ADDITION_ROOT
        if block.header.data.removals_root != removals_root:
            return Err.BAD_REMOVAL_ROOT

        return None

    async def _validate_transactions(
        self, block: FullBlock, fee_base: uint64
    ) -> Optional[Err]:
        # TODO(straya): review, further test the code, and number all the validation steps

        # 1. Check that transactions generator is present
        if not block.transactions_generator:
            return Err.UNKNOWN
        # Get List of names removed, puzzles hashes for removed coins and conditions crated
        error, npc_list, cost = calculate_cost_of_program(block.transactions_generator)

        # 2. Check that cost <= MAX_BLOCK_COST_CLVM
        if cost > self.constants["MAX_BLOCK_COST_CLVM"]:
            return Err.BLOCK_COST_EXCEEDS_MAX
        if error:
            return error

        prev_header: Header
        if block.prev_header_hash in self.headers:
            prev_header = self.headers[block.prev_header_hash]
        else:
            return Err.EXTENDS_UNKNOWN_BLOCK

        removals: List[bytes32] = []
        removals_puzzle_dic: Dict[bytes32, bytes32] = {}
        for npc in npc_list:
            removals.append(npc.coin_name)
            removals_puzzle_dic[npc.coin_name] = npc.puzzle_hash

        additions: List[Coin] = additions_for_npc(npc_list)
        additions_dic: Dict[bytes32, Coin] = {}
        # Check additions for max coin amount
        for coin in additions:
            additions_dic[coin.name()] = coin
            if coin.amount >= uint64.from_bytes(self.constants["MAX_COIN_AMOUNT"]):
                return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM

        # Validate addition and removal roots
        root_error = self._validate_merkle_root(block, additions, removals)
        if root_error:
            return root_error

        # Validate filter
        byte_array_tx: List[bytes32] = []

        for coin in additions:
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for coin_name in removals:
            byte_array_tx.append(bytearray(coin_name))

        bip158: PyBIP158 = PyBIP158(byte_array_tx)
        encoded_filter = bytes(bip158.GetEncoded())
        filter_hash = std_hash(encoded_filter)

        if filter_hash != block.header.data.filter_hash:
            return Err.INVALID_TRANSACTIONS_FILTER_HASH

        # Watch out for duplicate outputs
        addition_counter = collections.Counter(_.name() for _ in additions)
        for k, v in addition_counter.items():
            if v > 1:
                return Err.DUPLICATE_OUTPUT

        # Check for duplicate spends inside block
        removal_counter = collections.Counter(removals)
        for k, v in removal_counter.items():
            if v > 1:
                log.error(f"DOUBLE SPEND! 1 {k}")
                return Err.DOUBLE_SPEND

        # Check if removals exist and were not previously spend. (unspent_db + diff_store + this_block)
        fork_h = self._find_fork_point_in_chain(self.lca_block, block.header)

        # Get additions and removals since (after) fork_h but not including this block
        additions_since_fork: Dict[bytes32, Tuple[Coin, uint32]] = {}
        removals_since_fork: Set[bytes32] = set()
        coinbases_since_fork: Dict[bytes32, uint32] = {}
        curr: Optional[FullBlock] = await self.block_store.get_block(
            block.prev_header_hash
        )
        assert curr is not None
        log.info(f"curr.height is: {curr.height}, fork height is: {fork_h}")
        while curr.height > fork_h:
            removals_in_curr, additions_in_curr = await curr.tx_removals_and_additions()
            for c_name in removals_in_curr:
                removals_since_fork.add(c_name)
            for c in additions_in_curr:
                additions_since_fork[c.name()] = (c, curr.height)
            additions_since_fork[curr.header.data.coinbase.name()] = (
                curr.header.data.coinbase,
                curr.height,
            )
            additions_since_fork[curr.header.data.fees_coin.name()] = (
                curr.header.data.fees_coin,
                curr.height,
            )
            coinbases_since_fork[curr.header.data.coinbase.name()] = curr.height
            coinbases_since_fork[curr.header.data.fees_coin.name()] = curr.height
            curr = await self.block_store.get_block(curr.prev_header_hash)
            assert curr is not None

        removal_coin_records: Dict[bytes32, CoinRecord] = {}
        for rem in removals:
            if rem in additions_dic:
                # Ephemeral coin
                rem_coin: Coin = additions_dic[rem]
                new_unspent: CoinRecord = CoinRecord(
                    rem_coin, block.height, uint32(0), False, False
                )
                removal_coin_records[new_unspent.name] = new_unspent
            else:
                assert prev_header is not None
                unspent = await self.coin_store.get_coin_record(rem, prev_header)
                if unspent is not None and unspent.confirmed_block_index <= fork_h:
                    # Spending something in the current chain, confirmed before fork
                    # (We ignore all coins confirmed after fork)
                    if unspent.spent == 1 and unspent.spent_block_index <= fork_h:
                        # Spend in an ancestor block, so this is a double spend
                        log.error(f"DOUBLE SPEND! 2 {unspent}")
                        return Err.DOUBLE_SPEND
                    # If it's a coinbase, check that it's not frozen
                    if unspent.coinbase == 1:
                        if (
                            block.height
                            < unspent.confirmed_block_index + self.coinbase_freeze
                        ):
                            return Err.COINBASE_NOT_YET_SPENDABLE
                    removal_coin_records[unspent.name] = unspent
                else:
                    # This coin is not in the current heaviest chain, so it must be in the fork
                    if rem not in additions_since_fork:
                        # This coin does not exist in the fork
                        return Err.UNKNOWN_UNSPENT
                    if rem in coinbases_since_fork:
                        # This coin is a coinbase coin
                        if (
                            block.height
                            < coinbases_since_fork[rem] + self.coinbase_freeze
                        ):
                            return Err.COINBASE_NOT_YET_SPENDABLE
                    new_coin, confirmed_height = additions_since_fork[rem]
                    new_coin_record: CoinRecord = CoinRecord(
                        new_coin,
                        confirmed_height,
                        uint32(0),
                        False,
                        (rem in coinbases_since_fork),
                    )
                    removal_coin_records[new_coin_record.name] = new_coin_record

                # This check applies to both coins created before fork (pulled from coin_store),
                # and coins created after fork (additions_since_fork)>
                if rem in removals_since_fork:
                    # This coin was spent in the fork
                    log.error(f"DOUBLE SPEND! 3 {rem}")
                    log.error(f"removals_since_fork: {removals_since_fork}")
                    return Err.DOUBLE_SPEND

        # Check fees
        removed = 0
        for unspent in removal_coin_records.values():
            removed += unspent.coin.amount

        added = 0
        for coin in additions:
            added += coin.amount

        if removed < added:
            return Err.MINTING_COIN

        fees = removed - added
        assert_fee_sum: uint64 = uint64(0)

        for npc in npc_list:
            if ConditionOpcode.ASSERT_FEE in npc.condition_dict:
                fee_list: List[ConditionVarPair] = npc.condition_dict[
                    ConditionOpcode.ASSERT_FEE
                ]
                for cvp in fee_list:
                    fee = int_from_bytes(cvp.var1)
                    assert_fee_sum = assert_fee_sum + fee

        if fees < assert_fee_sum:
            return Err.ASSERT_FEE_CONDITION_FAILED

        # Check coinbase reward
        if fees + fee_base != block.header.data.fees_coin.amount:
            return Err.BAD_COINBASE_REWARD

        # Verify that removed coin puzzle_hashes match with calculated puzzle_hashes
        for unspent in removal_coin_records.values():
            if unspent.coin.puzzle_hash != removals_puzzle_dic[unspent.name]:
                return Err.WRONG_PUZZLE_HASH

        # Verify conditions, create hash_key list for aggsig check
        hash_key_pairs = []
        for npc in npc_list:
            unspent = removal_coin_records[npc.coin_name]
            error = blockchain_check_conditions_dict(
                unspent, removal_coin_records, npc.condition_dict, block.header,
            )
            if error:
                return error
            hash_key_pairs.extend(
                hash_key_pairs_for_conditions_dict(npc.condition_dict, npc.coin_name)
            )

        # Verify aggregated signature
        # TODO: move this to pre_validate_blocks_multiprocessing so we can sync faster
        if not block.header.data.aggregated_signature:
            return Err.BAD_AGGREGATE_SIGNATURE
        if not block.header.data.aggregated_signature.validate(hash_key_pairs):
            return Err.BAD_AGGREGATE_SIGNATURE

        return None
