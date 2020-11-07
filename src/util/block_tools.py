import copy
import os
import random
import shutil
import sys
import tempfile
import time
from argparse import Namespace
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union

import blspy
from blspy import G1Element, G2Element, AugSchemeMPL, PrivateKey
from chiabip158 import PyBIP158
from chiavdf import prove, create_discriminant

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
from src.types.reward_chain_sub_block import RewardChainSubBlock, RewardChainSubBlockUnfinished
from src.types.sized_bytes import bytes32
from src.types.slots import (
    InfusedChallengeChainSubSlot,
    ChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
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
from tests.recursive_replace import recursive_replace


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

    def get_consecutive_blocks(
        self,
        constants: ConsensusConstants,
        num_blocks: int,
        block_list: List[FullBlock] = None,
        farmer_reward_puzzle_hash: Optional[bytes32] = None,
        pool_reward_puzzle_hash: Optional[bytes32] = None,
        fees: uint64 = uint64(0),
        transaction_data_at_height: Dict[int, Tuple[Program, G2Element]] = None,
        seed: bytes = b"",
        timestamp: Optional[uint64] = None,
        force_overflow: bool = False,
        force_empty_slots: uint32 = uint32(0),  # Force at least this number of empty slots before the first SB
    ) -> List[FullBlock]:
        sub_blocks: Dict[uint32, SubBlockRecord] = {}
        height_to_hash: Dict[uint32, bytes32] = {}
        if transaction_data_at_height is None:
            transaction_data_at_height = {}

        # todo init correctly
        overflow_count: uint8 = uint8(0)
        curr_sub_epoch = 0
        curr_epoch = 0
        sub_epoch_summery: Optional[SubEpochSummary] = None

        # todo still not handled
        deficit: uint8 = uint8(0)

        if timestamp is None:
            timestamp = time.time()
        if block_list is None or len(block_list) == 0:
            genesis = self.create_genesis_block(
                constants,
                fees,
                seed,
                force_overflow=force_overflow,
                force_empty_slots=force_empty_slots,
            )
            block_list = [genesis]
            num_blocks -= 1

        if num_blocks == 0:
            return block_list

        difficulty = get_difficulty(block_list, constants, height_to_hash, sub_blocks)

        latest_sub_block: SubBlockRecord = sub_blocks[block_list[-1].header_hash]

        curr = latest_sub_block
        while not curr.first_in_sub_slot:
            curr = sub_blocks[curr.prev_hash]
        curr_challenge: bytes32 = curr.finished_challenge_slot_hashes[-1]

        finished_sub_slots: List[EndOfSubSlotBundle] = []  # Sub-slots since last sub block
        ips: uint64 = latest_sub_block.ips
        slot_iters: uint64 = calculate_slot_iters(constants, ips)
        num_empty_slots_added = 0
        same_slot_as_last = True
        sub_slot_start_total_iters: uint128 = uint128(0)

        # Start at the last block in block list
        # Get the challenge for that slot
        while True:
            print("Starting new slot at iters", sub_slot_start_total_iters)

            # If did not reach empty slot counts, continue
            if num_empty_slots_added >= force_empty_slots:
                # Get all proofs of space for challenge.
                proofs_of_space: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                    constants,
                    curr_challenge,
                    seed,
                    difficulty,
                    ips,
                )

                slot_cc_challenge, slot_rc_challenge = get_challenges(
                    sub_blocks, finished_sub_slots, latest_sub_block.header_hash
                )

                for required_iters, proof_of_space in sorted(proofs_of_space, key=lambda t: t[0]):
                    if same_slot_as_last and required_iters <= latest_sub_block.required_iters:
                        # Ignore this sub-block because it's in the past
                        continue
                    sp_iters: uint64 = calculate_sp_iters(constants, uint64(constants.IPS_STARTING), required_iters)
                    ip_iters = calculate_ip_iters(constants, uint64(constants.IPS_STARTING), required_iters)
                    is_overflow_block = sp_iters > ip_iters
                    if force_overflow and not is_overflow_block:
                        continue

                    unfinished_block = self.create_unfinished_block(
                        constants,
                        sub_slot_start_total_iters,
                        slot_iters,
                        sp_iters,
                        ip_iters,
                        proof_of_space,
                        slot_cc_challenge,
                        slot_rc_challenge,
                        difficulty,
                        farmer_reward_puzzle_hash,
                        pool_reward_puzzle_hash,
                        fees,
                        timestamp,
                        seed,
                        transaction_data_at_height.get(latest_sub_block.height + 1, None),
                        latest_sub_block,
                        sub_blocks,
                        finished_sub_slots,
                    )

                    if unfinished_block is None:
                        continue

                    if not is_overflow_block:
                        cc_vdf_challenge = slot_cc_challenge
                        # non overflow block
                        if len(finished_sub_slots) == 0:
                            prev_ip_iters = calculate_ip_iters(constants, ips, latest_sub_block.required_iters)
                            new_ip_iters = unfinished_block.total_iters - prev_ip_iters
                            cc_vdf_input = latest_sub_block.challenge_vdf_output
                            rc_vdf_challenge = latest_sub_block.reward_infusion_new_challenge
                        else:
                            new_ip_iters = ip_iters
                            cc_vdf_input = ClassgroupElement.get_default_element()
                            rc_vdf_challenge = slot_rc_challenge

                        cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
                            constants,
                            cc_vdf_input,
                            cc_vdf_challenge,
                            new_ip_iters,
                        )
                        print(f"Creating IP challenge for sub block {unfinished_block.total_iters} output {cc_ip_vdf}")
                        icc_ip_vdf, icc_ip_proof = get_icc(
                            constants,
                            unfinished_block.total_iters,
                            finished_sub_slots,
                            latest_sub_block,
                            sub_blocks,
                            sub_slot_start_total_iters,
                        )

                        rc_ip_vdf, rc_ip_proof = get_vdf_info_and_proof(
                            constants,
                            ClassgroupElement.get_default_element(),
                            rc_vdf_challenge,
                            new_ip_iters,
                        )
                        assert unfinished_block is not None
                        full_block: FullBlock = unfinished_block_to_full_block(
                            unfinished_block,
                            cc_ip_vdf,
                            cc_ip_proof,
                            rc_ip_vdf,
                            rc_ip_proof,
                            icc_ip_vdf,
                            icc_ip_proof,
                            finished_sub_slots,
                        )
                        block_list.append(full_block)
                        num_blocks -= 1
                        if num_blocks == 0:
                            return block_list

                        sub_blocks[full_block.header_hash] = full_block_to_sub_block_record(
                            constants,
                            sub_blocks,
                            height_to_hash,
                            full_block,
                            required_iters,
                        )
                        height_to_hash[uint32(full_block.height)] = full_block.header_hash
                        latest_sub_block = sub_blocks[full_block.header_hash]
                        finished_sub_slots = []
                        print(
                            f"Created block {full_block.height} is block: {full_block.is_block()} at iters {full_block.total_iters}"
                        )

                # Finish the end of sub-slot and try again next sub-slot
                # End of sub-slot logic

                if len(finished_sub_slots) == 0:
                    # Sub block has been created within this sub-slot
                    eos_iters = slot_iters - (latest_sub_block.total_iters - sub_slot_start_total_iters)
                    cc_input = latest_sub_block.challenge_vdf_output
                    rc_challenge = latest_sub_block.reward_infusion_new_challenge
                else:
                    # No sub-blocks were successfully created within this sub-slot
                    eos_iters = slot_iters
                    cc_input = ClassgroupElement.get_default_element()
                    rc_challenge = slot_rc_challenge

                cc_vdf, cc_proof = get_vdf_info_and_proof(
                    constants,
                    cc_input,
                    slot_cc_challenge,
                    eos_iters,
                )
                rc_vdf, rc_proof = get_vdf_info_and_proof(
                    constants,
                    ClassgroupElement.get_default_element(),
                    rc_challenge,
                    eos_iters,
                )

                icc_ip_vdf, icc_ip_proof = get_icc(
                    constants,
                    sub_slot_start_total_iters + slot_iters,
                    finished_sub_slots,
                    latest_sub_block,
                    sub_blocks,
                    sub_slot_start_total_iters,
                )
                # End of slot vdf info for icc and cc have to be from challenge block or start of slot, respectively,
                # in order for light clients to validate.
                if icc_ip_vdf is not None:
                    if len(finished_sub_slots) == 0:
                        curr = latest_sub_block
                        while not curr.is_challenge_sub_block(constants) and not curr.first_in_sub_slot:
                            curr = sub_blocks[curr.prev_hash]
                        if curr.is_challenge_sub_block(constants):
                            icc_eos_iters = sub_slot_start_total_iters + slot_iters - curr.total_iters
                        else:
                            icc_eos_iters = slot_iters
                    else:
                        icc_eos_iters = slot_iters
                    icc_ip_vdf = recursive_replace(icc_ip_vdf, "number_of_iterations", icc_eos_iters)
                    icc_sub_slot: Optional[InfusedChallengeChainSubSlot] = InfusedChallengeChainSubSlot(icc_ip_vdf)
                    cc_sub_slot = ChallengeChainSubSlot(cc_vdf, icc_sub_slot.get_hash(), None, None, None)
                else:
                    icc_sub_slot = None
                    cc_sub_slot = ChallengeChainSubSlot(cc_vdf, None, None, None, None)
                cc_sub_slot = recursive_replace(
                    cc_sub_slot, "challenge_chain_end_of_slot_vdf.number_of_iterations", slot_iters
                )

                finished_sub_slots.append(
                    EndOfSubSlotBundle(
                        cc_sub_slot,
                        icc_sub_slot,
                        RewardChainSubSlot(
                            rc_vdf,
                            cc_sub_slot.get_hash(),
                            icc_sub_slot.get_hash() if icc_sub_slot is not None else None,
                            uint8(constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK),
                        ),
                        SubSlotProofs(cc_proof, icc_ip_proof, rc_proof),
                    )
                )
                sub_epoch_summery = handle_end_of_sub_epoch(
                    constants,
                    latest_sub_block,
                    sub_blocks,
                    sub_epoch_summery,
                    overflow_count,
                    difficulty,
                    ips,
                    curr_sub_epoch,
                )

                if sub_epoch_summery is not None:
                    curr_sub_epoch = curr_sub_epoch + 1

                ips, difficulty, new_epoch = handle_end_of_epoch(
                    constants,
                    True,
                    difficulty,
                    deficit,
                    ips,
                    sp_iters,
                    sub_blocks,
                    latest_sub_block,
                    height_to_hash,
                    curr_epoch,
                )
                if new_epoch:
                    curr_epoch = curr_epoch + 1
                overflow_count = uint8(0)

            num_empty_slots_added += 1
            same_slot_as_last = False
            sub_slot_start_total_iters += slot_iters

    def create_unfinished_block(
        self,
        constants: ConsensusConstants,
        sub_slot_start_total_iters: uint128,
        slot_iters: uint64,
        sp_iters: uint64,
        ip_iters: uint64,
        proof_of_space: ProofOfSpace,
        slot_cc_challenge: bytes32,
        slot_rc_challenge: bytes32,
        difficulty: uint64,
        farmer_reward_puzzle_hash: Optional[bytes32] = None,
        pool_reward_puzzle_hash: Optional[bytes32] = None,
        fees: uint64 = uint64(0),
        timestamp: Optional[uint64] = None,
        seed: bytes32 = b"",
        transactions: Optional[Program] = None,
        prev_sub_block: Optional[SubBlockRecord] = None,
        sub_blocks=None,
        finished_sub_slots=None,
    ) -> Optional[UnfinishedBlock]:
        if finished_sub_slots is None:
            finished_sub_slots = []
        if sub_blocks is None:
            sub_blocks = {}
        overflow = sp_iters > ip_iters
        total_iters_sp = sub_slot_start_total_iters + sp_iters
        prev_block: Optional[SubBlockRecord] = None  # Set this if we are a block
        if prev_sub_block is not None:
            height = uint32(prev_sub_block.height + 1)
            weight: uint128 = uint128(prev_sub_block.weight + difficulty)
            curr = prev_sub_block
            while not curr.is_block:
                curr = sub_blocks[curr.prev_hash]
            if total_iters_sp > curr.total_iters:
                prev_block = curr
                is_block = True
            else:
                is_block = False
        else:
            # Genesis is a block
            is_block = True
            height = uint32(0)
            weight: uint128 = uint128(constants.DIFFICULTY_STARTING)

        if sp_iters == 0:
            cc_sp_vdf: Optional[VDFInfo] = None
            cc_sp_proof: Optional[VDFProof] = None
            rc_sp_vdf: Optional[VDFInfo] = None
            rc_sp_proof: Optional[VDFProof] = None
            to_sign_cc: Optional[bytes32] = slot_cc_challenge
            to_sign_rc: Optional[bytes32] = slot_rc_challenge
        else:
            if prev_sub_block is None:
                cc_vdf_input = ClassgroupElement.get_default_element()
                rc_challenge = slot_rc_challenge
                cc_sp_iters = sp_iters
                rc_sp_iters = sp_iters
            elif len(finished_sub_slots) > 0:
                cc_vdf_input = ClassgroupElement.get_default_element()
                rc_challenge = slot_rc_challenge
                cc_sp_iters = sp_iters
                rc_sp_iters = sp_iters
            else:
                curr = prev_sub_block
                while curr.total_iters >= total_iters_sp and not curr.first_in_sub_slot:
                    curr = sub_blocks[curr.prev_hash]
                if curr.total_iters >= total_iters_sp:
                    cc_vdf_input = ClassgroupElement.get_default_element()
                    rc_challenge = curr.finished_reward_slot_hashes[-1]
                    cc_sp_iters = sp_iters
                    rc_sp_iters = sp_iters
                else:
                    cc_vdf_input = curr.challenge_vdf_output
                    rc_challenge = curr.reward_infusion_new_challenge
                    cc_sp_iters = rc_sp_iters = total_iters_sp - curr.total_iters
            print(
                "sub slot start total iters",
                sub_slot_start_total_iters,
                total_iters_sp,
                ip_iters,
                len(finished_sub_slots),
                "challenge: ",
                slot_cc_challenge,
                "input ",
                cc_vdf_input,
            )
            cc_sp_vdf, cc_sp_proof = get_vdf_info_and_proof(
                constants,
                cc_vdf_input,
                slot_cc_challenge,
                cc_sp_iters,
            )
            rc_sp_vdf, rc_sp_proof = get_vdf_info_and_proof(
                constants,
                ClassgroupElement.get_default_element(),
                rc_challenge,
                rc_sp_iters,
            )

            to_sign_cc = cc_sp_vdf.output.get_hash()
            to_sign_rc = rc_sp_vdf.output.get_hash()

        cc_sp_signature: Optional[G2Element] = self.get_plot_signature(to_sign_cc, proof_of_space.plot_public_key)
        rc_sp_signature: Optional[G2Element] = self.get_plot_signature(to_sign_rc, proof_of_space.plot_public_key)
        assert blspy.AugSchemeMPL.verify(proof_of_space.plot_public_key, to_sign_cc, cc_sp_signature)

        # Checks sp filter
        plot_id = proof_of_space.get_plot_id()
        if not ProofOfSpace.can_create_proof(
            constants, plot_id, proof_of_space.challenge_hash, to_sign_cc, cc_sp_signature
        ):
            return None

        total_iters = uint128(sub_slot_start_total_iters + ip_iters + (slot_iters if overflow else 0))

        rc_sub_block = RewardChainSubBlockUnfinished(
            weight,
            height,
            total_iters,
            proof_of_space,
            cc_sp_vdf,
            cc_sp_signature,
            rc_sp_vdf,
            rc_sp_signature,
        )
        if farmer_reward_puzzle_hash is None:
            farmer_reward_puzzle_hash = self.farmer_ph

        foliage_sub_block, foliage_block, transactions_info = self.create_foliage(
            constants,
            rc_sub_block,
            fees,
            None,
            None,
            prev_sub_block,
            prev_block,
            sub_blocks,
            is_block,
            timestamp,
            farmer_reward_puzzle_hash,
            pool_reward_puzzle_hash,
            seed,
        )

        return UnfinishedBlock(
            [],
            rc_sub_block,
            cc_sp_proof,
            rc_sp_proof,
            foliage_sub_block,
            foliage_block,
            transactions_info,
            transactions,
        )

    def create_genesis_block(
        self,
        constants: ConsensusConstants,
        fees: uint64 = 0,
        seed: bytes32 = b"",
        timestamp: Optional[uint64] = None,
        farmer_reward_puzzle_hash: Optional[bytes32] = None,
        force_overflow: bool = False,
        force_empty_slots: uint32 = uint32(0),
    ) -> FullBlock:
        if timestamp is None:
            timestamp = time.time()
        finished_sub_slots: List[EndOfSubSlotBundle] = []
        slot_iters: uint64 = uint64(constants.IPS_STARTING * constants.SLOT_TIME_TARGET)
        unfinished_block: Optional[UnfinishedBlock] = None
        ip_iters: uint64 = uint64(0)
        sub_slot_total_iters: uint128 = uint128(0)

        # Keep trying until we get a good proof of space that also passes sp filter
        while True:
            cc_challenge, rc_challenge = get_genesis_challenges(constants, finished_sub_slots)
            print("cc challenge", cc_challenge)
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

                unfinished_block = self.create_unfinished_block(
                    constants,
                    sub_slot_total_iters,
                    slot_iters,
                    sp_iters,
                    ip_iters,
                    proof_of_space,
                    cc_challenge,
                    rc_challenge,
                    uint64(constants.DIFFICULTY_STARTING),
                    farmer_reward_puzzle_hash,
                    constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH,
                    fees,
                    timestamp,
                    seed,
                    finished_sub_slots=finished_sub_slots,
                )
                if unfinished_block is None:
                    continue

                if not is_overflow_block:
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
                    assert unfinished_block is not None
                    return unfinished_block_to_full_block(
                        unfinished_block,
                        cc_ip_vdf,
                        cc_ip_proof,
                        rc_ip_vdf,
                        rc_ip_proof,
                        None,
                        None,
                        finished_sub_slots,
                    )

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
            if unfinished_block is not None:
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
                # icc_info, icc_proof = self.get_icc()
                return unfinished_block_to_full_block(
                    unfinished_block,
                    cc_ip_vdf,
                    cc_ip_proof,
                    rc_ip_vdf,
                    rc_ip_proof,
                    None,
                    None,
                    finished_sub_slots,
                )
            sub_slot_total_iters += slot_iters

    def create_foliage(
        self,
        constants: ConsensusConstants,
        reward_sub_block: Union[RewardChainSubBlock, RewardChainSubBlockUnfinished],
        fees: uint64,
        aggsig: Optional[G2Element],
        transactions: Optional[Program],
        prev_sub_block: Optional[SubBlockRecord],
        prev_block: Optional[SubBlockRecord],
        sub_blocks: Dict[bytes32, SubBlockRecord],
        is_block: bool,
        timestamp: uint64,
        farmer_reward_puzzlehash: bytes32 = None,
        pool_reward_puzzlehash: bytes32 = None,
        seed: bytes32 = b"",
    ) -> (FoliageSubBlock, Optional[FoliageBlock], Optional[TransactionsInfo]):
        # Use the extension data to create different blocks based on header hash
        random.seed(seed)
        extension_data: bytes32 = random.randint(0, 100000000).to_bytes(32, "big")
        height = reward_sub_block.sub_block_height
        cost: uint64 = uint64(0)
        farmer_ph = self.farmer_ph
        pool_ph = self.pool_ph
        if farmer_reward_puzzlehash is not None:
            farmer_ph = farmer_reward_puzzlehash
        if pool_reward_puzzlehash is not None:
            pool_ph = pool_reward_puzzlehash

        # Create filter
        byte_array_tx: List[bytes32] = []
        tx_additions: List[Coin] = []
        tx_removals: List[bytes32] = []

        pool_target = PoolTarget(pool_ph, uint32(height))
        pool_target_signature = self.get_pool_key_signature(
            pool_target, reward_sub_block.proof_of_space.pool_public_key
        )
        assert pool_target_signature is not None

        foliage_sub_block_data = FoliageSubBlockData(
            reward_sub_block.get_hash(),
            pool_target,
            pool_target_signature,
            farmer_ph,
            extension_data,
        )

        foliage_sub_block_signature: G2Element = self.get_plot_signature(
            foliage_sub_block_data.get_hash(), reward_sub_block.proof_of_space.plot_public_key
        )

        prev_sub_block_hash: bytes32 = constants.GENESIS_PREV_HASH
        if height != 0:
            prev_sub_block_hash = prev_sub_block.header_hash

        if is_block:
            if aggsig is None:
                aggsig = G2Element.infinity()
            # TODO: prev generators root
            pool_coin = create_pool_coin(height, pool_ph, calculate_pool_reward(height))
            farmer_coin = create_farmer_coin(uint32(height), farmer_ph, calculate_base_farmer_reward(uint32(height)))
            reward_claims_incorporated = [pool_coin, farmer_coin]
            if height > 0:
                curr: SubBlockRecord = prev_sub_block
                while not curr.is_block:
                    pool_coin = create_pool_coin(curr.height, curr.pool_puzzle_hash, calculate_pool_reward(curr.height))
                    farmer_coin = create_farmer_coin(
                        curr.height, curr.farmer_puzzle_hash, calculate_base_farmer_reward(curr.height)
                    )
                    reward_claims_incorporated += [pool_coin, farmer_coin]
                    curr = sub_blocks[curr.prev_hash]
            additions: List[Coin] = reward_claims_incorporated
            npc_list = []
            if transactions is not None:
                error, npc_list, _ = get_name_puzzle_conditions(transactions)
                additions += additions_for_npc(npc_list)
            for coin in additions:
                tx_additions.append(coin)
                byte_array_tx.append(bytearray(coin.puzzle_hash))
            for npc in npc_list:
                tx_removals.append(npc.coin_name)
                byte_array_tx.append(bytearray(npc.coin_name))

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

            for coin in tx_additions:
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
            filter_hash: bytes32 = std_hash(encoded)

            transactions_info = TransactionsInfo(
                bytes([0] * 32), generator_hash, aggsig, fees, cost, reward_claims_incorporated
            )
            if prev_block is None:
                prev_block_hash: bytes32 = constants.GENESIS_PREV_HASH
            else:
                prev_block_hash = prev_block.header_hash

            foliage_block = FoliageBlock(
                prev_block_hash,
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
        return found_proofs


def get_challenges(
    sub_blocks: Dict[uint32, SubBlockRecord],
    finished_sub_slots: List[EndOfSubSlotBundle],
    prev_header_hash: bytes32,
):
    if len(finished_sub_slots) == 0:
        curr = sub_blocks[prev_header_hash]
        while True:
            curr = sub_blocks[curr.header_hash]
            if curr.first_in_sub_slot:
                break
        cc_challenge = curr.finished_challenge_slot_hashes[-1]
        rc_challenge = curr.finished_challenge_slot_hashes[-1]
    else:
        cc_challenge = finished_sub_slots[-1].challenge_chain.get_hash()
        rc_challenge = finished_sub_slots[-1].reward_chain.get_hash()
    return cc_challenge, rc_challenge


def get_genesis_challenges(constants, finished_sub_slots):
    if len(finished_sub_slots) == 0:
        challenge = constants.FIRST_CC_CHALLENGE
        rc_challenge = constants.FIRST_RC_CHALLENGE
    else:
        challenge = finished_sub_slots[-1].challenge_chain.get_hash()
        rc_challenge = finished_sub_slots[-1].reward_chain.get_hash()
    return challenge, rc_challenge


def get_vdf_info_and_proof(
    constants: ConsensusConstants,
    vdf_input: ClassgroupElement,
    challenge_hash: bytes32,
    number_iters: uint64,
) -> Tuple[VDFInfo, VDFProof]:
    int_size = (constants.DISCRIMINANT_SIZE_BITS + 16) >> 4

    disc: int = int(
        create_discriminant(challenge_hash, constants.DISCRIMINANT_SIZE_BITS),
        16,
    )
    # print("Disc", disc)
    # print(vdf_input)
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
    # print("Output:", output)
    proof_bytes = result[2 * int_size : 4 * int_size]
    return VDFInfo(challenge_hash, vdf_input, number_iters, output), VDFProof(uint8(0), proof_bytes)


def get_plot_dir():
    cache_path = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/"))) / "test-plots"
    mkdir(cache_path)
    return cache_path


def unfinished_block_to_full_block(
    unfinished_block: UnfinishedBlock,
    cc_ip_vdf: VDFInfo,
    cc_ip_proof: VDFProof,
    rc_ip_vdf: VDFInfo,
    rc_ip_proof: VDFProof,
    icc_ip_vdf: Optional[VDFInfo],
    icc_ip_proof: Optional[VDFProof],
    finished_sub_slots: List[EndOfSubSlotBundle],
):
    ret = FullBlock(
        finished_sub_slots,
        RewardChainSubBlock(
            unfinished_block.reward_chain_sub_block.weight,
            unfinished_block.reward_chain_sub_block.sub_block_height,
            unfinished_block.reward_chain_sub_block.total_iters,
            unfinished_block.reward_chain_sub_block.proof_of_space,
            unfinished_block.reward_chain_sub_block.challenge_chain_sp_vdf,
            unfinished_block.reward_chain_sub_block.challenge_chain_sp_signature,
            cc_ip_vdf,
            unfinished_block.reward_chain_sub_block.reward_chain_sp_vdf,
            unfinished_block.reward_chain_sub_block.reward_chain_sp_signature,
            rc_ip_vdf,
            icc_ip_vdf,
            unfinished_block.foliage_block is not None,
        ),
        unfinished_block.challenge_chain_sp_proof,
        cc_ip_proof,
        unfinished_block.reward_chain_sp_proof,
        rc_ip_proof,
        icc_ip_proof,
        unfinished_block.foliage_sub_block,
        unfinished_block.foliage_block,
        unfinished_block.transactions_info,
        unfinished_block.transactions_generator,
    )
    return recursive_replace(ret, "foliage_sub_block.reward_block_hash", ret.reward_chain_sub_block.get_hash())


def get_difficulty(block_list, constants, height_to_hash, sub_blocks) -> uint64:
    difficulty = 0
    for full_block in block_list:
        if full_block.height == 0:
            difficulty = uint64(constants.DIFFICULTY_STARTING)
        else:
            difficulty = full_block.weight - block_list[full_block.height - 1].weight
        quality_str = full_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(constants)
        required_iters: uint64 = calculate_iterations_quality(
            quality_str,
            full_block.reward_chain_sub_block.proof_of_space.size,
            difficulty,
        )
        sub_blocks[full_block.header_hash] = full_block_to_sub_block_record(
            constants,
            sub_blocks,
            height_to_hash,
            full_block,
            required_iters,
        )
        height_to_hash[uint32(full_block.height)] = full_block.header_hash
    return difficulty


def get_icc(
    constants,
    vdf_end_total_iters: uint128,
    finished_sub_slots: List[EndOfSubSlotBundle],
    latest_sub_block: SubBlockRecord,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    sub_slot_start_total_iters: uint128,
) -> Tuple[Optional[VDFInfo], Optional[VDFProof]]:
    if latest_sub_block.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
        # Curr block has deficit either 4 or 5 so no need for ICC vdfs
        return None, None
    else:
        if len(finished_sub_slots) == 0:
            curr = latest_sub_block  # curr deficit is 0, 1, 2, 3, or 4
            while not curr.is_challenge_sub_block(constants) and not curr.first_in_sub_slot:
                curr = sub_blocks[curr.prev_hash]
            icc_iters = uint64(vdf_end_total_iters - latest_sub_block.total_iters)
            if latest_sub_block.is_challenge_sub_block(constants):
                icc_input = ClassgroupElement.get_default_element()
            else:
                icc_input = latest_sub_block.infused_challenge_vdf_output
            if curr.is_challenge_sub_block(constants):  # Deficit 4
                icc_challenge_hash = curr.challenge_block_info_hash
            else:
                # First sub block in sub slot has deficit 0,1,2 or 3
                icc_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
        else:
            icc_challenge_hash = finished_sub_slots[-1].infused_challenge_chain.get_hash()
            icc_iters = uint64(vdf_end_total_iters - sub_slot_start_total_iters)
            icc_input = ClassgroupElement.get_default_element()

    return get_vdf_info_and_proof(
        constants,
        icc_input,
        icc_challenge_hash,
        icc_iters,
    )


def handle_end_of_epoch(
    constants: ConsensusConstants,
    new_slot: bool,
    difficulty: uint64,
    deficit: uint8,
    ips: uint64,
    sp_iters: uint128,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    prev_block: SubBlockRecord,
    height_to_hash: Dict[uint32, bytes32],
    curr_epoch: int,
):
    new_epoch = False
    if len(sub_blocks.keys()) == constants.EPOCH_SUB_BLOCKS * (curr_epoch + 1):
        new_epoch = True
        # new difficulty
        difficulty = get_next_difficulty(
            constants,
            sub_blocks,
            height_to_hash,
            prev_block.header_hash,
            prev_block.height,
            deficit,
            difficulty,
            new_slot,
            sp_iters,
        )

        # new iterations per slot
        ips = get_next_ips(
            constants,
            height_to_hash,
            sub_blocks,
            prev_block.header_hash,
            prev_block.height,
            deficit,
            ips,
            new_slot,
            sp_iters,
        )

    return ips, difficulty, new_epoch


def handle_end_of_sub_epoch(
    constants: ConsensusConstants,
    prev_block: SubBlockRecord,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    prev_subepoch_summary_hash: bytes32,
    overflow_count: uint8,
    difficulty: uint64,
    ips: uint64,
    curr_sub_epoch: int,
):
    if len(sub_blocks.keys()) == constants.SUB_EPOCH_SUB_BLOCKS * (curr_sub_epoch + 1):
        # update sub_epoch_summery
        sub_epoch_summery = SubEpochSummary(
            prev_subepoch_summary_hash,
            prev_block.reward_chain_sub_block.get_hash(),
            overflow_count,
            difficulty,
            ips,
        )
        return std_hash(sub_epoch_summery)
