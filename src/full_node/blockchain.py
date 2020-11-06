import asyncio
import collections
import logging
from concurrent.futures.process import ProcessPoolExecutor
from enum import Enum
import multiprocessing
import concurrent
from typing import Dict, List, Optional, Set, Tuple, Union
from blspy import AugSchemeMPL, G2Element

from chiabip158 import PyBIP158

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import is_overflow_sub_block, calculate_ip_iters, calculate_sp_iters
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.full_node.deficit import calculate_deficit
from src.full_node.difficulty_adjustment import get_next_difficulty, get_next_ips
from src.full_node.full_block_to_sub_block_record import full_block_to_sub_block_record
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
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.util.clvm import int_from_bytes
from src.util.condition_tools import pkm_pairs_for_conditions_dict
from src.full_node.cost_calculator import calculate_cost_of_program
from src.util.errors import Err
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint128
from src.full_node.block_root_validation import validate_block_merkle_roots
from src.consensus.find_fork_point import find_fork_point_in_chain
from src.consensus.block_rewards import (
    calculate_pool_reward,
    calculate_base_farmer_reward,
)
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.types.name_puzzle_condition import NPC
from src.full_node.block_header_validation import (
    validate_finished_header_block,
    validate_unfinished_header_block,
)
from src.types.unfinished_header_block import UnfinishedHeaderBlock

log = logging.getLogger(__name__)


class ReceiveBlockResult(Enum):
    """
    When Blockchain.receive_block(b) is called, one of these results is returned,
    showing whether the block was added to the chain (extending the peak),
    and if not, why it was not added.
    """

    NEW_PEAK = 1  # Added to the peak of the blockchain
    ADDED_AS_ORPHAN = 2  # Added as an orphan/stale block (not a new peak of the chain)
    INVALID_BLOCK = 3  # Block was not added because it was invalid
    ALREADY_HAVE_BLOCK = 4  # Block is already present in this blockchain
    DISCONNECTED_BLOCK = (
        5  # Block's parent (previous pointer) is not in this blockchain
    )


class Blockchain:
    constants: ConsensusConstants
    # peak of the blockchain
    peak_height: Optional[uint32]
    # All sub blocks in peak path are guaranteed to be included, can include orphan sub-blocks
    sub_blocks: Dict[bytes32, SubBlockRecord]
    # Defines the path from genesis to the peak, no orphan sub-blocks
    height_to_hash: Dict[uint32, bytes32]
    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the sub-blocks in the path to the peak
    sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}
    # Unspent Store
    coin_store: CoinStore
    # Store
    block_store: BlockStore
    # Coinbase freeze period
    coinbase_freeze: int
    # Used to verify blocks in parallel
    pool: ProcessPoolExecutor

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
        Initializes a blockchain with the SubBlockRecords from disk, assuming they have all been
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
        self.coin_store = coin_store
        self.block_store = block_store
        self._shut_down = False
        self.coinbase_freeze = self.constants.COINBASE_FREEZE_PERIOD
        await self._load_chain_from_store()
        return self

    def shut_down(self):
        self._shut_down = True
        self.pool.shutdown(wait=True)

    async def _load_chain_from_store(self) -> None:
        """
        Initializes the state of the Blockchain class from the database.
        """
        self.sub_blocks, peak = await self.block_store.get_sub_blocks()
        self.height_to_hash = {}
        self.sub_epoch_summaries = {}

        if len(self.sub_blocks) == 0:
            assert peak is None
            log.info("Initializing empty blockchain")
            self.peak_height = None
            return

        assert peak is not None
        self.peak_height = self.sub_blocks[peak].height

        # Sets the other state variables (peak_height and height_to_hash)
        curr: SubBlockRecord = self.sub_blocks[peak]
        while True:
            self.height_to_hash[curr.height] = curr.header_hash
            if curr.sub_epoch_summary_included is not None:
                self.sub_epoch_summaries[curr.height] = curr.sub_epoch_summary_included
            if curr.height == 0:
                break
            curr = self.sub_blocks[curr.prev_hash]
        assert len(self.sub_blocks) == len(self.height_to_hash) == self.peak_height + 1

    def get_peak(self) -> Optional[SubBlockRecord]:
        """
        Return the peak of the blockchain
        """
        if self.peak_height is None:
            return None
        return self.sub_blocks[self.height_to_hash[self.peak_height]]

    async def get_full_peak(self) -> Optional[FullBlock]:
        if self.peak_height is None:
            return None
        """ Return list of FullBlocks that are peaks"""
        block = await self.block_store.get_block(self.height_to_hash[self.peak_height])
        assert block is not None
        return block

    def is_child_of_peak(self, block: UnfinishedBlock) -> bool:
        """
        True iff the block is the direct ancestor of the peak
        """
        if self.peak_height is None:
            return False
        return block.prev_header_hash == self.get_peak().header_hash

    def contains_block(self, header_hash: bytes32) -> bool:
        """
        True if we have already added this block to the chain. This may return false for orphan sub-blocks
        that we have added but no longer keep in memory.
        """
        return header_hash in self.sub_blocks

    async def receive_block(
        self,
        block: FullBlock,
        pre_validated: bool = False,
    ) -> Tuple[ReceiveBlockResult, Optional[Err], Optional[uint32]]:
        """
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid. Also returns the fork height, in the case of a new peak.
        """
        genesis: bool = block.height == 0

        if block.header_hash in self.sub_blocks:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None, None

        if block.prev_header_hash not in self.sub_blocks and not genesis:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None, None

        curr_header_block = HeaderBlock(
            block.finished_sub_slots,
            block.reward_chain_sub_block,
            block.challenge_chain_sp_proof,
            block.challenge_chain_ip_proof,
            block.reward_chain_sp_proof,
            block.reward_chain_ip_proof,
            block.infused_challenge_chain_ip_proof,
            block.foliage_sub_block,
            block.foliage_block,
            b"",  # No filter
        )
        required_iters, error_code = await validate_finished_header_block(
            self.constants,
            self.sub_blocks,
            self.height_to_hash,
            curr_header_block,
            False,
        )

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code, None

        error_code = await self.validate_block_body(block)

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code, None

        sub_block = full_block_to_sub_block_record(
            self.constants,
            self.sub_blocks,
            self.height_to_hash,
            block,
            required_iters,
        )

        # Always add the block to the database
        await self.block_store.add_block(block, sub_block)

        fork_height: Optional[uint32] = await self._reconsider_peak(sub_block, genesis)
        if fork_height is not None:
            return ReceiveBlockResult.NEW_PEAK, None, fork_height
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN, None, None

    async def _reconsider_peak(
        self, sub_block: SubBlockRecord, genesis: bool
    ) -> Optional[uint32]:
        """
        When a new block is added, this is called, to check if the new block is the new peak of the chain.
        This also handles reorgs by reverting blocks which are not in the heaviest chain.
        It returns the height of the fork between the previous chain and the new chain, or returns
        None if there was no update to the heaviest chain.
        """
        if genesis:
            block: Optional[FullBlock] = await self.block_store.get_block(
                sub_block.header_hash
            )
            assert block is not None
            await self.coin_store.new_block(block)
            self.height_to_hash[uint32(0)] = block.header_hash
            self.sub_blocks[block.header_hash] = sub_block
            self.peak_height = uint32(0)
            return uint32(0)

        assert self.get_peak() is not None
        if sub_block.weight > self.get_peak().weight:
            # Find the fork. if the block is just being appended, it will return the peak
            # If no blocks in common, returns -1, and reverts all blocks
            fork_h: int = find_fork_point_in_chain(
                self.sub_blocks, sub_block, self.get_peak()
            )

            # Rollback to fork
            await self.coin_store.rollback_to_block(fork_h)

            # Rollback sub_epoch_summaries
            for ses_included_height in self.sub_epoch_summaries.keys():
                if ses_included_height > fork_h:
                    del self.sub_epoch_summaries[ses_included_height]

            # Collect all blocks from fork point to new peak
            blocks_to_add: List[Tuple[FullBlock, SubBlockRecord]] = []
            curr = sub_block.header_hash
            while fork_h < 0 or curr != self.height_to_hash[uint32(fork_h)]:
                fetched_block: Optional[FullBlock] = await self.block_store.get_block(
                    curr
                )
                fetched_sub_block: Optional[
                    SubBlockRecord
                ] = await self.block_store.get_sub_block(curr)
                assert fetched_block is not None
                assert fetched_sub_block is not None
                blocks_to_add.append((fetched_block, fetched_sub_block))
                if fetched_block.height == 0:
                    # Doing a full reorg, starting at height 0
                    break
                curr = fetched_sub_block.prev_hash

            for fetched_block, fetched_sub_block in reversed(blocks_to_add):
                self.height_to_hash[
                    fetched_sub_block.height
                ] = fetched_sub_block.header_hash
                self.sub_blocks[fetched_sub_block.header_hash] = fetched_sub_block
                await self.coin_store.new_block(fetched_block)
                if fetched_sub_block.sub_epoch_summary_included is not None:
                    self.sub_epoch_summaries[fetched_sub_block.height] = fetched_sub_block.sub_epoch_summary_included

            # Changes the peak to be the new peak
            await self.block_store.set_peak(sub_block.header_hash)
            self.peak_height = sub_block.height
            return uint32(min(fork_h, 0))

        # This is not a heavier block than the heaviest we have seen, so we don't change the coin set
        return None

    def get_next_difficulty(self, header_hash: bytes32, new_slot: bool) -> uint64:
        assert header_hash in self.sub_blocks
        curr = self.sub_blocks[header_hash]

        ip_iters = calculate_ip_iters(self.constants, curr.ips, curr.required_iters)
        sp_iters = calculate_sp_iters(self.constants, curr.ips, curr.required_iters)
        return get_next_difficulty(
            self.constants,
            self.sub_blocks,
            self.height_to_hash,
            header_hash,
            curr.height,
            curr.deficit,
            uint64(curr.weight - self.sub_blocks[curr.prev_hash].weight),
            new_slot,
            uint128(curr.total_iters - ip_iters + sp_iters),
        )

    def get_next_slot_iters(self, header_hash: bytes32, new_slot: bool) -> uint64:
        return get_next_slot_iters(header_hash, self.sub_blocks, self.constants, self.height_to_hash, new_slot)

    async def pre_validate_blocks_mulpeakrocessing(
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

    async def validate_unfinished_block(
        self, block: UnfinishedBlock
    ) -> Tuple[Optional[uint64], Optional[Err]]:
        if block.header_hash in self.sub_blocks:
            return (
                self.sub_blocks[block.header_hash].required_iters,
                None,
            )  # Already validated and added

        if block.prev_header_hash not in self.sub_blocks and not block.height == 0:
            return None, Err.INVALID_PREV_BLOCK_HASH

        unfinished_header_block = UnfinishedHeaderBlock(
            block.finished_sub_slots,
            block.reward_chain_sub_block,
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage_sub_block,
            block.foliage_block,
            b"",
        )

        required_iters, error_code = await validate_unfinished_header_block(
            self.constants,
            self.sub_blocks,
            self.height_to_hash,
            unfinished_header_block,
            False,
        )

        if error_code is not None:
            return None, error_code

        error_code = await self.validate_block_body(block)

        if error_code is not None:
            return None, error_code

        return required_iters, None

    async def validate_block_body(
        self, block: Union[FullBlock, UnfinishedBlock]
    ) -> Optional[Err]:
        """
        This assumes the header block has been completely validated.
        Validates the transactions and body of the block. Returns None if everything
        validates correctly, or an Err if something does not validate.
        """

        # 1. For non block sub-blocks, foliage block, transaction filter, transactions info, and generator must be empty
        # If it is a sub block but not a block, there is no body to validate. Check that all fields are None
        if block.foliage_sub_block.foliage_block_hash is None:
            if (
                block.foliage_block is not None
                or block.transactions_info is not None
                or block.transactions_generator is not None
            ):
                return Err.NOT_BLOCK_BUT_HAS_DATA
            return None  # This means the sub-block is valid

        # 2. For blocks, foliage block, transaction filter, transactions info must not be empty
        if block.foliage_block is None or block.foliage_block.filter_hash is None or block.transactions_info is None:
            return Err.IS_BLOCK_BUT_NO_DATA

        # keeps track of the reward coins that need to be incorporated
        expected_reward_coins: Set[Coin] = set()

        # 3. The transaction info hash in the Foliage block must match the transaction info
        if block.foliage_block.transactions_info_hash != std_hash(
            block.transactions_info
        ):
            return Err.INVALID_TRANSACTIONS_INFO_HASH

        # 4. The foliage block hash in the foliage sub block must match the foliage block
        if block.foliage_sub_block.foliage_block_hash != std_hash(block.foliage_block):
            return Err.INVALID_FOLIAGE_BLOCK_HASH

        # 5. The prev generators root must be valid
        # TODO(straya): implement prev generators

        # 6. The generator root must be the tree-hash of the generator (or zeroes if no generator)
        if block.transactions_generator is not None:
            if (
                block.transactions_generator.get_tree_hash()
                != block.transactions_info.generator_root
            ):
                return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT
        else:
            if block.transactions_info.generator_root != bytes([0] * 32):
                return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT

        # 7. The reward claims must be valid for the previous sub-blocks, and current block fees
        pool_coin = create_pool_coin(
            block.height,
            block.foliage_sub_block.foliage_sub_block_data.pool_target.puzzle_hash,
            calculate_pool_reward(block.height),
        )
        farmer_coin = create_farmer_coin(
            block.height,
            block.foliage_sub_block.foliage_sub_block_data.farmer_reward_puzzle_hash,
            calculate_base_farmer_reward(block.height) + block.transactions_info.fees,
        )
        expected_reward_coins.add(pool_coin)
        expected_reward_coins.add(farmer_coin)

        if block.height > 0:
            # Add reward claims for all sub-blocks since the last block
            curr_sb = self.sub_blocks[block.prev_header_hash]
            while not curr_sb.is_block:
                expected_reward_coins.add(
                    create_pool_coin(curr_sb.height, curr_sb.pool_puzzle_hash, calculate_pool_reward(curr_sb.height))
                )
                expected_reward_coins.add(
                    create_farmer_coin(
                        curr_sb.height, curr_sb.farmer_puzzle_hash, calculate_base_farmer_reward(curr_sb.height)
                    )
                )
                curr_sb = self.sub_blocks[curr_sb.prev_hash]

        if set(block.transactions_info.reward_claims_incorporated) != expected_reward_coins:
            return Err.INVALID_REWARD_COINS

        removals: List[bytes32] = []
        coinbase_additions: List[Coin] = list(expected_reward_coins)
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
        root_error = validate_block_merkle_roots(
            block.foliage_block.additions_root,
            block.foliage_block.removals_root,
            additions + coinbase_additions,
            removals,
        )
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

        if filter_hash != block.foliage_block.filter_hash:
            return Err.INVALID_TRANSACTIONS_FILTER_HASH

        # 13. Check for duplicate outputs in additions
        addition_counter = collections.Counter(
            _.name() for _ in additions + coinbase_additions
        )
        for k, v in addition_counter.items():
            if v > 1:
                return Err.DUPLICATE_OUTPUT

        # 14. Check for duplicate spends inside block
        removal_counter = collections.Counter(removals)
        for k, v in removal_counter.items():
            if v > 1:
                return Err.DOUBLE_SPEND

        # 15. Check if removals exist and were not previously spent. (unspent_db + diff_store + this_block)
        if self.get_peak() is None or block.height == 0:
            fork_h: int = -1
        else:
            fork_h: int = find_fork_point_in_chain(
                self.sub_blocks, self.get_peak(), self.sub_blocks[block.prev_header_hash]
            )

        # Get additions and removals since (after) fork_h but not including this block
        additions_since_fork: Dict[bytes32, Tuple[Coin, uint32]] = {}
        removals_since_fork: Set[bytes32] = set()
        coinbases_since_fork: Dict[bytes32, uint32] = {}

        if block.height > 0:
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
                new_unspent: CoinRecord = CoinRecord(
                    rem_coin, block.height, uint32(0), False, False
                )
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
                        if (
                            block.height
                            < unspent.confirmed_block_index + self.coinbase_freeze
                        ):
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
                fee_list: List[ConditionVarPair] = npc.condition_dict[
                    ConditionOpcode.ASSERT_FEE
                ]
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
                block.height,
            )
            if error:
                return error
            for pk, m in pkm_pairs_for_conditions_dict(
                npc.condition_dict, npc.coin_name
            ):
                pairs_pks.append(pk)
                pairs_msgs.append(m)

        # 21. Verify aggregated signature
        # TODO: move this to pre_validate_blocks_multiprocessing so we can sync faster
        if not block.transactions_info.aggregated_signature:
            return Err.BAD_AGGREGATE_SIGNATURE

        if len(pairs_pks) == 0:
            if len(pairs_msgs) != 0 or block.transactions_info.aggregated_signature != G2Element.infinity():
                return Err.BAD_AGGREGATE_SIGNATURE
        else:
            # noinspection PyTypeChecker
            validates = AugSchemeMPL.aggregate_verify(
                pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature
            )
            if not validates:
                return Err.BAD_AGGREGATE_SIGNATURE

        return None


def get_next_slot_iters(
    header_hash: bytes32,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    constants: ConsensusConstants,
    height_to_hash: Dict[uint32, bytes32],
    new_slot: bool,
) -> uint64:
    assert header_hash in sub_blocks
    curr = sub_blocks[header_hash]

    ip_iters = calculate_ip_iters(constants, curr.ips, curr.required_iters)
    sp_iters = calculate_sp_iters(constants, curr.ips, curr.required_iters)
    return (
        get_next_ips(
            constants,
            sub_blocks,
            height_to_hash,
            header_hash,
            curr.height,
            curr.deficit,
            curr.ips,
            new_slot,
            uint128(curr.total_iters - ip_iters + sp_iters),
        )
        * constants.SLOT_TIME_TARGET
    )
