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
from src.consensus import block_rewards
from src.consensus.block_rewards import (
    calculate_pool_reward,
    calculate_base_farmer_reward,
)
from src.consensus.coinbase import (
    create_puzzlehash_for_pk,
    create_pool_coin,
    create_farmer_coin,
)
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_infusion_point_iters,
    calculate_iterations_quality,
    calculate_sp_iters,
    calculate_slot_iters,
)
from src.full_node.difficulty_adjustment import (
    get_next_difficulty,
    get_next_ips,
)
from src.full_node.full_block_to_sub_block_record import full_block_to_sub_block_record
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.full_node.sub_block_record import SubBlockRecord
from src.plotting.plot_tools import load_plots, PlotInfo
from src.types.classgroup import ClassgroupElement
from src.types.coin import hash_coin_list, Coin
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
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
from src.types.slots import InfusedChallengeChainSubSlot, ChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs, \
    ChallengeBlockInfo
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
                bytes_to_mnemonic(std_hash(b"block_tools farmer key")), "")
            self.pool_master_sk = self.keychain.add_private_key(bytes_to_mnemonic(std_hash(b"block_tools pool key")),
                                                                "")
            self.farmer_pk = master_sk_to_farmer_sk(self.farmer_master_sk).get_g1()
            self.pool_pk = master_sk_to_pool_sk(self.pool_master_sk).get_g1()
            self.latest_sub_block: Optional[FullBlock] = None
            self.latest_block: Optional[FullBlock] = None
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
            master_sk_to_wallet_sk(self.farmer_master_sk, uint32(0)).get_g1())
        self.pool_ph: bytes32 = create_puzzlehash_for_pk(
            master_sk_to_wallet_sk(self.pool_master_sk, uint32(0)).get_g1())

        self.all_sks: List[PrivateKey] = [sk for sk, _ in self.keychain.get_all_private_keys()]
        self.pool_pubkeys: List[G1Element] = [master_sk_to_pool_sk(sk).get_g1() for sk in self.all_sks]
        self.curr_slot: uint32 = uint32(1)
        self.curr_epoch: uint32 = uint32(1)
        self.curr_sub_epoch: uint32 = uint32(1)
        self.sub_blocks: Optional[Dict[bytes32, SubBlockRecord]] = {}
        self.height_to_hash: Optional[Dict[uint32, bytes32]] = {}
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

    def get_consecutive_blocks(
            self,
            constants: ConsensusConstants,
            num_blocks: int,
            block_list: List[FullBlock] = None,
            reward_puzzlehash: bytes32 = None,
            fees: uint64 = uint64(0),
            transaction_data_at_height: Dict[int, Tuple[Program, G2Element]] = None,
            force_overflow: bool = False,
            seed: bytes = b"",
            force_empty_slots: uint32 = uint32(0),  # Force at least this number of empty slots before the first SB
    ) -> List[FullBlock]:
        if transaction_data_at_height is None:
            transaction_data_at_height = {}
        if block_list is None or len(block_list) == 0:
            self.difficulty = constants.DIFFICULTY_STARTING
            self.ips = uint64(constants.IPS_STARTING)
            genesis, req_iters = self.create_genesis_block(
                constants,
                fees,
                seed,
                force_overflow=force_overflow,
                force_empty_slots=force_empty_slots,
            )
            self.latest_sub_block = genesis

            self.sub_blocks[genesis.header_hash] = full_block_to_sub_block_record(
                constants,
                self.sub_blocks,
                self.height_to_hash,
                genesis,
                req_iters,
            )
            self.height_to_hash[uint32(0)] = genesis.header_hash
            self.deficit = 5
            block_list: List[FullBlock] = [genesis]
            self.prev_foliage_block = genesis.foliage_block
        else:
            assert block_list[-1].proof_of_time is not None

        starting_height: int = block_list[-1].height + 1
        timestamp: uint64 = block_list[-1].foliage_block.timestamp
        end_of_slot: Optional[RewardChainSubSlot] = None
        transactions: Optional[Program] = None
        aggsig: Optional[G2Element] = None

        return block_list

        for next_height in range(starting_height, starting_height + num_blocks):
            if next_height in transaction_data_at_height:
                transactions, aggsig = transaction_data_at_height[next_height]
            block = self.create_next_block(
                constants,
                transactions,
                aggsig,
                fees,
                seed,
                force_overflow=force_overflow,
                force_empty_slots=force_empty_slots,
            )
            self.latest_sub_block = block
            block_list.append(block)
        #         self.handle_end_of_sub_epoch(prev_block)
        #         self.handle_end_of_epoch(new_slot, prev_block, constants)
        #
        return block_list

    def create_genesis_block(
            self,
            constants: ConsensusConstants,
            fees: uint64 = 0,
            seed: bytes32 = b"",
            timestamp: Optional[uint64] = None,
            farmer_reward_puzzle_hash: Optional[bytes32] = None,
            force_overflow: bool = False,
            force_empty_slots: uint32 = uint32(0),
    ) -> (FullBlock, uint128):
        if timestamp is None:
            timestamp = time.time()
        finished_sub_slots: List[EndOfSubSlotBundle] = []
        slot_iters: uint64 = uint64(constants.IPS_STARTING * constants.SLOT_TIME_TARGET)
        selected_proof: Optional[Tuple[uint64, ProofOfSpace]] = None
        selected_proof_is_overflow: bool = False

        # Keep trying until we get a good proof of space that also passes sp filter
        while True:
            cc_challenge, rc_challenge = self.get_genesis_challenges(constants, finished_sub_slots)
            proofs_of_space: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                constants,
                cc_challenge,
                seed,
                uint64(constants.DIFFICULTY_STARTING),
                uint64(constants.IPS_STARTING),
            )

            # Try each of the proofs of space
            for required_iters, proof_of_space in sorted(proofs_of_space, key=lambda t: t[0]):

                sp_iters: uint64 = calculate_sp_iters(constants, uint64(constants.IPS_STARTING), required_iters)
                ip_iters = calculate_ip_iters(constants, uint64(constants.IPS_STARTING), required_iters)
                is_overflow_block = sp_iters > ip_iters
                if force_overflow and not is_overflow_block:
                    continue
                if len(finished_sub_slots) < force_empty_slots:
                    continue

                cc_challenge, rc_challenge = self.get_genesis_challenges(constants, finished_sub_slots)

                if sp_iters == 0:
                    cc_sp_vdf: Optional[VDFInfo] = None
                    cc_sp_proof: Optional[VDFProof] = None
                    rc_sp_vdf: Optional[VDFInfo] = None
                    rc_sp_proof: Optional[VDFProof] = None
                    to_sign_cc: Optional[bytes32] = constants.FIRST_CC_CHALLENGE
                    to_sign_rc: Optional[bytes32] = constants.FIRST_RC_CHALLENGE
                else:
                    cc_sp_vdf, cc_sp_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        cc_challenge,
                        sp_iters,
                    )
                    rc_sp_vdf, rc_sp_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        rc_challenge,
                        sp_iters,
                    )

                    to_sign_cc = cc_sp_vdf.output.get_hash()
                    to_sign_rc = rc_sp_vdf.output.get_hash()
                if is_overflow_block:
                    # Handle the infusion point stuff after finishing the sub-slot
                    pass
                else:
                    cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        cc_challenge,
                        ip_iters,
                    )
                    rc_ip_vdf, rc_ip_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        rc_challenge,
                        ip_iters,
                    )

                cc_sp_signature: Optional[G2Element] = self.get_plot_signature(to_sign_cc,
                                                                               proof_of_space.plot_public_key)
                rc_sp_signature: Optional[G2Element] = self.get_plot_signature(to_sign_rc,
                                                                               proof_of_space.plot_public_key)

                # Checks sp filter
                plot_id = proof_of_space.get_plot_id()
                if ProofOfSpace.can_create_proof(constants, plot_id, cc_challenge, to_sign_cc, cc_sp_signature):
                    selected_proof = (required_iters, proof_of_space)
                    selected_proof_is_overflow = is_overflow_block
                    self.curr_proof_of_space = selected_proof
                    break

            if selected_proof is not None and not selected_proof_is_overflow:
                # Break if found the proof of space. Don't break for overflow, need to finish the slot first
                break

            # Finish the end of sub-slot and try again next sub-slot
            cc_vdf, cc_proof = get_vdf_info_and_proof(
                constants,
                ClassgroupElement.get_default_element(),
                cc_challenge,
                slot_iters,
            )
            rc_vdf, rc_proof = get_vdf_info_and_proof(
                constants,
                ClassgroupElement.get_default_element(),
                rc_challenge,
                slot_iters,
            )
            cc_slot = ChallengeChainSubSlot(cc_vdf, None, None, None, None)
            finished_sub_slots.append(
                EndOfSubSlotBundle(
                    cc_slot,
                    None,
                    RewardChainSubSlot(
                        rc_vdf,
                        cc_slot.get_hash(),
                        None,
                        uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK),
                    ),
                    SubSlotProofs(cc_proof, None, rc_proof),
                )
            )
            if selected_proof is not None:
                # Break for overflow sub-block
                assert selected_proof_is_overflow
                cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
                    constants,
                    ClassgroupElement.get_default_element(),
                    finished_sub_slots[-1].challenge_chain.get_hash(),
                    ip_iters,
                )
                rc_ip_vdf, rc_ip_proof = get_vdf_info_and_proof(
                    constants,
                    ClassgroupElement.get_default_element(),
                    finished_sub_slots[-1].reward_chain.get_hash(),
                    ip_iters,
                )
                break



        rc_sub_block = RewardChainSubBlock(
            uint128(constants.DIFFICULTY_STARTING),
            uint32(0),
            uint128(slot_iters * len(finished_sub_slots) + ip_iters),
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
        # print("Created RCSB", rc_sub_block)
        if farmer_reward_puzzle_hash is None:
            farmer_reward_puzzle_hash = self.farmer_ph
        pool_coin = create_pool_coin(uint32(0), constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH,
                                     calculate_pool_reward(uint32(0)))
        farmer_coin = create_farmer_coin(uint32(0), farmer_reward_puzzle_hash, calculate_base_farmer_reward(uint32(0)))

        foliage_sub_block, foliage_block, transactions_info = self.create_foliage(
            constants,
            rc_sub_block,
            fees,
            None,
            None,
            [pool_coin, farmer_coin],
            None,
            timestamp,
            True,
            farmer_reward_puzzle_hash,
            constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH,
            seed,
        )

        return FullBlock(
            finished_sub_slots,
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
        ),required_iters

    def get_genesis_challenges(self, constants, finished_sub_slots):
        if len(finished_sub_slots) == 0:
            challenge = constants.FIRST_CC_CHALLENGE
            rc_challenge = constants.FIRST_RC_CHALLENGE
        else:
            challenge = finished_sub_slots[-1].challenge_chain.get_hash()
            rc_challenge = finished_sub_slots[-1].reward_chain.get_hash()
        return challenge, rc_challenge






    def create_next_block(
            self,
            constants: ConsensusConstants,
            transactions: Optional[Program],
            aggsig: Optional[G2Element],
            fees: uint64 = 0,
            seed: bytes32 = b"",
            timestamp: Optional[uint64] = None,
            farmer_reward_puzzle_hash: Optional[bytes32] = None,
            force_overflow: bool = False,
            force_empty_slots: uint32 = uint32(0),
            deficit: int = 0,
    ) -> FullBlock:
        if timestamp is None:
            timestamp = time.time()
        finished_sub_slots: List[EndOfSubSlotBundle] = []
        slot_iters: uint64 = uint64(constants.IPS_STARTING * constants.SLOT_TIME_TARGET)
        selected_proof: Optional[Tuple[uint64, ProofOfSpace]] = None
        selected_proof_is_overflow: bool = False

        # Keep trying until we get a good proof of space that also passes sp filter
        while True:
            cc_challenge, rc_challenge = self.get_challenges(finished_sub_slots)
            proofs_of_space: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                constants,
                cc_challenge,
                seed,
                uint64(constants.DIFFICULTY_STARTING),
                uint64(constants.IPS_STARTING),
            )

            # Try each of the proofs of space
            for required_iters, proof_of_space in sorted(proofs_of_space, key=lambda t: t[0]):
                sp_iters: uint64 = calculate_sp_iters(constants, uint64(constants.IPS_STARTING), required_iters)
                ip_iters = calculate_ip_iters(constants, uint64(constants.IPS_STARTING), required_iters)
                is_overflow_block = sp_iters > ip_iters
                if force_overflow and not is_overflow_block:
                    continue
                if len(finished_sub_slots) < force_empty_slots:
                    continue

                cc_challenge, rc_challenge = self.get_challenges(finished_sub_slots)

                if sp_iters == 0:
                    cc_sp_vdf: Optional[VDFInfo] = None
                    cc_sp_proof: Optional[VDFProof] = None
                    rc_sp_vdf: Optional[VDFInfo] = None
                    rc_sp_proof: Optional[VDFProof] = None
                    to_sign_cc: Optional[bytes32] = constants.FIRST_CC_CHALLENGE
                    to_sign_rc: Optional[bytes32] = constants.FIRST_RC_CHALLENGE
                else:
                    cc_sp_vdf, cc_sp_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        cc_challenge,
                        sp_iters,
                    )
                    rc_sp_vdf, rc_sp_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        rc_challenge,
                        sp_iters,
                    )
                    to_sign_cc = cc_sp_vdf.output.get_hash()
                    to_sign_rc = rc_sp_vdf.output.get_hash()


                if is_overflow_block:
                    # Handle the infusion point stuff after finishing the sub-slot
                    pass
                else:
                    cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        cc_challenge,
                        ip_iters,
                    )
                    rc_ip_vdf, rc_ip_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        rc_challenge,
                        ip_iters,
                    )

                cc_sp_signature: Optional[G2Element] = self.get_plot_signature(to_sign_cc,
                                                                               proof_of_space.plot_public_key)
                rc_sp_signature: Optional[G2Element] = self.get_plot_signature(to_sign_rc,
                                                                               proof_of_space.plot_public_key)

                # Checks sp filter
                plot_id = proof_of_space.get_plot_id()
                if ProofOfSpace.can_create_proof(constants, plot_id, cc_challenge, to_sign_cc, cc_sp_signature):
                    selected_proof = (required_iters, proof_of_space)
                    selected_proof_is_overflow = is_overflow_block
                    self.curr_proof_of_space = selected_proof
                    break

            if selected_proof is not None and not selected_proof_is_overflow:
                # Break if found the proof of space. Don't break for overflow, need to finish the slot first
                break

            # Finish the end of sub-slot and try again next sub-slot
            cc_vdf, cc_proof = get_vdf_info_and_proof(
                constants,
                ClassgroupElement.get_default_element(),
                cc_challenge,
                slot_iters,
            )
            rc_vdf, rc_proof = get_vdf_info_and_proof(
                constants,
                ClassgroupElement.get_default_element(),
                rc_challenge,
                slot_iters,
            )

            cbi = self.get_icc(constants)

            icc_vdf, icc_proof = get_vdf_info_and_proof(
                    constants,
                    self.latest_sub_block.infused_challenge_vdf_output,
                    std_hash(cbi),
                    ip_iters,
            )


            icc = InfusedChallengeChainSubSlot(icc_vdf)
            cc_slot = ChallengeChainSubSlot(cc_vdf, None, None, None, None)


            finished_sub_slots.append(
                EndOfSubSlotBundle(
                    cc_slot,
                    icc,
                    RewardChainSubSlot(
                        rc_vdf,
                        cc_slot.get_hash(),
                        icc.get_hash(),
                        uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK),
                    ),
                    SubSlotProofs(cc_proof, None, rc_proof),
                )
            )
            if selected_proof is not None:
                # Break for overflow sub-block
                assert selected_proof_is_overflow
                cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
                    constants,
                    ClassgroupElement.get_default_element(),
                    finished_sub_slots[-1].challenge_chain.get_hash(),
                    ip_iters,
                )
                rc_ip_vdf, rc_ip_proof = get_vdf_info_and_proof(
                    constants,
                    ClassgroupElement.get_default_element(),
                    finished_sub_slots[-1].reward_chain.get_hash(),
                    ip_iters,
                )
                break

        rc_sub_block = RewardChainSubBlock(
            uint128(constants.DIFFICULTY_STARTING),
            uint32(self.latest_sub_block.height + 1),
            uint128(slot_iters * len(finished_sub_slots) + ip_iters),
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
        # print("Created RCSB", rc_sub_block)
        if farmer_reward_puzzle_hash is None:
            farmer_reward_puzzle_hash = self.farmer_ph
        pool_coin = create_pool_coin(
            uint32(0),
            constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH,
            calculate_pool_reward(uint32(0)),
        )
        farmer_coin = create_farmer_coin(
            uint32(0),
            farmer_reward_puzzle_hash,
            calculate_base_farmer_reward(uint32(0)),
        )

        foliage_sub_block, foliage_block, transactions_info = self.create_foliage(
            constants,
            rc_sub_block,
            fees,
            aggsig,
            transactions,
            [pool_coin, farmer_coin],
            self.latest_sub_block,
            timestamp,
            False,
            farmer_reward_puzzle_hash,
            constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH,
            seed,
        )

        return FullBlock(
            finished_sub_slots,
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

    def get_icc(self, constants,finished_sub_slots):
        prev_sb = self.latest_sub_block
        if self.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
            icc_challenge_hash: Optional[bytes32] = None
        else:
            if len(finished_sub_slots) == 0:
                while self.deficit < constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1 and not curr.first_in_slot:
                    curr = self.sub_blocks[curr.prev_hash]
                if curr.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                    icc_challenge_hash = curr.challenge_block_info_hash
                    # ip_iters_prev = calculate_ip_iters(constants, prev_sb.ips, prev_sb.required_iters)
                    # ip_iters_challenge_block = calculate_ip_iters(constants, curr.ips, curr.required_iters)
                    # icc_iters_proof: uint64 = calculate_slot_iters(constants, prev_sb.ips) - ip_iters_prev
                    # icc_iters_committed: uint64 = calculate_slot_iters(constants,
                    #                                                    prev_sb.ips) - ip_iters_challenge_block

                else:
                    icc_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
                    # icc_iters_committed = calculate_slot_iters(constants, prev_sb.ips)
                    # icc_iters_proof = icc_iters_committed
            else:
                icc_challenge_hash = finished_sub_slots[
                    len(finished_sub_slots) - 1].infused_challenge_chain.get_hash()
                # icc_iters_committed = calculate_slot_iters(constants, prev_sb.ips)
                # icc_iters_proof = icc_iters_committed
        return icc_challenge_hash

    def get_challenges(self, finished_sub_slots):
        if len(finished_sub_slots) == 0:
            curr = self.sub_blocks[self.latest_sub_block.header_hash]
            while True:
                curr = self.sub_blocks[curr.header_hash]
                if curr.first_in_slot:
                    break
            cc_challenge = curr.finished_challenge_slot_hashes[-1]
            rc_challenge = curr.finished_challenge_slot_hashes[-1]
        else:
            cc_challenge = finished_sub_slots[-1].challenge_chain.get_hash()
            rc_challenge = finished_sub_slots[-1].reward_chain.get_hash()
        return cc_challenge, rc_challenge

    def create_foliage(
            self,
            constants: ConsensusConstants,
            reward_sub_block: RewardChainSubBlock,
            fees: uint64,
            aggsig: Optional[G2Element],
            transactions: Optional[Program],
            reward_claims_incorporated: Optional[List[Coin]],
            prev_sub_block: Optional[FullBlock],
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

        farmer_reward: uint64 = uint64(block_rewards.calculate_base_farmer_reward(height) + fees)
        pool_reward: uint64 = uint64(block_rewards.calculate_pool_reward(height))

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

        pool_coin = create_pool_coin(height, pool_ph, pool_reward)
        farmer_coin = create_farmer_coin(height, farmer_ph, farmer_reward)

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
        pool_target_signature = self.get_pool_key_signature(pool_target,
                                                            reward_sub_block.proof_of_space.pool_public_key)
        assert pool_target_signature is not None

        foliage_sub_block_data = FoliageSubBlockData(
            reward_sub_block.get_unfinished().get_hash(),
            pool_target,
            pool_target_signature,
            farmer_ph,
            extension_data,
        )

        foliage_sub_block_signature: G2Element = self.get_plot_signature(foliage_sub_block_data.get_hash(),
                                                                         reward_sub_block.proof_of_space.plot_public_key)
        if height != 0:
            prev_sub_block_hash = prev_sub_block.get_hash()
        else:
            prev_sub_block_hash = constants.GENESIS_PREV_HASH

        if is_transaction:
            if height != 0:
                prev_hash: Optional[bytes32] = self.latest_block.header_hash
            else:
                prev_hash = constants.GENESIS_PREV_HASH

            if aggsig is None:
                aggsig = G2Element.infinity()
            # TODO: prev generators root
            transactions_info = TransactionsInfo(bytes([0] * 32), generator_hash, aggsig, fees, cost,
                                                 reward_claims_incorporated)

            foliage_block = FoliageBlock(
                prev_hash,
                timestamp,
                filter_hash,
                additions_root,
                removals_root,
                transactions_info.get_hash(),
            )
            foliage_block_hash: Optional[bytes32] = foliage_block.get_hash()
            foliage_block_signature: Optional[G2Element] = self.get_plot_signature(foliage_block_hash,
                                                                                   reward_sub_block.proof_of_space.plot_public_key)
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

    def get_pospaces_for_challenge(self, constants: ConsensusConstants, challenge_hash: bytes32, seed: bytes,
                                   difficulty: uint64, ips: uint64) -> (ProofOfSpace, uint64):
        found_proofs: List[(uint64, ProofOfSpace)] = []
        plots: List[PlotInfo] = [plot_info for _, plot_info in
                                 sorted(list(self.plots.items()), key=lambda x: str(x[0]))]
        random.seed(seed)
        # print("Trying", len(plots) // 2, "plots")
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
                    # else:
                    #     print("Iters too high", required_iters)
        # print("Passed filter:", passed_plot_filter)
        # print("Total eligible proofs:", len(found_proofs))
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
    result: bytes = prove(challenge_hash, str(vdf_input.a), str(vdf_input.b), constants.DISCRIMINANT_SIZE_BITS,
                          number_iters)
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
                result[int_size: 2 * int_size],
                "big",
                signed=True,
            )
        ),
    )
    proof_bytes = result[2 * int_size: 4 * int_size]
    return VDFInfo(challenge_hash, vdf_input, number_iters, output), VDFProof(uint8(0), proof_bytes)


def get_plot_dir():
    cache_path = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/"))) / "test-plots"
    mkdir(cache_path)
    return cache_path


def is_transaction_block(overflow: bool, total_iters, ip_iters, sp_iters, slot_iters, curr_total_iters) -> bool:
    # The first sub-block to have an sp > the last block's infusion iters, is a block
    if overflow:
        our_sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters - slot_iters)
    else:
        our_sp_total_iters: uint128 = uint128(total_iters - ip_iters + sp_iters)
    return our_sp_total_iters > curr_total_iters
