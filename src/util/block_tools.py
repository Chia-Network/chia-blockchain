import copy
import os
import random
import shutil
import sys
import tempfile
import time
from argparse import Namespace
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from blspy import G1Element, G2Element, AugSchemeMPL, PrivateKey
from chiabip158 import PyBIP158
from chiavdf import prove

from src.cmds.init import create_default_chia_config, initialize_ssl
from src.cmds.plots import create_plots
from src.consensus import pot_iterations, block_rewards
from src.consensus.block_rewards import calculate_pool_reward
from src.consensus.coinbase import (
    create_puzzlehash_for_pk,
    create_pool_coin,
    create_farmer_coin,
)
from src.consensus.constants import ConsensusConstants
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.consensus.pot_iterations import (
    calculate_infusion_point_iters,
    calculate_iterations_quality,
    calculate_sp_iters,
    is_overflow_sub_block,
    calculate_slot_iters,
)
from src.full_node.difficulty_adjustment import (
    get_next_difficulty,
    get_next_ips,
)
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.full_node.sub_block_record import SubBlockRecord
from src.plotting.plot_tools import load_plots, PlotInfo
from src.types.slots import InfusedChallengeChainSubSlot, ChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
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
from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.vdf import VDFInfo, VDFProof
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint128, uint8, int512
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
            args.num = 80
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

        self.farmer_ph: bytes32 = create_puzzlehash_for_pk(
            master_sk_to_wallet_sk(self.farmer_master_sk, uint32(0)).get_g1()
        )
        self.pool_ph: bytes32 = create_puzzlehash_for_pk(
            master_sk_to_wallet_sk(self.pool_master_sk, uint32(0)).get_g1()
        )

        self.all_sks: List[PrivateKey] = [sk for sk, _ in self.keychain.get_all_private_keys()]
        self.pool_pubkeys: List[G1Element] = [master_sk_to_pool_sk(sk).get_g1() for sk in self.all_sks]
        self.curr_slot: uint32 = uint32(1)
        self.curr_epoch: uint32 = uint32(1)
        self.curr_sub_epoch: uint32 = uint32(1)
        self.sub_blocks: Optional[Dict[bytes32, SubBlockRecord]] = None
        self.height_to_hash: Optional[Dict[uint32, bytes32]] = None
        self.finished_sub_slots: Optional[List[EndOfSubSlotBundle]] = None
        self.ips: uint64 = uint64(0)
        self.deficit: uint8 = uint8(0)
        self.last_challenge_proof_of_space: Optional[ProofOfSpace] = None
        self.curr_proof_of_space: Optional[ProofOfSpace] = None
        self.quality: Optional[bytes32] = None
        self.plot_pk: Optional[G1Element] = None
        self.curr_slot_iters: uint64 = uint64(0)
        self.next_slot_iters: uint64 = uint64(0)
        self.difficulty: Optional[uint64] = None
        self.previous_generators_root: Optional[bytes32] = None

        farmer_pubkeys: List[G1Element] = [master_sk_to_farmer_sk(sk).get_g1() for sk in self.all_sks]
        if len(self.pool_pubkeys) == 0 or len(farmer_pubkeys) == 0:
            raise RuntimeError("Keys not generated. Run `chia generate keys`")

        _, loaded_plots, _, _ = load_plots({}, {}, farmer_pubkeys, self.pool_pubkeys, None, root_path)
        self.plots: Dict[Path, PlotInfo] = loaded_plots
        self._config = load_config(self.root_path, "config.yaml")

    @property
    def config(self) -> Dict:
        return copy.deepcopy(self._config)

    def get_plot_signature(self, m: bytes32, plot_pk: G1Element) -> Optional[G2Element]:
        """
        Returns the plot signature of the header data.
        """
        farmer_sk = master_sk_to_farmer_sk(self.all_sks[0])
        for _, plot_info in self.plots.items():
            agg_pk = ProofOfSpace.generate_plot_public_key(plot_info.local_sk.get_g1(), plot_info.farmer_public_key)
            if agg_pk == plot_pk:
                harv_share = AugSchemeMPL.sign(plot_info.local_sk, m, agg_pk)
                farm_share = AugSchemeMPL.sign(farmer_sk, m, agg_pk)
                return AugSchemeMPL.aggregate([harv_share, farm_share])

        return None

    def get_pool_key_signature(self, pool_target: PoolTarget, pool_pk: G1Element) -> Optional[G2Element]:
        for sk in self.all_sks:
            sk_child = master_sk_to_pool_sk(sk)
            if sk_child.get_g1() == pool_pk:
                return AugSchemeMPL.sign(sk_child, bytes(pool_target))
        return None

    def get_farmer_wallet_tool(self) -> WalletTool:
        return WalletTool(self.farmer_master_sk)

    def get_pool_wallet_tool(self) -> WalletTool:
        return WalletTool(self.pool_master_sk)

    def handle_end_of_epoch(self, new_slot, prev_block, constants):
        if len(self.sub_blocks.keys()) == constants.EPOCH_SUB_BLOCKS * (self.curr_epoch + 1):
            # new difficulty
            self.difficulty = get_next_difficulty(
                constants,
                self.sub_blocks,
                self.height_to_hash,
                prev_block.header_hash,
                new_slot,
            )
            # new iterations per slot
            self.ips = get_next_ips(
                constants,
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

    # def get_consecutive_blocks(
    #     self,
    #     constants: ConsensusConstants,
    #     num_blocks: int,
    #     block_list: List[FullBlock] = None,
    #     reward_puzzlehash: bytes32 = None,
    #     fees: uint64 = uint64(0),
    #     transaction_data_at_height: Dict[int, Tuple[Program, G2Element]] = None,
    #     seed: bytes = b"",
    # ) -> List[FullBlock]:
    #     if transaction_data_at_height is None:
    #         transaction_data_at_height = {}
    #     if block_list is None or len(block_list) == 0:
    #         self.difficulty = constants.DIFFICULTY_STARTING
    #         self.ips = uint64(constants.IPS_STARTING)
    #         genesis = self.create_genesis_block(constants, fees, seed)
    #         self.chain_head = genesis
    #         self.deficit = 5
    #         block_list: List[FullBlock] = [genesis]
    #         self.prev_foliage_block = genesis.foliage_block
    #     else:
    #         assert block_list[-1].proof_of_time is not None
    #
    #     starting_height: int = block_list[-1].height + 1
    #     timestamp: uint64 = block_list[-1].header.data.timestamp
    #     end_of_slot: Optional[RewardChainSubSlot] = None
    #     transactions: Optional[Program] = None
    #     aggsig: Optional[G2Element] = None
    #     for next_height in range(starting_height, starting_height + num_blocks):
    #         if next_height in transaction_data_at_height:
    #             transactions, aggsig = transaction_data_at_height[next_height]
    #
    #         # update values
    #         prev_block = block_list[-1]
    #         self.sub_blocks[prev_block.get_hash()] = prev_block.get_sub_block_record()
    #         self.height_to_hash[prev_block.height] = prev_block.get_hash()
    #
    #         number_iters: uint64 = pot_iterations.calculate_iterations(
    #             constants, self.last_challenge_proof_of_space, self.difficulty
    #         )
    #
    #         new_slot = False
    #         # check is new slot
    #         if number_iters > self.next_slot_iters:
    #             new_slot = True
    #             self.curr_slot_iters = self.next_slot_iters
    #             self.next_slot_iters = get_next_slot_iters(
    #                 constants,
    #                 self.height_to_hash,
    #                 self.sub_blocks,
    #                 prev_block.reward_chain_sub_block.get_hash(),
    #                 True,
    #             )
    #
    #             challnge = self.chain_head.finished_sub_slots[-1][0].get_hash()
    #
    #             output = get_vdf_output(
    #                 challnge,
    #                 ClassgroupElement.get_default_element(),
    #                 constants.DISCRIMINANT_SIZE_BITS,
    #                 self.curr_slot_iters,
    #             )
    #             end_of_slot_vdf = VDFInfo(
    #                 challnge,
    #                 ClassgroupElement.get_default_element(),
    #                 self.curr_slot_iters,
    #                 output,
    #             )
    #
    #             # restart overflow count
    #             self.num_sub_blocks_overflow: uint8 = uint8(0)
    #
    #             challenge_slot = ChallengeSlot(
    #                 self.prev_subepoch_summary_hash,
    #                 self.last_challenge_proof_of_space,
    #                 prev_block.reward_chain_sub_block.challenge_chain_sp_vdf,
    #                 prev_block.reward_chain_sub_block.challenge_chain_sp_sig,
    #                 prev_block.reward_chain_sub_block.challenge_chain_ip_vdf,
    #                 end_of_slot_vdf,
    #             )
    #
    #             rc_eos = RewardChainSubSlot(end_of_slot_vdf, std_hash(challenge_slot), self.deficit)
    #
    #             end_slot_proofs = get_end_of_slot_proofs(self.curr_slot_iters, challnge, constants)
    #             self.finished_sub_slots.append(Tuple[challenge_slot, rc_eos, end_slot_proofs])
    #
    #             # proof of space
    #             (
    #                 self.curr_proof_of_space,
    #                 self.plot_pk,
    #             ) = self.get_prams_from_plots(constants, std_hash(end_of_slot), seed)
    #
    #             self.quality = self.curr_proof_of_space.last_challenge_proof_of_space.verify_and_get_quality_string(
    #                 constants,
    #                 prev_block.reward_chain_sub_block.challenge_chain_sp_vdf.output.get_hash(),
    #                 prev_block.reward_chain_sub_block.challenge_chain_sp_sig,
    #             )
    #
    #         # if valid PoSpace
    #         if self.quality is not None:
    #             required_iters: uint64 = calculate_iterations_quality(
    #                 self.quality, self.curr_proof_of_space.size, self.difficulty
    #             )
    #
    #             # if we have deficit, subtract one
    #             if self.deficit > 0:
    #                 self.deficit = self.deficit - 1
    #
    #             # if overflow update num of overflow blocks
    #             overflow = False
    #             if is_overflow_sub_block(constants, self.ips, required_iters):
    #                 self.num_sub_blocks_overflow = self.num_sub_blocks_overflow + 1
    #                 overflow = True
    #
    #             block = self.create_next_block(
    #                 constants,
    #                 fees,
    #                 prev_block,
    #                 transactions,
    #                 aggsig,
    #                 timestamp,
    #                 reward_puzzlehash,
    #                 new_slot,
    #                 required_iters,
    #                 overflow,
    #             )
    #
    #             # zero finish slots
    #             self.finished_sub_slots = []
    #
    #             if new_slot and self.deficit == 0:
    #                 # new challenge chain block, zero sub block list
    #                 self.sub_blocks = Dict[bytes32, SubBlockRecord]
    #                 # new challenge chain block, reset deficit
    #                 self.deficit = 5
    #                 self.last_challenge_proof_of_space = self.curr_proof_of_space
    #
    #             block_list.append(block)
    #
    #         self.handle_end_of_sub_epoch(prev_block)
    #         self.handle_end_of_epoch(new_slot, prev_block, constants)
    #
    #     return block_list

    def create_genesis_block(
        self,
        constants: ConsensusConstants,
        fees: uint64 = 0,
        seed: bytes32 = b"",
        timestamp: Optional[uint64] = None,
        farmer_reward_puzzle_hash: Optional[bytes32] = None,
    ) -> FullBlock:
        """
        Creates the genesis block with the specified details.
        """
        if timestamp is None:
            timestamp = time.time()
        selected_proof: Optional[Tuple[uint64, ProofOfSpace]] = None
        finished_slots: List[EndOfSubSlotBundle] = []
        slot_iters: uint64 = uint64(constants.IPS_STARTING * constants.SLOT_TIME_TARGET)
        while True:
            if len(finished_slots) == 0:
                challenge = constants.FIRST_CC_CHALLENGE
                rc_challenge = constants.FIRST_RC_CHALLENGE
            else:
                challenge = finished_slots[-1].challenge_chain.get_hash()
                rc_challenge = finished_slots[-1].reward_chain.get_hash()
            proofs_of_space: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                constants,
                challenge,
                seed,
                uint64(constants.DIFFICULTY_STARTING),
                uint64(constants.IPS_STARTING),
            )
            if len(proofs_of_space) > 0:
                selected_proof = sorted(proofs_of_space)[0]
                break

            cc_vdf, cc_proof = get_vdf_info_and_proof(
                constants,
                ClassgroupElement.get_default_element(),
                challenge,
                slot_iters,
            )
            rc_vdf, rc_proof = get_vdf_info_and_proof(
                constants,
                ClassgroupElement.get_default_element(),
                rc_challenge,
                slot_iters,
            )
            cc_slot = ChallengeChainSubSlot(cc_vdf, None, None, None, None)
            finished_slots.append(
                EndOfSubSlotBundle(
                    cc_slot,
                    None,
                    RewardChainSubSlot(
                        rc_vdf, cc_slot.get_hash(), None, uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK)
                    ),
                    SubSlotProofs(cc_proof, None, rc_proof),
                )
            )

        required_iters: uint64 = selected_proof[0]
        sp_iters: uint64 = calculate_sp_iters(constants, uint64(constants.IPS_STARTING), required_iters)
        ip_iters: uint64 = calculate_ip_iters(constants, uint64(constants.IPS_STARTING), required_iters)

        if len(finished_slots) == 0:
            cc_challenge: bytes32 = constants.FIRST_CC_CHALLENGE
            rc_challenge: bytes32 = constants.FIRST_RC_CHALLENGE
        else:
            cc_challenge: bytes32 = finished_slots[-1].challenge_chain.get_hash()
            rc_challenge: bytes32 = finished_slots[-1].reward_chain.get_hash()

        if sp_iters == 0:
            cc_sp_vdf: Optional[VDFInfo] = None
            cc_sp_proof: Optional[VDFProof] = None
            rc_sp_vdf: Optional[VDFInfo] = None
            rc_sp_proof: Optional[VDFProof] = None
            to_sign_cc: Optional[bytes32] = constants.FIRST_CC_CHALLENGE
            to_sign_rc: Optional[bytes32] = constants.FIRST_RC_CHALLENGE
        else:
            cc_sp_vdf, cc_sp_proof = get_vdf_info_and_proof(
                constants, ClassgroupElement.get_default_element(), cc_challenge, sp_iters
            )
            rc_sp_vdf, rc_sp_proof = get_vdf_info_and_proof(
                constants, ClassgroupElement.get_default_element(), rc_challenge, sp_iters
            )
            to_sign_cc = cc_sp_vdf.get_hash()
            to_sign_rc = rc_sp_vdf.get_hash()

        cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
            constants, ClassgroupElement.get_default_element(), cc_challenge, ip_iters
        )
        rc_ip_vdf, rc_ip_proof = get_vdf_info_and_proof(
            constants, ClassgroupElement.get_default_element(), rc_challenge, ip_iters
        )
        cc_sp_signature: G2Element = self.get_plot_signature(to_sign_cc, selected_proof[1].plot_public_key)
        rc_sp_signature: G2Element = self.get_plot_signature(to_sign_rc, selected_proof[1].plot_public_key)
        print("Sigs", cc_sp_signature, rc_sp_signature)

        rc_sub_block = RewardChainSubBlock(
            uint128(constants.DIFFICULTY_STARTING),
            uint32(0),
            uint128(ip_iters),
            selected_proof[1],
            cc_sp_vdf,
            cc_sp_signature,
            cc_ip_vdf,
            rc_sp_vdf,
            rc_sp_signature,
            rc_ip_vdf,
            None,
            True,
        )
        if farmer_reward_puzzle_hash is None:
            farmer_reward_puzzle_hash = self.farmer_ph
        pool_coin = create_pool_coin(
            uint32(0), constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH, calculate_pool_reward(uint32(0))
        )
        farmer_coin = create_farmer_coin(uint32(0), farmer_reward_puzzle_hash, calculate_pool_reward(uint32(0)))

        foliage_sub_block, foliage_block, transactions_info = self.create_foliage(
            constants,
            rc_sub_block,
            fees,
            0,
            None,
            None,
            [pool_coin, farmer_coin],
            None,
            None,
            timestamp,
            True,
            farmer_reward_puzzle_hash,
            constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH,
            seed,
        )

        return FullBlock(
            finished_slots,
            rc_sub_block,
            cc_sp_proof,
            cc_ip_proof,
            rc_sp_proof,
            rc_ip_proof,
            None,
            foliage_sub_block,
            foliage_block,
            transactions_info,
            None,
        )

    # def create_next_block(
    #     self,
    #     constants: ConsensusConstants,
    #     fees: uint64,
    #     head: FullBlock,
    #     transactions: Optional[Program],
    #     aggsig: Optional[G2Element],
    #     timestamp: uint64,
    #     reward_puzzlehash: bytes32,
    #     new_slot: bool,
    #     required_iters: uint64,
    #     overflow: bool,
    # ) -> (FullBlock, bool):
    #     """
    #     Creates the next block with the specified details.
    #     """
    #
    #     # use default element if new slot
    #     if new_slot:
    #         cc_vdf_input = ClassgroupElement.get_default_element()
    #         rc_vdf_challenge = self.chain_head.finished_sub_slots[-1][1].get_hash()
    #     else:
    #         cc_vdf_input = head.reward_chain_sub_block.challenge_chain_ip_vdf.output
    #         rc_vdf_challenge = head.reward_chain_sub_block.reward_chain_ip_vdf.output.get_hash()
    #
    #     cc_vdf_challenge = self.finished_sub_slots[-1][0].get_hash()
    #
    #     number_iters: uint64 = pot_iterations.calculate_iterations(
    #         constants, self.last_challenge_proof_of_space, self.difficulty
    #     )
    #
    #     cc_sp_output, cc_ip_output, rc_sp_output, rc_ip_output = get_vdf_outputs(
    #         number_iters, std_hash(new_slot), cc_vdf_input, constants
    #     )
    #
    #     sp_iters: uint64 = calculate_sp_iters(constants, self.ips, required_iters)
    #     ip_iters: uint64 = calculate_ip_iters(constants, self.ips, required_iters)
    #
    #     cc_sp_vdf: VDFInfo = get_challenge_chain_sp_vdf(cc_vdf_challenge, sp_iters, cc_vdf_input, cc_sp_output)
    #     cc_ip_vdf: VDFInfo = get_challenge_chain_ip_vdf(cc_vdf_challenge, ip_iters, cc_vdf_input, cc_ip_output)
    #     cc_sp_signature: G2Element = self.get_plot_signature(self.chain_head, self.plot_pk)
    #
    #     rc_sp_vdf: VDFInfo = get_reward_chain_sp_vdf(rc_vdf_challenge, sp_iters, rc_sp_output)
    #     rc_ip_vdf: VDFInfo = get_reward_chain_ip_vdf(rc_vdf_challenge, ip_iters, rc_ip_output)
    #     rc_sp_sig: G2Element = self.get_plot_signature(head, self.plot_pk)
    #
    #     reward_chain_sub_block = RewardChainSubBlock(
    #         head.weight + self.difficulty,
    #         number_iters,
    #         self.curr_proof_of_space,
    #         cc_ip_vdf,
    #         cc_sp_vdf,
    #         cc_sp_signature,
    #         rc_sp_vdf,
    #         rc_sp_sig,
    #         rc_ip_vdf,
    #     )
    #
    #     foliage_sub_block, foliage_block, transactions_info, transactions_generator = self.create_foliage(
    #         fees,
    #         aggsig,
    #         transactions,
    #         block_rewards,  # todo
    #         head,
    #         timestamp,
    #         head.reward_chain_sub_block.get_unfinished().get_hash(),
    #         is_transaction_block(
    #             overflow,
    #             number_iters,
    #             ip_iters,
    #             sp_iters,
    #             self.curr_slot_iters,
    #             head.total_iters,
    #         ),
    #         reward_puzzlehash,
    #         self.curr_proof_of_space,
    #     )
    #
    #     self.prev_foliage_block = foliage_block
    #     self.previous_generators_root = transactions_generator.get_tree_hash()
    #
    #     full_block: FullBlock = FullBlock(
    #         finished_slots=self.finished_sub_slots,
    #         challenge_chain_ip_proof=VDFProof(witness=cc_ip_output.get_hash(), witness_type=uint8(1)),
    #         challenge_chain_sp_proof=VDFProof(witness=cc_sp_output.get_hash(), witness_type=uint8(1)),
    #         reward_chain_sp_proof=VDFProof(witness=rc_sp_output.get_hash(), witness_type=uint8(1)),
    #         reward_chain_ip_proof=VDFProof(witness=rc_ip_output.get_hash(), witness_type=uint8(1)),
    #         reward_chain_sub_block=reward_chain_sub_block,
    #         foliage_sub_block=foliage_sub_block,
    #         foliage_block=foliage_block,
    #         transactions_info=transactions_info,
    #         transactions_generator=transactions_generator,
    #     )
    #
    #     return full_block

    def create_foliage(
        self,
        constants: ConsensusConstants,
        reward_sub_block: RewardChainSubBlock,
        fees: uint64,
        height,
        aggsig: Optional[G2Element],
        transactions: Optional[Program],
        reward_claims_incorporated: Optional[List[Coin]],
        prev_sub_block: Optional[FullBlock],
        prev_block: Optional[FullBlock],
        timestamp: uint64,
        is_transaction: bool,
        farmer_reward_puzzlehash: bytes32 = None,
        pool_reward_puzzlehash: bytes32 = None,
        seed: bytes32 = b"",
    ) -> (FoliageSubBlock, Optional[FoliageBlock], Optional[TransactionsInfo]):

        # Use the extension data to create different blocks based on header hash
        random.seed(seed)
        extension_data: bytes32 = random.randint(0, 100000000).to_bytes(32, "big")
        height = reward_sub_block.sub_block_height
        cost: uint64 = uint64(0)
        fee_reward: uint64 = uint64(block_rewards.calculate_base_farmer_reward(height) + fees)

        # Create filter
        byte_array_tx: List[bytes32] = []
        tx_additions: List[Coin] = []
        tx_removals: List[bytes32] = []
        if is_transaction and transactions:
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
        if farmer_reward_puzzlehash is not None:
            farmer_ph = farmer_reward_puzzlehash
        if pool_reward_puzzlehash is not None:
            pool_ph = pool_reward_puzzlehash

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
        # print(height, reward_puzzlehash, fee_reward)
        pool_coin = create_pool_coin(height, pool_ph, fee_reward)
        farmer_coin = create_farmer_coin(height, farmer_ph, fee_reward)

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
        pool_target_signature = self.get_pool_key_signature(
            pool_target, reward_sub_block.proof_of_space.pool_public_key
        )
        assert pool_target_signature is not None

        foliage_sub_block_data = FoliageSubBlockData(
            reward_sub_block.get_unfinished().get_hash(),
            pool_target,
            pool_target_signature,
            farmer_ph,
            extension_data,
        )

        foliage_sub_block_signature: G2Element = self.get_plot_signature(
            foliage_sub_block_data.get_hash(), reward_sub_block.proof_of_space.plot_public_key
        )
        if height != 0:
            prev_sub_block_hash = prev_sub_block.get_hash()
        else:
            prev_sub_block_hash = constants.GENESIS_PREV_HASH

        if is_transaction:
            if height != 0:
                prev_hash: Optional[bytes32] = prev_block.get_hash()
            else:
                prev_hash = constants.GENESIS_PREV_HASH

            if aggsig is None:
                aggsig = G2Element.infinity()
            # TODO: prev generators root
            transactions_info = TransactionsInfo(
                bytes([0] * 32), generator_hash, aggsig, fees, cost, reward_claims_incorporated
            )

            foliage_block = FoliageBlock(
                prev_hash,
                timestamp,
                filter_hash,
                additions_root,
                removals_root,
                transactions_info.get_hash(),
            )
            foliage_block_hash: Optional[bytes32] = foliage_block.get_hash()
            foliage_block_signature: Optional[G2Element] = self.get_plot_signature(
                foliage_block_hash, reward_sub_block.proof_of_space.plot_public_key
            )
        else:
            foliage_block_hash = None
            foliage_block_signature = None
            foliage_block = None
            transactions_info = None

        foliage_sub_block = FoliageSubBlock(
            prev_sub_block_hash,
            reward_sub_block.get_hash(),
            foliage_sub_block_data,
            foliage_sub_block_signature,
            foliage_block_hash,
            foliage_block_signature,
        )

        return foliage_sub_block, foliage_block, transactions_info

    def get_pospaces_for_challenge(
        self, constants: ConsensusConstants, challenge_hash: bytes32, seed: bytes, difficulty: uint64, ips: uint64
    ) -> (ProofOfSpace, uint64):
        found_proofs: List[(uint64, ProofOfSpace)] = []
        plots: List[PlotInfo] = [
            plot_info for _, plot_info in sorted(list(self.plots.items()), key=lambda x: str(x[0]))
        ]
        random.seed(seed)
        print("Trying", len(plots) // 2, "plots")
        passed_plot_filter = 0
        # Use the seed to select a random number of plots, so we generate different chains
        for plot_info in random.sample(plots, len(plots) // 2):
            # Allow passing in seed, to create reorgs and different chains
            plot_id = plot_info.prover.get_id()
            if ProofOfSpace.can_create_proof(constants, plot_id, challenge_hash, None, None):
                passed_plot_filter += 1
                qualities = plot_info.prover.get_qualities_for_challenge(challenge_hash)
                for proof_index, quality_str in enumerate(qualities):
                    slot_iters = calculate_slot_iters(constants, ips)
                    required_iters: uint64 = calculate_iterations_quality(
                        quality_str,
                        plot_info.prover.get_size(),
                        difficulty,
                    )
                    if required_iters < slot_iters:
                        proof_xs: bytes = plot_info.prover.get_full_proof(challenge_hash, proof_index)

                        plot_pk = ProofOfSpace.generate_plot_public_key(
                            plot_info.local_sk.get_g1(),
                            plot_info.farmer_public_key,
                        )
                        proof_of_space: ProofOfSpace = ProofOfSpace(
                            challenge_hash,
                            plot_info.pool_public_key,
                            None,
                            plot_pk,
                            plot_info.prover.get_size(),
                            proof_xs,
                        )
                        found_proofs.append((required_iters, proof_of_space))
                    else:
                        print("Iters too high", required_iters)
        print("Passed filter:", passed_plot_filter)
        print("Total eligible proofs:", len(found_proofs))
        return found_proofs


# def get_end_of_slot_proofs(curr_slot_iters, challnge, constants):
#     challenge_chain_slot_proof = get_vdf_proof(
#         challnge,
#         ClassgroupElement.get_default_element(),
#         curr_slot_iters,
#         constants.DISCRIMINANT_SIZE_BITS,
#     )
#     reward_chain_slot_proof = get_vdf_proof(
#         challnge,
#         ClassgroupElement.get_default_element(),
#         curr_slot_iters,
#         constants.DISCRIMINANT_SIZE_BITS,
#     )
#     end_slot_proofs = SubSlotProofs(challenge_chain_slot_proof, reward_chain_slot_proof)
#     return end_slot_proofs


def get_vdf_info_and_proof(
    constants: ConsensusConstants,
    vdf_input: ClassgroupElement,
    challenge_hash: bytes32,
    number_iters: uint64,
) -> Tuple[VDFInfo, VDFProof]:
    int_size = (constants.DISCRIMINANT_SIZE_BITS + 16) >> 4
    result: bytes = prove(
        challenge_hash, str(vdf_input.a), str(vdf_input.b), constants.DISCRIMINANT_SIZE_BITS, number_iters
    )
    output = ClassgroupElement(
        int512(
            int.from_bytes(
                result[0:int_size],
                "big",
                signed=True,
            )
        ),
        int512(
            int.from_bytes(
                result[int_size : 2 * int_size],
                "big",
                signed=True,
            )
        ),
    )
    proof_bytes = result[2 * int_size : 4 * int_size]
    return VDFInfo(challenge_hash, vdf_input, number_iters, output), VDFProof(uint8(0), proof_bytes)


def get_plot_dir():
    cache_path = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/"))) / "test-plots"
    mkdir(cache_path)
    return cache_path


# def get_challenge_chain_sp_vdf(
#     challenge: bytes32, sp_iters: uint64, input: ClassgroupElement, output: ClassgroupElement
# ) -> Optional[VDFInfo]:
#     if sp_iters == 0:
#         return None
#     return VDFInfo(
#         challenge_hash=challenge,
#         input=input,
#         number_of_iterations=sp_iters,
#         output=output,
#     )
#
#
# def get_reward_chain_sp_vdf(challenge: bytes32, sp_iters: uint64, output: ClassgroupElement) -> Optional[VDFInfo]:
#     if sp_iters == 0:
#         return None
#     return VDFInfo(
#         challenge_hash=challenge,
#         input=ClassgroupElement.get_default_element(),
#         number_of_iterations=sp_iters,
#         output=output,
#     )
#
#
# def get_challenge_chain_ip_vdf(
#     challenge: bytes32, ip_iters: uint64, input: ClassgroupElement, output: ClassgroupElement
# ) -> VDFInfo:
#     return VDFInfo(
#         challenge_hash=challenge,
#         input=input,
#         number_of_iterations=ip_iters,
#         output=output,
#     )
#
#
# def get_reward_chain_ip_vdf(block: FullBlock, ip_iters: uint64, output: ClassgroupElement) -> VDFInfo:
#     cc_vdf_challenge: bytes32 = block.finished_sub_slots[-1][1].get_hash()
#     return VDFInfo(
#         challenge_hash=cc_vdf_challenge,
#         input=ClassgroupElement.get_default_element(),
#         number_of_iterations=ip_iters,
#         output=output,
#     )


def is_transaction_block(overflow: bool, total_iters, ip_iters, sp_iters, slot_iters, curr_total_iters) -> bool:
    # The first sub-block to have an sp > the last block's infusion iters, is a block
    if overflow:
        our_sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters - slot_iters)
    else:
        our_sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters)
    return our_sp_total_iters > curr_total_iters


test_constants = DEFAULT_CONSTANTS.replace(
    **{
        "DIFFICULTY_STARTING": 1,
        "DISCRIMINANT_SIZE_BITS": 8,
        "SUB_EPOCH_SUB_BLOCKS": 128,
        "EPOCH_SUB_BLOCKS": 512,
        "IPS_STARTING": 10 * 1,
        "NUMBER_ZERO_BITS_PLOT_FILTER": 1,  # H(plot signature of the challenge) must start with these many zeroes
        "NUMBER_ZERO_BITS_ICP_FILTER": 1,  # H(plot signature of the challenge) must start with these many zeroes
    }
)
bt = BlockTools()
g = bt.create_genesis_block(test_constants)
print(g)
