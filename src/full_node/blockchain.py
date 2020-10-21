import asyncio
import collections
import logging
from enum import Enum
import multiprocessing
import concurrent
from typing import Dict, List, Optional, Set, Tuple, Union
from blspy import AugSchemeMPL

from chiabip158 import PyBIP158

from src.consensus.constants import ConsensusConstants
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.full_node.difficulty_adjustment import get_next_difficulty, get_next_slot_iters
from src.types.coin import Coin
from src.types.coin_record import CoinRecord
from src.types.condition_opcodes import ConditionOpcode
from src.types.condition_var_pair import ConditionVarPair
from src.types.full_block import FullBlock, additions_for_npc
from src.types.header_block import HeaderBlock
from src.types.unfinished_block import UnfinishedBlock
from src.types.sized_bytes import bytes32
from src.full_node.blockchain_check_conditions import blockchain_check_conditions_dict
from src.full_node.sub_block_record import SubBlockRecord
from src.util.clvm import int_from_bytes
from src.util.condition_tools import pkm_pairs_for_conditions_dict
from src.full_node.cost_calculator import calculate_cost_of_program
from src.util.errors import ConsensusError, Err
from src.util.hash import std_hash
from src.util.ints import uint32, uint64
from src.full_node.block_root_validation import validate_block_merkle_roots
from src.consensus.find_fork_point import find_fork_point_in_chain
from src.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.types.name_puzzle_condition import NPC
from src.full_node.block_header_validation import validate_finished_header_block, validate_unfinished_header_block
from src.types.unfinished_header_block import UnfinishedHeaderBlock

log = logging.getLogger(__name__)


class ReceiveBlockResult(Enum):
    """
    When Blockchain.receive_block(b) is called, one of these results is returned,
    showing whether the block was added to the chain (extending the tip),
    and if not, why it was not added.
    """

    NEW_TIP = 1  # Added to the tip of the blockchain
    ADDED_AS_ORPHAN = 2  # Added as an orphan/stale block (not a new tip of the chain)
    INVALID_BLOCK = 3  # Block was not added because it was invalid
    ALREADY_HAVE_BLOCK = 4  # Block is already present in this blockchain
    DISCONNECTED_BLOCK = 5  # Block's parent (previous pointer) is not in this blockchain


class Blockchain:
    constants: ConsensusConstants
    # Tip of the blockchain
    tip_height: uint32
    # Defines the path from genesis to the tip, no orphan sub-blocks
    height_to_hash: Dict[uint32, bytes32]
    # All sub blocks in tip path are guaranteed to be included, can include orphan sub-blocks
    sub_blocks: Dict[bytes32, SubBlockRecord]
    # Unspent Store
    coin_store: CoinStore
    # Store
    block_store: BlockStore
    # Coinbase freeze period
    coinbase_freeze: int
    # Used to verify blocks in parallel
    pool: concurrent.futures.ProcessPoolExecutor

    # Whether blockchain is shut down or not
    _shut_down: bool

    # Lock to prevent simultaneous reads and writes
    lock: asyncio.Lock

    @staticmethod
    async def create(
        coin_store: CoinStore,
        block_store: BlockStore,
        consensus_constants: ConsensusConstants,
    ):
        """
        Initializes a blockchain with the header blocks from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = Blockchain()
        self.lock = asyncio.Lock()  # External lock handled by full node
        cpu_count = multiprocessing.cpu_count()
        if cpu_count > 61:
            cpu_count = 61  # Windows Server 2016 has an issue https://bugs.python.org/issue26903
        self.pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=max(cpu_count - 2, 1)
        )
        self.constants = consensus_constants
        self.tip_height = 0
        self.height_to_hash = {}
        self.sub_blocks = {}
        self.coin_store = coin_store
        self.block_store = block_store
        self._shut_down = False
        self.coinbase_freeze = self.constants.COINBASE_FREEZE_PERIOD
        await self._load_chain_from_store(FullBlock.from_bytes(self.constants.GENESIS_BLOCK))
        return self

    def shut_down(self):
        self._shut_down = True
        self.pool.shutdown(wait=True)

    async def _load_chain_from_store(self, genesis: FullBlock) -> None:
        """
        Initializes the state of the Blockchain class from the database. Sets the LCA, tips,
        headers, height_to_hash, and block_store DiffStores.
        """
        self.sub_blocks_db: Dict[bytes32, SubBlockRecord] = await self.block_store.get_sub_blocks()

        if len(self.sub_blocks_db) == 0:
            result, error_code = await self.receive_block(genesis, sync_mode=False)
            if result != ReceiveBlockResult.NEW_TIP:
                if error_code is not None:
                    raise ConsensusError(error_code)
                else:
                    raise RuntimeError(f"Invalid genesis block {genesis}")
            return

        # Sets the other state variables (tip_height and height_to_hash)
        for hh, sb in self.sub_blocks:
            self.height_to_hash[sb.height] = hh
            if sb.height > self.tip_height:
                self.tip_height = sb.height

        assert len(self.sub_blocks_db) == len(self.height_to_hash) == self.tip_height + 1

    def get_tip(self) -> SubBlockRecord:
        """
        Return the tip of the blockchain
        """
        return self.sub_blocks[self.height_to_hash[self.tip_height]]

    async def get_full_tip(self) -> FullBlock:
        """ Return list of FullBlocks that are tips"""
        block = await self.block_store.get_block(self.height_to_hash[self.tip_height])
        assert block is not None
        return block

    def is_child_of_tip(self, block: FullBlock) -> bool:
        """
        True iff the block is the direct ancestor of the tip
        """
        return block.prev_header_hash == self.get_tip().header_hash

    def contains_block(self, header_hash: bytes32) -> bool:
        """
        True if we have already added this block to the chain. This may return false for orphan sub-blocks
        that we have added but no longer keep in memory.
        """
        return header_hash in self.sub_blocks

    def get_header_hashes(self, tip_header_hash: bytes32) -> List[bytes32]:
        """
        Returns a list of all header hashes from genesis to the tip, inclusive.
        """
        if tip_header_hash not in self.sub_blocks:
            raise ValueError("Invalid tip requested")

        curr = self.sub_blocks[tip_header_hash]
        ret_hashes = [tip_header_hash]
        while curr.height != 0:
            curr = self.sub_blocks[curr.prev_header_hash]
            ret_hashes.append(curr.header_hash)
        return list(reversed(ret_hashes))

    def find_fork_point_alternate_chain(self, alternate_chain: List[bytes32]) -> uint32:
        """
        Takes in an alternate blockchain (headers), and compares it to self. Returns the last header
        where both blockchains are equal.
        """
        tip: SubBlockRecord = self.get_tip()

        if tip.height >= len(alternate_chain) - 1:
            raise ValueError("Alternate chain is shorter")
        low: uint32 = uint32(0)
        high = tip.height
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
    ) -> Tuple[ReceiveBlockResult, Optional[Err]]:
        """
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid.
        """
        genesis: bool = block.height == 0 and len(self.height_to_hash) == 0

        if block.header_hash in self.sub_blocks:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None

        if block.prev_header_hash not in self.sub_blocks and not genesis:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None

        curr_header_block = HeaderBlock(
            block.subepoch_summary,
            block.finished_slots,
            block.challenge_chain_icp_vdf,
            block.challenge_chain_icp_proof,
            block.challenge_chain_icp_signature,
            block.challenge_chain_ip_vdf,
            block.challenge_chain_ip_proof,
            block.reward_chain_sub_block,
            block.reward_chain_icp_proof,
            block.reward_chain_ip_proof,
            block.foliage_sub_block,
            block.foliage_block,
            b"",  # Nofilter
        )

        error_code: Optional[Err] = await validate_finished_header_block(
            self.constants, self.sub_blocks, self.height_to_hash, curr_header_block, False
        )

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code

        error_code = await self.validate_block_body(block)

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code

        # TODO: fill
        sub_block = block.get_sub_block_record(0)

        # Always add the block to the database
        await self.block_store.add_block(block)

        new_tip = await self._reconsider_tip(sub_block, genesis)
        if new_tip:
            return ReceiveBlockResult.NEW_TIP, None
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN, None

    async def _reconsider_tip(self, sub_block: SubBlockRecord, genesis: bool) -> bool:
        """
        When a new block is added, this is called, to check if the new block is the new tip of the chain.
        This also handles reorgs by reverting blocks which are not in the heaviest chain.
        """
        if genesis:
            assert self.tip_height == 0
            block: Optional[FullBlock] = await self.block_store.get_block(sub_block.header_hash)
            assert block is not None
            await self.coin_store.new_block(block)
            self.height_to_hash[uint32(0)] = block.header_hash
            return True

        if sub_block.weight > self.get_tip().weight:
            # Find the fork. if the block is just being appended, it will return the tip
            fork_h: bytes32 = find_fork_point_in_chain(self.sub_blocks, sub_block, self.get_tip())
            # Rollback to fork
            await self.coin_store.rollback_to_block(fork_h)

            # Collect all blocks from fork point to new tip
            blocks_to_add: List[FullBlock] = []
            curr = sub_block.header_hash
            while curr != self.height_to_hash[fork_h]:
                block: Optional[FullBlock] = await self.block_store.get_block(curr)
                assert block is not None
                blocks_to_add.append(block)
                curr = block.prev_header_hash

            for block in reversed(blocks_to_add):
                self.height_to_hash[block.height] = block.header_hash
                self.sub_blocks[block.header_hash] = SubBlockRecord(
                    block.header_hash, block.prev_header_hash, block.height, block.weight, block.total_iters
                )
                await self.coin_store.new_block(block)
            return True

        # This is not a heavier block than the heaviest we have seen, so we don't change the coin set
        return False

    def get_next_difficulty(self, header_hash: bytes32) -> uint64:
        return get_next_difficulty(self.constants, self.sub_blocks, self.height_to_hash, header_hash)

    def get_next_slot_iters(self, header_hash: bytes32) -> uint64:
        return get_next_slot_iters(self.constants, self.sub_blocks, self.height_to_hash, header_hash)

    async def pre_validate_blocks_multiprocessing(
        self, blocks: List[FullBlock]
    ) -> List[Tuple[bool, Optional[bytes32]]]:
        # TODO(mariano): review
        # futures = []
        # # Pool of workers to validate blocks concurrently
        # for block in blocks:
        #     if self._shut_down:
        #         return [(False, None) for _ in range(len(blocks))]
        #     futures.append(
        #         asyncio.get_running_loop().run_in_executor(
        #             self.pool,
        #             pre_validate_finished_block_header,
        #             self.constants,
        #             bytes(block),
        #         )
        #     )
        # results = await asyncio.gather(*futures)
        #
        # for i, (val, pos) in enumerate(results):
        #     if pos is not None:
        #         pos = bytes32(pos)
        #     results[i] = val, pos
        # return results
        return []

    async def validate_unfinished_block(self, block: UnfinishedBlock) -> Optional[Err]:
        unfinished_header_block = UnfinishedHeaderBlock(
            block.subepoch_summary,
            block.finished_slots,
            block.challenge_chain_icp_vdf,
            block.challenge_chain_icp_proof,
            block.challenge_chain_icp_signature,
            block.reward_chain_sub_block,
            block.reward_chain_icp_proof,
            block.foliage_sub_block,
            block.foliage_block,
            b"",
        )

        error_code: Optional[Err] = await validate_unfinished_header_block(
            self.constants, self.sub_blocks, self.height_to_hash, unfinished_header_block, False
        )

        if error_code is not None:
            return error_code

        error_code = await self.validate_block_body(block)

        if error_code is not None:
            return error_code

        return await self.validate_block_body(block)

    async def validate_block_body(self, block: Union[FullBlock, UnfinishedBlock]) -> Optional[Err]:
        """
        This assumes the header block has been completely validated.
        Validates the transactions and body of the block. Returns None if everything
        validates correctly, or an Err if something does not validate.
        """

        # 1. For non block sub-blocks, foliage block, transaction filter, transactions info, and generator must be empty
        # If it is a sub block but not a block, there is no body to validate. Check that all fields are None
        if not block.foliage_sub_block.is_block:
            if (
                block.foliage_block is not None
                or block.transactions_filter is not None
                or block.transactions_info is not None
                or block.transactions_generator is not None
            ):
                return Err.NOT_BLOCK_BUT_HAS_DATA
            return None  # This means the sub-block is valid

        # 2. For blocks, foliage block, transaction filter, transactions info must not be empty
        if block.foliage_block is None or block.transactions_filter is None or block.transactions_info is None:
            return Err.IS_BLOCK_BUT_NO_DATA

        # keeps track of the reward coins that need to be incorporated
        expected_reward_coins: Set[Coin] = set()

        # 3. The transaction info hash in the Foliage block must match the transaction info
        if block.foliage_block.transactions_info_hash != std_hash(block.transactions_info):
            return Err.INVALID_TRANSACTIONS_INFO_HASH

        # 4. The foliage block hash in the foliage sub block must match the foliage block
        if block.foliage_sub_block.signed_data.foliage_block_hash != std_hash(block.foliage_block):
            return Err.INVALID_FOLIAGE_BLOCK_HASH

        # 5. The prev generators root must be valid
        # TODO(straya): implement prev generators

        # 6. The generator root must be the tree-hash of the generator (or zeroes if no generator)
        if block.transactions_generator is not None:
            if block.transactions_generator.get_tree_hash() != block.transactions_info.generator_root:
                return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT
        else:
            if block.transactions_info.generator_root != bytes([0] * 32):
                return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT

        # 7. The reward claims must be valid for the previous sub-blocks, and current block fees
        pool_coin = create_pool_coin(
            block.height,
            block.foliage_sub_block.signed_data.pool_target.puzzle_hash,
            calculate_pool_reward(block.height),
        )
        farmer_coin = create_farmer_coin(
            block.height,
            block.foliage_sub_block.signed_data.farmer_reward_puzzle_hash,
            calculate_base_farmer_reward(block.height) + block.transactions_info.fees,
        )
        expected_reward_coins.add(pool_coin)
        expected_reward_coins.add(farmer_coin)
        if block.transactions_info.reward_claims_incorporated != expected_reward_coins:
            return Err.INVALID_REWARD_COINS

        removals: List[bytes32] = []
        coinbase_additions: List[Coin] = [farmer_coin, pool_coin]
        additions: List[Coin] = []
        npc_list: List[NPC] = []
        removals_puzzle_dic: Dict[bytes32, bytes32] = {}
        cost: uint64 = uint64(0)

        if block.transactions_generator is not None:
            # Get List of names removed, puzzles hashes for removed coins and conditions crated
            error, npc_list, cost = calculate_cost_of_program(
                block.transactions_generator, self.constants.CLVM_COST_RATIO_CONSTANT
            )

            # 8. Check that cost <= MAX_BLOCK_COST_CLVM
            if cost > self.constants.MAX_BLOCK_COST_CLVM:
                return Err.BLOCK_COST_EXCEEDS_MAX
            if error:
                return error

            for npc in npc_list:
                removals.append(npc.coin_name)
                removals_puzzle_dic[npc.coin_name] = npc.puzzle_hash

            additions = additions_for_npc(npc_list)

        # 9. Check that the correct cost is in the transactions info
        if block.transactions_info.cost != cost:
            return Err.INVALID_BLOCK_COST

        additions_dic: Dict[bytes32, Coin] = {}
        # 10. Check additions for max coin amount
        for coin in additions + coinbase_additions:
            additions_dic[coin.name()] = coin
            if coin.amount >= self.constants.MAX_COIN_AMOUNT:
                return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM

        # 11. Validate addition and removal roots
        root_error = validate_block_merkle_roots(block, additions + coinbase_additions, removals)
        if root_error:
            return root_error

        # 12. The additions and removals must result in the correct filter
        byte_array_tx: List[bytes32] = []

        for coin in additions + coinbase_additions:
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for coin_name in removals:
            byte_array_tx.append(bytearray(coin_name))

        bip158: PyBIP158 = PyBIP158(byte_array_tx)
        encoded_filter = bytes(bip158.GetEncoded())
        filter_hash = std_hash(encoded_filter)

        if filter_hash != block.header.data.filter_hash:
            return Err.INVALID_TRANSACTIONS_FILTER_HASH

        # 13. Check for duplicate outputs in additions
        addition_counter = collections.Counter(_.name() for _ in additions + coinbase_additions)
        for k, v in addition_counter.items():
            if v > 1:
                return Err.DUPLICATE_OUTPUT

        # 14. Check for duplicate spends inside block
        removal_counter = collections.Counter(removals)
        for k, v in removal_counter.items():
            if v > 1:
                return Err.DOUBLE_SPEND

        # 15. Check if removals exist and were not previously spent. (unspent_db + diff_store + this_block)
        new_ips = self.get_next_slot_iters(block.prev_header_hash)
        fork_h = find_fork_point_in_chain(self.sub_blocks, self.get_tip(), block.get_sub_block_record(new_ips))

        # Get additions and removals since (after) fork_h but not including this block
        additions_since_fork: Dict[bytes32, Tuple[Coin, uint32]] = {}
        removals_since_fork: Set[bytes32] = set()
        coinbases_since_fork: Dict[bytes32, uint32] = {}
        curr: Optional[FullBlock] = await self.block_store.get_block(block.prev_header_hash)
        assert curr is not None

        while curr.height > fork_h:
            removals_in_curr, additions_in_curr = await curr.tx_removals_and_additions()
            for c_name in removals_in_curr:
                removals_since_fork.add(c_name)
            for c in additions_in_curr:
                additions_since_fork[c.name()] = (c, curr.height)

            for coinbase_coin in curr.get_included_reward_coins():
                coinbases_since_fork[coinbase_coin.name()] = curr.height
            curr = await self.block_store.get_block(curr.prev_header_hash)
            assert curr is not None

        removal_coin_records: Dict[bytes32, CoinRecord] = {}
        for rem in removals:
            if rem in additions_dic:
                # Ephemeral coin
                rem_coin: Coin = additions_dic[rem]
                new_unspent: CoinRecord = CoinRecord(rem_coin, block.height, uint32(0), False, False)
                removal_coin_records[new_unspent.name] = new_unspent
            else:
                unspent = await self.coin_store.get_coin_record(rem)
                if unspent is not None and unspent.confirmed_block_index <= fork_h:
                    # Spending something in the current chain, confirmed before fork
                    # (We ignore all coins confirmed after fork)
                    if unspent.spent == 1 and unspent.spent_block_index <= fork_h:
                        # Check for coins spent in an ancestor block
                        return Err.DOUBLE_SPEND
                    # If it's a coinbase, check that it's not frozen
                    if unspent.coinbase == 1:
                        if block.height < unspent.confirmed_block_index + self.coinbase_freeze:
                            return Err.COINBASE_NOT_YET_SPENDABLE
                    removal_coin_records[unspent.name] = unspent
                else:
                    # This coin is not in the current heaviest chain, so it must be in the fork
                    if rem not in additions_since_fork:
                        # Check for spending a coin that does not exist in this fork
                        # TODO: fix this, there is a consensus bug here
                        return Err.UNKNOWN_UNSPENT
                    if rem in coinbases_since_fork:
                        # This coin is a coinbase coin
                        if block.height < coinbases_since_fork[rem] + self.coinbase_freeze:
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
                    return Err.DOUBLE_SPEND

        removed = 0
        for unspent in removal_coin_records.values():
            removed += unspent.coin.amount

        added = 0
        for coin in additions:
            added += coin.amount

        # 16. Check that the total coin amount for added is <= removed
        if removed < added:
            return Err.MINTING_COIN

        fees = removed - added
        assert_fee_sum: uint64 = uint64(0)

        for npc in npc_list:
            if ConditionOpcode.ASSERT_FEE in npc.condition_dict:
                fee_list: List[ConditionVarPair] = npc.condition_dict[ConditionOpcode.ASSERT_FEE]
                for cvp in fee_list:
                    fee = int_from_bytes(cvp.vars[0])
                    assert_fee_sum = assert_fee_sum + fee

        # 17. Check that the assert fee sum <= fees
        if fees < assert_fee_sum:
            return Err.ASSERT_FEE_CONDITION_FAILED

        # 18. Check that the computed fees are equal to the fees in the block header
        if block.transactions_info.fees != fees:
            return Err.INVALID_BLOCK_FEE_AMOUNT

        # 19. Verify that removed coin puzzle_hashes match with calculated puzzle_hashes
        for unspent in removal_coin_records.values():
            if unspent.coin.puzzle_hash != removals_puzzle_dic[unspent.name]:
                return Err.WRONG_PUZZLE_HASH

        # 20. Verify conditions
        # create hash_key list for aggsig check
        pairs_pks = []
        pairs_msgs = []
        for npc in npc_list:
            unspent = removal_coin_records[npc.coin_name]
            error = blockchain_check_conditions_dict(
                unspent,
                removal_coin_records,
                npc.condition_dict,
                block.header,
            )
            if error:
                return error
            for pk, m in pkm_pairs_for_conditions_dict(npc.condition_dict, npc.coin_name):
                pairs_pks.append(pk)
                pairs_msgs.append(m)

        # 21. Verify aggregated signature
        # TODO: move this to pre_validate_blocks_multiprocessing so we can sync faster
        if not block.transactions_info.aggregated_signature:
            return Err.BAD_AGGREGATE_SIGNATURE

        validates = AugSchemeMPL.aggregate_verify(pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature)
        if not validates:
            return Err.BAD_AGGREGATE_SIGNATURE

        return None
