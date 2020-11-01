import copy
import os
import random
import shutil
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from blspy import G1Element, G2Element, AugSchemeMPL
from chiabip158 import PyBIP158
from chiavdf import prove

from src.cmds.init import create_default_chia_config, initialize_ssl
from src.cmds.plots import create_plots
from src.consensus import pot_iterations, block_rewards
from src.consensus.coinbase import (
    create_puzzlehash_for_pk,
    create_pool_coin,
    create_farmer_coin,
)
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_infusion_point_iters,
    calculate_iterations_quality,
    calculate_infusion_challenge_point_iters,
    calculate_min_iters_from_iterations,
    is_overflow_sub_block,
)
from src.full_node.difficulty_adjustment import (
    get_next_slot_iters,
    get_next_difficulty,
    get_next_ips,
)
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.full_node.sub_block_record import SubBlockRecord
from src.plotting.plot_tools import load_plots
from src.types.challenge_slot import ChallengeSlot
from src.types.classgroup import ClassgroupElement
from src.types.coin import hash_coin_list, Coin
from src.types.foliage import (
    FoliageBlock,
    FoliageSubBlock,
    TransactionsInfo,
    FoliageSubBlockData,
)
from src.types.full_block import FullBlock, additions_for_npc
from src.types.pool_target import PoolTarget
from src.types.program import Program
from src.types.proof_of_space import ProofOfSpace
from src.types.reward_chain_end_of_slot import RewardChainEndOfSlot, EndOfSlotProofs
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.vdf import VDFInfo, VDFProof
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint128, uint8
from src.util.keychain import Keychain, bytes_to_mnemonic
from src.util.merkle_set import MerkleSet
from src.util.path import mkdir
from src.util.wallet_tools import WalletTool
from src.wallet.derive_keys import (
    master_sk_to_farmer_sk,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk,
)


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    def __init__(
            self,
            root_path: Optional[Path] = None,
            real_plots: bool = False,
    ):
        self._tempdir = None
        if root_path is None:
            self._tempdir = tempfile.TemporaryDirectory()
            root_path = Path(self._tempdir.name)
        self.root_path = root_path
        self.real_plots = real_plots

        if not real_plots:
            create_default_chia_config(root_path)
            initialize_ssl(root_path)
            # No real plots supplied, so we will use the small test plots
            self.use_any_pos = True
            self.keychain = Keychain("testing-1.8.0", True)
            self.keychain.delete_all_keys()
            self.farmer_master_sk = self.keychain.add_private_key(
                bytes_to_mnemonic(std_hash(b"block_tools farmer key")), ""
            )
            self.pool_master_sk = self.keychain.add_private_key(
                bytes_to_mnemonic(std_hash(b"block_tools pool key")), ""
            )
            self.farmer_pk = master_sk_to_farmer_sk(self.farmer_master_sk).get_g1()
            self.pool_pk = master_sk_to_pool_sk(self.pool_master_sk).get_g1()
            self.chain_head = FullBlock
            self.tx_height = None
            self.prev_foliage_block = None
            self.num_sub_blocks_overflow: uint8 = uint8(0)
            self.prev_subepoch_summary_hash: Optional[SubEpochSummary] = None

            plot_dir = get_plot_dir()
            mkdir(plot_dir)
            temp_dir = plot_dir / "tmp"
            mkdir(temp_dir)
            args = Namespace()
            # Can't go much lower than 18, since plots start having no solutions
            args.size = 18
            # Uses many plots for testing, in order to guarantee proofs of space at every height
            args.num = 40
            args.buffer = 100
            args.farmer_public_key = bytes(self.farmer_pk).hex()
            args.pool_public_key = bytes(self.pool_pk).hex()
            args.tmp_dir = temp_dir
            args.tmp2_dir = plot_dir
            args.final_dir = plot_dir
            args.plotid = None
            args.memo = None
            args.buckets = 0
            args.stripe_size = 2000
            args.num_threads = 0
            test_private_keys = [AugSchemeMPL.key_gen(std_hash(bytes([i]))) for i in range(args.num)]
            try:
                # No datetime in the filename, to get deterministic filenames and not replot
                create_plots(
                    args,
                    root_path,
                    use_datetime=False,
                    test_private_keys=test_private_keys,
                )
            except KeyboardInterrupt:
                shutil.rmtree(plot_dir, ignore_errors=True)
                sys.exit(1)
        else:
            initialize_ssl(root_path)
            self.keychain = Keychain()
            self.use_any_pos = False
            sk_and_ent = self.keychain.get_first_private_key()
            assert sk_and_ent is not None
            self.farmer_master_sk = sk_and_ent[0]
            self.pool_master_sk = sk_and_ent[0]

        self.farmer_ph = create_puzzlehash_for_pk(master_sk_to_wallet_sk(self.farmer_master_sk, uint32(0)).get_g1())
        self.pool_ph = create_puzzlehash_for_pk(master_sk_to_wallet_sk(self.pool_master_sk, uint32(0)).get_g1())

        self.all_sks = self.keychain.get_all_private_keys()
        self.pool_pubkeys: List[G1Element] = [master_sk_to_pool_sk(sk).get_g1() for sk, _ in self.all_sks]
        self.curr_slot = 1
        self.curr_epoch = 1
        self.curr_sub_epoch = 1
        self.sub_blocks: Optional[Dict[bytes32, SubBlockRecord]] = None
        self.height_to_hash: Optional[Dict[uint32, bytes32]] = None
        self.finished_slots: Optional[List[Tuple[ChallengeSlot, RewardChainEndOfSlot, EndOfSlotProofs]]] = None
        self.ips: uint64 = uint64(0)
        self.deficit = 0
        self.last_challenge_proof_of_space = None
        self.curr_proof_of_space = None
        self.quality: Optional[bytes32] = None
        self.plot_pk = None
        self.curr_slot_iters = 0
        self.next_slot_iters = 0
        self.difficulty: Optional[uint128] = None
        self.previous_generators_root: bytes32 = None

        farmer_pubkeys: List[G1Element] = [master_sk_to_farmer_sk(sk).get_g1() for sk, _ in self.all_sks]
        self.match_str = None
        if len(self.pool_pubkeys) == 0 or len(farmer_pubkeys) == 0:
            raise RuntimeError("Keys not generated. Run `chia generate keys`")
        _, self.plots, _, _ = load_plots({}, {}, farmer_pubkeys, self.pool_pubkeys, self.match_str, root_path)
        self._config = load_config(self.root_path, "config.yaml")

    @property
    def config(self) -> Dict:
        return copy.deepcopy(self._config)

    def get_plot_signature(self, m: bytes32, plot_pk: G1Element) -> Optional[G2Element]:
        """
        Returns the plot signature of the header data.
        """
        farmer_sk = master_sk_to_farmer_sk(self.all_sks[0][0])
        for _, plot_info in self.plots.items():
            agg_pk = ProofOfSpace.generate_plot_public_key(plot_info.local_sk.get_g1(), plot_info.farmer_public_key)
            if agg_pk == plot_pk:
                harv_share = AugSchemeMPL.sign(plot_info.local_sk, m, agg_pk)
                farm_share = AugSchemeMPL.sign(farmer_sk, m, agg_pk)
                return AugSchemeMPL.aggregate([harv_share, farm_share])

        return None

    def get_pool_key_signature(self, pool_target: PoolTarget, pool_pk: G1Element) -> Optional[G2Element]:
        for sk, _ in self.all_sks:
            sk_child = master_sk_to_pool_sk(sk)
            if sk_child.get_g1() == pool_pk:
                return AugSchemeMPL.sign(sk_child, bytes(pool_target))
        return None

    def get_farmer_wallet_tool(self) -> WalletTool:
        return WalletTool(self.farmer_master_sk)

    def get_pool_wallet_tool(self) -> WalletTool:
        return WalletTool(self.pool_master_sk)

    def handle_end_of_epoch(self, new_slot, prev_block, test_constants):
        if len(self.sub_blocks.keys()) == 32256 * (self.curr_epoch + 1):
            # new difficulty
            self.difficulty = get_next_difficulty(
                test_constants,
                self.sub_blocks,
                self.height_to_hash,
                prev_block.header_hash,
                new_slot,
            )
            # new iterations per slot
            self.ips = get_next_ips(
                test_constants,
                self.height_to_hash,
                self.sub_blocks,
                prev_block.header_hash,
                new_slot,
            )

    def handle_end_of_sub_epoch(self, prev_block):
        if len(self.sub_blocks.keys()) == 384 * (self.curr_sub_epoch + 1):
            # update sub_epoch_summery
            sub_epoch_summery = SubEpochSummary(
                self.prev_subepoch_summary_hash,
                prev_block.reward_chain_sub_block.get_hash(),
                self.num_sub_blocks_overflow,
                self.difficulty,
                self.ips,
            )
            self.prev_subepoch_summary_hash = std_hash(sub_epoch_summery)

    def get_consecutive_blocks(
        self,
        test_constants: ConsensusConstants,
        num_blocks: int,
        block_list: List[FullBlock] = None,
        reward_puzzlehash: bytes32 = None,
        fees: uint64 = uint64(0),
        transaction_data_at_height: Dict[int, Tuple[Program, G2Element]] = None,
        seed: bytes = b"",
    ) -> List[FullBlock]:
        if transaction_data_at_height is None:
            transaction_data_at_height = {}
        if block_list is None or len(block_list) == 0:
            genesis = self.create_genesis_block(test_constants, seed)
            self.difficulty = test_constants.DIFFICULTY_STARTING
            self.ips = uint64(test_constants.IPS_STARTING)
            self.chain_head = genesis
            self.deficit = 5
            block_list = List[FullBlock]
            block_list.append(genesis)
            self.prev_foliage_block = genesis.foliage_block
        else:
            assert block_list[-1].proof_of_time is not None
            curr_min_iters = calculate_min_iters_from_iterations(
                block_list[-1].proof_of_space,
                difficulty,
                block_list[-1].proof_of_time.number_of_iterations,
                test_constants.NUMBER_ZERO_BITS_CHALLENGE_SIG,
            )

        starting_height: int = block_list[-1].height + 1
        timestamp: uint64 = block_list[-1].header.data.timestamp
        end_of_slot: Optional[RewardChainEndOfSlot] = None
        transactions: Optional[Program] = None
        aggsig: Optional[G2Element] = None
        for next_height in range(starting_height, starting_height + num_blocks):
            if next_height in transaction_data_at_height:
                transactions, aggsig = transaction_data_at_height[next_height]

            # update values
            prev_block = block_list[-1]
            self.sub_blocks[prev_block.get_hash()] = prev_block.get_sub_block_record()
            self.height_to_hash[prev_block.height] = prev_block.get_hash()

            number_iters: uint64 = pot_iterations.calculate_iterations(
                test_constants, self.last_challenge_proof_of_space, self.difficulty
            )

            new_slot = False
            # check is new slot
            if number_iters > self.next_slot_iters:
                new_slot = True
                self.curr_slot_iters = self.next_slot_iters
                self.next_slot_iters = get_next_slot_iters(
                    test_constants,
                    self.height_to_hash,
                    self.sub_blocks,
                    prev_block.reward_chain_sub_block.get_hash(),
                    True,
                )

                challnge = self.chain_head.finished_slots[-1][0].get_hash()

                output = get_vdf_output(
                    challnge,
                    ClassgroupElement.get_default_element(),
                    test_constants.DISCRIMINANT_SIZE_BITS,
                    self.curr_slot_iters,
                )
                end_of_slot_vdf = VDFInfo(
                    challnge,
                    ClassgroupElement.get_default_element(),
                    self.curr_slot_iters,
                    output,
                )

                # restart overflow count
                self.num_sub_blocks_overflow: uint8 = uint8(0)

                challenge_slot = ChallengeSlot(
                    self.prev_subepoch_summary_hash,
                    self.last_challenge_proof_of_space,
                    prev_block.reward_chain_sub_block.challenge_chain_icp_vdf,
                    prev_block.reward_chain_sub_block.challenge_chain_icp_sig,
                    prev_block.reward_chain_sub_block.challenge_chain_ip_vdf,
                    end_of_slot_vdf,
                )

                rc_eos = RewardChainEndOfSlot(end_of_slot_vdf, std_hash(challenge_slot), self.deficit)

                end_slot_proofs = get_end_of_slot_proofs(self.curr_slot_iters, challnge, test_constants)
                self.finished_slots.append(Tuple[challenge_slot, rc_eos, end_slot_proofs])

                # proof of space
                (
                    self.curr_proof_of_space,
                    self.quality,
                    self.plot_pk,
                ) = self.get_prams_from_plots(test_constants, std_hash(end_of_slot), seed)

                self.quality = self.curr_proof_of_space.last_challenge_proof_of_space.verify_and_get_quality_string(
                    test_constants,
                    prev_block.reward_chain_sub_block.challenge_chain_icp_vdf.output.get_hash(),
                    prev_block.reward_chain_sub_block.challenge_chain_icp_sig,
                )

            # if valid PoSpace
            if self.quality is not None:
                required_iters: uint64 = calculate_iterations_quality(
                    self.quality, self.curr_proof_of_space.size, self.difficulty
                )

                # if we have deficit, subtract one
                if self.deficit > 0:
                    self.deficit = self.deficit - 1

                # if overflow update num of overflow blocks
                overflow = False
                if is_overflow_sub_block(test_constants, self.ips, required_iters):
                    self.num_sub_blocks_overflow = self.num_sub_blocks_overflow + 1
                    overflow = True

                block = self.create_next_block(
                    test_constants,
                    fees,
                    prev_block,
                    transactions,
                    aggsig,
                    timestamp,
                    reward_puzzlehash,
                    new_slot,
                    required_iters,
                    overflow,
                )

                # zero finish slots
                self.finished_slots = List[Tuple[ChallengeSlot, RewardChainEndOfSlot, EndOfSlotProofs]]

                if new_slot and self.deficit == 0:
                    # new challenge chain block, zero sub block list
                    self.sub_blocks = Dict[bytes32, SubBlockRecord]
                    # new challenge chain block, reset deficit
                    self.deficit = 5
                    self.last_challenge_proof_of_space = self.curr_proof_of_space

                block_list.append(block)

            self.handle_end_of_sub_epoch(prev_block)
            self.handle_end_of_epoch(new_slot, prev_block, test_constants)

        return block_list

    def create_genesis_block(self, test_constants: ConsensusConstants, seed: bytes32) -> FullBlock:
        """
        Creates the genesis block with the specified details.
        """

        (self.last_challenge_proof_of_space, self.quality, self.plot_pk,) = self.get_prams_from_plots(
            test_constants, test_constants.FIRST_RC_CHALLENGE, test_constants.DIFFICULTY_STARTING
        )

        required_iters: uint64 = calculate_iterations_quality(
            self.quality, self.last_challenge_proof_of_space.size, test_constants.DIFFICULTY_STARTING
        )

        icp_iters: uint64 = calculate_icp_iters(test_constants, uint64(test_constants.IPS_STARTING), required_iters)

        ip_iters: uint64 = calculate_ip_iters(test_constants, uint64(test_constants.IPS_STARTING), required_iters)
        number_iters: uint64 = pot_iterations.calculate_iterations(
            test_constants, self.last_challenge_proof_of_space, self.difficulty
        )

        cc_icp_output, cc_ip_output, rc_icp_output, rc_ip_output = get_vdf_outputs(
            number_iters,
            test_constants.FIRST_CC_CHALLENGE,
            test_constants.FIRST_RC_CHALLENGE,
            ClassgroupElement.get_default_element(),
            test_constants,
        )

        cc_icp_vdf = VDFInfo(
            test_constants.FIRST_CC_CHALLENGE,
            ClassgroupElement.get_default_element(),
            ip_iters,
            cc_icp_output,
        )

        cc_ip_vdf = (
            VDFInfo(
                test_constants.FIRST_CC_CHALLENGE,
                ClassgroupElement.get_default_element(),
                icp_iters,
                cc_ip_output,
            ),
        )

        rc_icp_vdf = (
            VDFInfo(
                test_constants.FIRST_RC_CHALLENGE,
                ClassgroupElement.get_default_element(),
                ip_iters,
                rc_icp_output,
            ),
        )
        rc_ip_vdf = (
            VDFInfo(
                test_constants.FIRST_RC_CHALLENGE,
                ClassgroupElement.get_default_element(),
                icp_iters,
                rc_ip_output,
            ),
        )

        cc_icp_proof = VDFProof(witness=cc_icp_output.get_hash(), witness_type=uint8(1))
        cc_ip_proof = VDFProof(witness=cc_ip_output.get_hash(), witness_type=uint8(1))
        rc_icp_proof = VDFProof(witness=rc_icp_output.get_hash(), witness_type=uint8(1))
        rc_ip_proof = VDFProof(witness=rc_ip_output.get_hash(), witness_type=uint8(1))
        rc_icp_sig: G2Element = self.get_plot_signature(None, self.plot_pk)
        cc_icp_signature = self.get_plot_signature(None, self.plot_pk)

        rc_sub_block = RewardChainSubBlock(
            test_constants.DIFFICULTY_STARTING,
            number_iters,
            self.last_challenge_proof_of_space,
            cc_ip_vdf,
            cc_icp_vdf,
            cc_icp_signature,
            rc_icp_vdf,
            rc_icp_sig,
            rc_ip_vdf,
        )

        # todo genesis foliage

        full_block: FullBlock = FullBlock(
            finished_slots=None,
            challenge_chain_icp_proof=cc_icp_proof,
            challenge_chain_ip_proof=cc_ip_proof,
            reward_chain_icp_proof=rc_icp_proof,
            reward_chain_ip_proof=rc_ip_proof,
            reward_chain_sub_block=rc_sub_block,
            # foliage_sub_block=foliage_sub_block,
            # foliage_block=foliage_block,
        )

        return full_block

    def create_next_block(
        self,
        test_constants: ConsensusConstants,
        fees: uint64,
        head: FullBlock,
        transactions: Optional[Program],
        aggsig: Optional[G2Element],
        timestamp: uint64,
        reward_puzzlehash: bytes32,
        new_slot: bool,
        required_iters: uint64,
        overflow: bool,
    ) -> (FullBlock, bool):
        """
        Creates the next block with the specified details.
        """

        # use default element if new slot
        if new_slot:
            cc_vdf_input = ClassgroupElement.get_default_element()
            rc_vdf_challenge = self.chain_head.finished_slots[-1][1].get_hash()
        else:
            cc_vdf_input = head.reward_chain_sub_block.challenge_chain_ip_vdf.output
            rc_vdf_challenge = self.sub_blocks[self.chain_head.prev_header_hash]

        number_iters: uint64 = pot_iterations.calculate_iterations(
            test_constants, self.last_challenge_proof_of_space, self.difficulty
        )

        cc_icp_output, cc_ip_output, rc_icp_output, rc_ip_output = get_vdf_outputs(
            number_iters, std_hash(new_slot), cc_vdf_input, test_constants
        )

        icp_iters: uint64 = calculate_icp_iters(test_constants, self.ips, required_iters)
        ip_iters: uint64 = calculate_ip_iters(test_constants, self.ips, required_iters)

        cc_icp_vdf: VDFInfo = get_challenge_chain_icp_vdf(head, icp_iters, cc_vdf_input, cc_icp_output)
        cc_ip_vdf: VDFInfo = get_challenge_chain_ip_vdf(head, ip_iters, cc_vdf_input, cc_ip_output)
        cc_icp_signature: G2Element = self.get_plot_signature(self.chain_head, self.plot_pk)

        rc_icp_vdf: VDFInfo = get_reward_chain_icp_vdf(rc_vdf_challenge, icp_iters, rc_icp_output)
        rc_ip_vdf: VDFInfo = get_reward_chain_ip_vdf(rc_vdf_challenge, ip_iters, rc_ip_output)
        rc_icp_sig: G2Element = self.get_plot_signature(head, self.plot_pk)

        reward_chain_sub_block = RewardChainSubBlock(
            head.weight + self.difficulty,
            number_iters,
            self.curr_proof_of_space,
            cc_ip_vdf,
            cc_icp_vdf,
            cc_icp_signature,
            rc_icp_vdf,
            rc_icp_sig,
            rc_ip_vdf,
        )

        foliage_sub_block, foliage_block, transactions_info, transactions_generator = self.create_foliage(
            fees,
            aggsig,
            transactions,
            block_rewards,  # todo
            head,
            timestamp,
            head.reward_chain_sub_block.get_unfinished().get_hash(),
            is_transaction_block(
                overflow,
                number_iters,
                ip_iters,
                icp_iters,
                self.curr_slot_iters,
                head.total_iters,
            ),
            reward_puzzlehash,
            self.curr_proof_of_space,
        )

        self.prev_foliage_block = foliage_block
        self.previous_generators_root = transactions_generator.get_tree_hash()

        full_block: FullBlock = FullBlock(
            finished_slots=self.finished_slots,
            challenge_chain_ip_proof=VDFProof(witness=cc_ip_output.get_hash(), witness_type=uint8(1)),
            challenge_chain_icp_proof=VDFProof(witness=cc_icp_output.get_hash(), witness_type=uint8(1)),
            reward_chain_icp_proof=VDFProof(witness=rc_icp_output.get_hash(), witness_type=uint8(1)),
            reward_chain_ip_proof=VDFProof(witness=rc_ip_output.get_hash(), witness_type=uint8(1)),
            reward_chain_sub_block=reward_chain_sub_block,
            foliage_sub_block=foliage_sub_block,
            foliage_block=foliage_block,
            transactions_info=transactions_info,
            transactions_generator=transactions_generator,
        )

        return full_block

    def create_foliage(
        self,
        fees: uint64,
        aggsig: G2Element,
        transactions: Program,
        reward_claims_incorporated: List[Coin],
        prev_block: FullBlock,
        reward_block_hash: bytes32,
        timestamp: uint64,
        unfinished_reward_block_hash: bytes32,
        is_transaction: bool,
        proof_of_space: ProofOfSpace,
        reward_puzzlehash: bytes32 = None,
    ) -> (FoliageSubBlock, FoliageBlock, TransactionsInfo, Program):

        # Use the extension data to create different blocks based on header hash
        # extension_data: bytes32 = bytes32([random.randint(0, 255) for _ in range(32)])  # todo start from same seed always
        height = uint32(len(self.height_to_hash))

        extension_data = bytes32("todo")

        cost: uint64 = uint64(0)

        fee_reward: uint64 = uint64(block_rewards.calculate_base_farmer_reward(height) + fees)

        # Create filter
        byte_array_tx: List[bytes32] = []
        tx_additions: List[Coin] = []
        tx_removals: List[bytes32] = []
        if transactions:
            error, npc_list, _ = get_name_puzzle_conditions(transactions)
            additions: List[Coin] = additions_for_npc(npc_list)
            for coin in additions:
                tx_additions.append(coin)
                byte_array_tx.append(bytearray(coin.puzzle_hash))
            for npc in npc_list:
                tx_removals.append(npc.coin_name)
                byte_array_tx.append(bytearray(npc.coin_name))
        farmer_ph = self.farmer_ph
        pool_ph = self.pool_ph
        if reward_puzzlehash is not None:
            farmer_ph = reward_puzzlehash
            pool_ph = reward_puzzlehash

        byte_array_tx.append(bytearray(farmer_ph))
        byte_array_tx.append(bytearray(pool_ph))
        bip158: PyBIP158 = PyBIP158(byte_array_tx)
        encoded = bytes(bip158.GetEncoded())

        removal_merkle_set = MerkleSet()
        addition_merkle_set = MerkleSet()

        # Create removal Merkle set
        for coin_name in tx_removals:
            removal_merkle_set.add_already_hashed(coin_name)

        # Create addition Merkle set
        puzzlehash_coin_map: Dict[bytes32, List[Coin]] = {}
        pool_coin = create_pool_coin(height, reward_puzzlehash, fee_reward)
        farmer_coin = create_farmer_coin(height, reward_puzzlehash, fee_reward)

        for coin in tx_additions + [pool_coin, farmer_coin]:
            if coin.puzzle_hash in puzzlehash_coin_map:
                puzzlehash_coin_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coin_map[coin.puzzle_hash] = [coin]

        # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
        for puzzle, coins in puzzlehash_coin_map.items():
            addition_merkle_set.add_already_hashed(puzzle)
            addition_merkle_set.add_already_hashed(hash_coin_list(coins))

        additions_root = addition_merkle_set.get_root()
        removals_root = removal_merkle_set.get_root()

        generator_hash = transactions.get_tree_hash() if transactions is not None else bytes32([0] * 32)
        filter_hash = std_hash(encoded)

        pool_target = PoolTarget(pool_ph, uint32(height))
        pool_target_signature = self.get_pool_key_signature(pool_target, proof_of_space.pool_public_key)
        assert pool_target_signature is not None
        final_aggsig: G2Element = pool_target_signature
        if aggsig is not None:
            final_aggsig = AugSchemeMPL.aggregate([final_aggsig, aggsig])

        foliage_sub_block_data = FoliageSubBlockData(
            unfinished_reward_block_hash,
            pool_target,
            pool_target_signature,
            farmer_ph,
            extension_data,
        )

        signed_foliage_sub_block_data: G2Element = self.get_plot_signature(foliage_sub_block_data, self.plot_pk)
        signed_prev_foliage_sub_block: G2Element = self.get_plot_signature(prev_block.foliage_block, self.plot_pk)

        foliage_sub_block = FoliageSubBlock(
            prev_block.get_hash(),
            reward_block_hash,
            foliage_sub_block_data,
            signed_foliage_sub_block_data,
            prev_block.foliage_block.get_hash(),
            signed_prev_foliage_sub_block,
        )

        transactions_info_hash = None
        if is_transaction:
            transactions_info_hash = TransactionsInfo(
                self.previous_generators_root, generator_hash, final_aggsig, fees, cost, reward_claims_incorporated
            )

        foliage_block = FoliageBlock(
            prev_block.get_hash(),
            timestamp,
            filter_hash,
            additions_root,
            removals_root,
            transactions_info_hash,
        )

        return foliage_sub_block, foliage_block, generator_hash, transactions

    def get_prams_from_plots(
        self, test_constants, challenge_hash, seed
    ) -> (ClassgroupElement, uint64, ProofOfSpace, bytes32, G2Element):
        selected_plot_info = None
        selected_proof_index = 0
        selected_quality: Optional[bytes] = None
        plots = [pinfo for _, pinfo in sorted(list(self.plots.items()), key=lambda x: str(x[0]))]
        random.seed(seed)
        for i in range(len(plots) * 3):
            # Allow passing in seed, to create reorgs and different chains
            seeded_pn = random.randint(0, len(plots) - 1)
            plot_info = plots[seeded_pn]
            plot_id = plot_info.prover.get_id()
            ccp = ProofOfSpace.can_create_proof(test_constants, plot_id, challenge_hash, None, None)
            if not ccp:
                continue
            qualities = plot_info.prover.get_qualities_for_challenge(challenge_hash)
            if len(qualities) > 0:
                selected_plot_info = plot_info
                selected_quality = qualities[0]
                # break list.append(Tuple[selected_plot_info,selected_quality])

        # for each pos :
        assert selected_plot_info is not None
        if selected_quality is None:
            raise RuntimeError("No proofs for this challenge")

        proof_xs: bytes = selected_plot_info.prover.get_full_proof(challenge_hash, selected_proof_index)

        plot_pk = ProofOfSpace.generate_plot_public_key(
            selected_plot_info.local_sk.get_g1(),
            selected_plot_info.farmer_public_key,
        )
        proof_of_space: ProofOfSpace = ProofOfSpace(
            challenge_hash,
            selected_plot_info.pool_public_key,
            plot_pk,
            selected_plot_info.prover.get_size(),
            proof_xs,
        )

        number_iters: uint64 = pot_iterations.calculate_iterations(test_constants, proof_of_space, self.difficulty)

        if self.real_plots:
            print(f"Performing {number_iters} VDF iterations")

        return proof_of_space, selected_quality, plot_pk


def get_end_of_slot_proofs(curr_slot_iters, challnge, test_constants):
    challenge_chain_slot_proof = get_vdf_proof(
        challnge,
        ClassgroupElement.get_default_element(),
        curr_slot_iters,
        test_constants.DISCRIMINANT_SIZE_BITS,
    )
    reward_chain_slot_proof = get_vdf_proof(
        challnge,
        ClassgroupElement.get_default_element(),
        curr_slot_iters,
        test_constants.DISCRIMINANT_SIZE_BITS,
    )
    end_slot_proofs = EndOfSlotProofs(challenge_chain_slot_proof, reward_chain_slot_proof)
    return end_slot_proofs


def get_vdf_proof(
    challenge_hash: bytes32, input: ClassgroupElement, number_iters, discriminant_size_bits: int
) -> VDFProof:
    output = get_vdf_output(input, challenge_hash, discriminant_size_bits, number_iters)
    return VDFProof(witness=output.get_hash(), witness_type=uint8(1))


def get_vdf_output(
    input: ClassgroupElement, challenge_hash: bytes32, discriminant_size_bits: int, number_iters: uint64
) -> ClassgroupElement:
    return prove(challenge_hash, input.a, input.b, discriminant_size_bits, number_iters)


def get_vdf_outputs(
    number_iters: uint64,
    cc_challenge: bytes32,
    rc_challenge: bytes32,
    cc_vdf_Input: ClassgroupElement,
    test_constants,
):
    cc_icp_output = get_vdf_output(
        cc_challenge,
        cc_vdf_Input,
        test_constants.DISCRIMINANT_SIZE_BITS,
        number_iters,
    )
    cc_ip_output = get_vdf_output(
        cc_challenge,
        cc_vdf_Input,
        test_constants.DISCRIMINANT_SIZE_BITS,
        number_iters,
    )

    rc_icp_output = get_vdf_output(
        ClassgroupElement.get_default_element(),
        rc_challenge,
        test_constants.DISCRIMINANT_SIZE_BITS,
        number_iters,
    )

    rc_ip_output = get_vdf_output(
        ClassgroupElement.get_default_element(),
        rc_challenge,
        test_constants.DISCRIMINANT_SIZE_BITS,
        number_iters,
    )
    return cc_icp_output, cc_ip_output, rc_icp_output, rc_ip_output


def get_plot_dir():
    cache_path = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/"))) / "test-plots"
    mkdir(cache_path)
    return cache_path


def get_challenge_chain_icp_vdf(
    block: FullBlock, icp_iters: uint64, input: ClassgroupElement, output: ClassgroupElement
) -> Optional[VDFInfo]:
    if icp_iters == 0:
        return None
    cc_vdf_challenge: bytes32 = block.finished_slots[-1][0].get_hash()
    return VDFInfo(
        challenge_hash=cc_vdf_challenge,
        input=input,
        number_of_iterations=icp_iters,
        output=output,
    )


def get_reward_chain_icp_vdf(challenge: bytes32, icp_iters: uint64, output: ClassgroupElement) -> Optional[VDFInfo]:
    if icp_iters == 0:
        return None
    return VDFInfo(
        challenge_hash=challenge,
        input=ClassgroupElement.get_default_element(),
        number_of_iterations=icp_iters,
        output=output,
    )


def get_challenge_chain_ip_vdf(
    challenge: bytes32, ip_iters: uint64, input: ClassgroupElement, output: ClassgroupElement
) -> VDFInfo:
    return VDFInfo(
        challenge_hash=challenge,
        input=input,
        number_of_iterations=ip_iters,
        output=output,
    )


def get_reward_chain_ip_vdf(block: FullBlock, ip_iters: uint64, output: ClassgroupElement) -> VDFInfo:
    cc_vdf_challenge: bytes32 = block.finished_slots[-1][1].get_hash()
    return VDFInfo(
        challenge_hash=cc_vdf_challenge,
        input=ClassgroupElement.get_default_element(),
        number_of_iterations=ip_iters,
        output=output,
    )


def is_transaction_block(overflow: bool, total_iters, ip_iters, icp_iters, slot_iters, curr_total_iters) -> bool:
    # The first sub-block to have an icp > the last block's infusion iters, is a block
    if overflow:
        our_icp_total_iters: uint128 = uint128(total_iters - ip_iters + icp_iters - slot_iters)
    else:
        our_icp_total_iters: uint128 = uint128(total_iters - ip_iters + icp_iters)
    return our_icp_total_iters > curr_total_iters
