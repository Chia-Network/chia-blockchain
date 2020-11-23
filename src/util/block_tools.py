import copy
import os
import random
import shutil
import sys
import tempfile
import time
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable

from blspy import G1Element, G2Element, AugSchemeMPL, PrivateKey
from src.consensus.deficit import calculate_deficit

from src.cmds.init import create_default_chia_config, initialize_ssl
from src.cmds.plots import create_plots
from src.consensus.coinbase import (
    create_puzzlehash_for_pk,
)
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_infusion_point_iters,
    calculate_iterations_quality,
    calculate_sp_iters,
    calculate_sub_slot_iters,
    calculate_sp_interval_iters,
    is_overflow_sub_block,
)
from src.consensus.full_block_to_sub_block_record import full_block_to_sub_block_record
from src.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from src.full_node.signage_point import SignagePoint
from src.full_node.sub_block_record import SubBlockRecord
from src.consensus.vdf_info_computation import get_signage_point_vdf_info
from src.plotting.plot_tools import load_plots, PlotInfo
from src.types.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.pool_target import PoolTarget
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.types.slots import (
    InfusedChallengeChainSubSlot,
    ChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from src.types.spend_bundle import SpendBundle
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.types.vdf import VDFInfo, VDFProof
from src.consensus.block_creation import create_unfinished_block, unfinished_block_to_full_block
from src.util.config import load_config
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint128, uint8
from src.util.keychain import Keychain, bytes_to_mnemonic
from src.util.path import mkdir
from src.util.vdf_prover import get_vdf_info_and_proof
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

            plot_dir = get_plot_dir()
            mkdir(plot_dir)
            temp_dir = plot_dir / "tmp"
            mkdir(temp_dir)
            args = Namespace()
            # Can't go much lower than 18, since plots start having no solutions
            args.size = 18
            # Uses many plots for testing, in order to guarantee proofs of space at every height
            args.num = 160
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
                # No datetime in the filename, to get deterministic filenames and not re-plot
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

    def get_plot_signature(self, m: bytes32, plot_pk: G1Element) -> G2Element:
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

        raise ValueError(f"Do not have key {plot_pk}")

    def get_pool_key_signature(self, pool_target: PoolTarget, pool_pk: G1Element) -> G2Element:
        for sk in self.all_sks:
            sk_child = master_sk_to_pool_sk(sk)
            if sk_child.get_g1() == pool_pk:
                return AugSchemeMPL.sign(sk_child, bytes(pool_target))
        raise ValueError(f"Do not have key {pool_pk}")

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
        transaction_data: Optional[SpendBundle] = None,
        seed: bytes = b"",
        time_per_sub_block: Optional[float] = None,
        force_overflow: bool = False,
        skip_slots: uint32 = uint32(0),  # Force at least this number of empty slots before the first SB
    ) -> List[FullBlock]:
        transaction_data_included = False
        if time_per_sub_block is None:
            time_per_sub_block = constants.SLOT_TIME_TARGET / constants.SLOT_SUB_BLOCKS_TARGET

        if farmer_reward_puzzle_hash is None:
            farmer_reward_puzzle_hash = self.farmer_ph
        if pool_reward_puzzle_hash is None:
            pool_reward_puzzle_hash = self.pool_ph
        pool_target = PoolTarget(pool_reward_puzzle_hash, uint32(0))

        if block_list is None or len(block_list) == 0:
            initial_block_list_len = 0
            genesis = self.create_genesis_block(
                constants,
                seed,
                force_overflow=force_overflow,
                skip_slots=skip_slots,
                timestamp=uint64(int(time.time())),
                farmer_reward_puzzle_hash=farmer_reward_puzzle_hash,
            )
            num_empty_slots_added = skip_slots
            block_list = [genesis]
            num_blocks -= 1
        else:
            initial_block_list_len = len(block_list)
            num_empty_slots_added = 0  # Allows forcing empty slots in the beginning, for testing purposes

        if num_blocks == 0:
            return block_list

        height_to_hash, difficulty, sub_blocks = load_block_list(block_list, constants)

        latest_sub_block: SubBlockRecord = sub_blocks[block_list[-1].header_hash]
        curr = latest_sub_block
        while not curr.is_block:
            curr = sub_blocks[curr.prev_hash]
        start_timestamp = curr.timestamp
        start_height = curr.height

        curr = latest_sub_block
        sub_blocks_added_this_sub_slot = 1
        while not curr.first_in_sub_slot:
            curr = sub_blocks[curr.prev_hash]
            sub_blocks_added_this_sub_slot += 1

        finished_sub_slots_at_sp: List[EndOfSubSlotBundle] = []  # Sub-slots since last sub block, up to signage point
        finished_sub_slots_at_ip: List[EndOfSubSlotBundle] = []  # Sub-slots since last sub block, up to infusion point
        ips: uint64 = latest_sub_block.ips
        sub_slot_iters: uint64 = calculate_sub_slot_iters(constants, ips)  # The number of iterations in one sub-slot
        same_slot_as_last = True  # Only applies to first slot, to prevent old blocks from being added
        sub_slot_start_total_iters: uint128 = latest_sub_block.infusion_sub_slot_total_iters(constants)
        sub_slots_finished = 0
        print(
            f"Latest block {latest_sub_block.height} {latest_sub_block.signage_point_index} {latest_sub_block.total_iters}"
        )

        # Start at the last block in block list
        # Get the challenge for that slot
        while True:
            slot_cc_challenge, slot_rc_challenge = get_challenges(
                sub_blocks, finished_sub_slots_at_sp, latest_sub_block.header_hash
            )
            prev_num_of_blocks = num_blocks
            if num_empty_slots_added < skip_slots:
                # If did not reach the target slots to skip, don't make any proofs for this sub-slot
                num_empty_slots_added += 1
            else:
                # Loop over every signage point (Except for the last ones, which are used for overflows)
                for signage_point_index in range(0, constants.NUM_SPS_SUB_SLOT - constants.NUM_SP_INTERVALS_EXTRA):
                    curr = latest_sub_block
                    while curr.total_iters > sub_slot_start_total_iters + calculate_sp_iters(
                        constants, ips, uint8(signage_point_index)
                    ):
                        if curr.height == 0:
                            break
                        curr = sub_blocks[curr.prev_hash]
                    if curr.total_iters > sub_slot_start_total_iters:
                        finished_sub_slots_at_sp = []

                    signage_point: SignagePoint = get_signage_point(
                        constants,
                        sub_blocks,
                        latest_sub_block,
                        sub_slot_start_total_iters,
                        uint8(signage_point_index),
                        finished_sub_slots_at_sp,
                        ips,
                    )
                    if signage_point_index == 0:
                        cc_sp_output_hash: bytes32 = slot_cc_challenge
                    else:
                        assert signage_point is not None
                        cc_sp_output_hash: bytes32 = signage_point.cc_vdf.output.get_hash()

                    qualified_proofs: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                        constants,
                        slot_cc_challenge,
                        cc_sp_output_hash,
                        seed,
                        difficulty,
                        ips,
                    )

                    for required_iters, proof_of_space in sorted(qualified_proofs, key=lambda t: t[0]):
                        if sub_blocks_added_this_sub_slot == constants.MAX_SLOT_SUB_BLOCKS or force_overflow:
                            break
                        if same_slot_as_last:
                            if signage_point_index < latest_sub_block.signage_point_index:
                                # Ignore this sub-block because it's in the past
                                continue
                            if signage_point_index == latest_sub_block.signage_point_index:
                                # Ignore this sub-block because it's in the past
                                if required_iters <= latest_sub_block.required_iters:
                                    continue
                        assert latest_sub_block.header_hash in sub_blocks
                        if transaction_data_included:
                            transaction_data = None
                        full_block, sub_block_record = get_full_block_and_sub_record(
                            constants,
                            sub_slot_start_total_iters,
                            uint8(signage_point_index),
                            proof_of_space,
                            slot_cc_challenge,
                            slot_rc_challenge,
                            farmer_reward_puzzle_hash,
                            pool_target,
                            start_timestamp,
                            start_height,
                            time_per_sub_block,
                            transaction_data,
                            height_to_hash,
                            difficulty,
                            required_iters,
                            ips,
                            self.get_plot_signature,
                            self.get_pool_key_signature,
                            finished_sub_slots_at_ip,
                            signage_point,
                            seed,
                            latest_sub_block,
                            sub_blocks,
                        )

                        if full_block is None:
                            continue
                        if sub_block_record.is_block:
                            transaction_data_included = True

                        block_list.append(full_block)
                        sub_blocks_added_this_sub_slot += 1
                        num_blocks -= 1
                        if num_blocks == 0:
                            return block_list
                        sub_blocks[full_block.header_hash] = sub_block_record
                        print(f"Added block {sub_block_record.height} ove=False, iters {sub_block_record.total_iters}")
                        height_to_hash[uint32(full_block.height)] = full_block.header_hash
                        latest_sub_block = sub_blocks[full_block.header_hash]
                        finished_sub_slots_at_ip = []

            # Finish the end of sub-slot and try again next sub-slot
            # End of sub-slot logic
            if len(finished_sub_slots_at_ip) == 0:
                # Sub block has been created within this sub-slot
                eos_iters = sub_slot_iters - (latest_sub_block.total_iters - sub_slot_start_total_iters)
                cc_input = latest_sub_block.challenge_vdf_output
                rc_challenge = latest_sub_block.reward_infusion_new_challenge
            else:
                # No sub-blocks were successfully created within this sub-slot
                eos_iters = sub_slot_iters
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

            eos_deficit: uint8 = (
                latest_sub_block.deficit
                if latest_sub_block.deficit > 0
                else constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
            )
            icc_ip_vdf, icc_ip_proof = get_icc(
                constants,
                sub_slot_start_total_iters + sub_slot_iters,
                finished_sub_slots_at_ip,
                latest_sub_block,
                sub_blocks,
                sub_slot_start_total_iters,
                eos_deficit,
            )
            # End of slot vdf info for icc and cc have to be from challenge block or start of slot, respectively,
            # in order for light clients to validate.
            cc_vdf = VDFInfo(
                cc_vdf.challenge_hash, ClassgroupElement.get_default_element(), sub_slot_iters, cc_vdf.output
            )

            sub_epoch_summary: Optional[SubEpochSummary] = next_sub_epoch_summary(
                constants,
                sub_blocks,
                height_to_hash,
                latest_sub_block.signage_point_index,
                latest_sub_block.required_iters,
                block_list[-1],
            )

            if sub_epoch_summary is not None:
                ses_hash = sub_epoch_summary.get_hash()
                new_ips: Optional[uint64] = sub_epoch_summary.new_ips
                new_difficulty: Optional[uint64] = sub_epoch_summary.new_difficulty
                if new_ips is not None:
                    ips = new_ips
                    difficulty = new_difficulty
                print("Sub epoch summary:", sub_epoch_summary)
            else:
                ses_hash = None
                new_ips = None
                new_difficulty = None

            if icc_ip_vdf is not None:
                # Icc vdf (Deficit of latest sub-block is <= 4)
                if len(finished_sub_slots_at_ip) == 0:
                    # This means there are sub-blocks in this sub-slot
                    curr = latest_sub_block
                    while not curr.is_challenge_sub_block(constants) and not curr.first_in_sub_slot:
                        curr = sub_blocks[curr.prev_hash]
                    if curr.is_challenge_sub_block(constants):
                        icc_eos_iters = sub_slot_start_total_iters + sub_slot_iters - curr.total_iters
                    else:
                        icc_eos_iters = sub_slot_iters
                else:
                    # This means there are no sub-blocks in this sub-slot
                    icc_eos_iters = sub_slot_iters
                icc_ip_vdf = VDFInfo(
                    icc_ip_vdf.challenge_hash,
                    ClassgroupElement.get_default_element(),
                    icc_eos_iters,
                    icc_ip_vdf.output,
                )
                icc_sub_slot: Optional[InfusedChallengeChainSubSlot] = InfusedChallengeChainSubSlot(icc_ip_vdf)
                icc_sub_slot_hash = icc_sub_slot.get_hash() if latest_sub_block.deficit == 0 else None
                cc_sub_slot = ChallengeChainSubSlot(cc_vdf, icc_sub_slot_hash, ses_hash, new_ips, new_difficulty)
            else:
                # No icc
                icc_sub_slot = None
                cc_sub_slot = ChallengeChainSubSlot(cc_vdf, None, ses_hash, new_ips, new_difficulty)

            finished_sub_slots_at_ip.append(
                EndOfSubSlotBundle(
                    cc_sub_slot,
                    icc_sub_slot,
                    RewardChainSubSlot(
                        rc_vdf,
                        cc_sub_slot.get_hash(),
                        icc_sub_slot.get_hash() if icc_sub_slot is not None else None,
                        eos_deficit,
                    ),
                    SubSlotProofs(cc_proof, icc_ip_proof, rc_proof),
                )
            )
            finished_sub_slots_eos = finished_sub_slots_at_ip.copy()
            latest_sub_block_eos = latest_sub_block
            overflow_cc_challenge = finished_sub_slots_at_ip[-1].challenge_chain.get_hash()
            overflow_rc_challenge = finished_sub_slots_at_ip[-1].reward_chain.get_hash()

            if transaction_data_included:
                transaction_data = None
            sub_slots_finished += 1
            print(
                f"Sub slot finished. Sub-blocks included: {sub_blocks_added_this_sub_slot} sub_blocks_per_slot: "
                f"{(len(block_list) - initial_block_list_len)/sub_slots_finished}"
            )
            sub_blocks_added_this_sub_slot = 0  # Sub slot ended, overflows are in next sub slot

            if new_ips is None and num_empty_slots_added >= skip_slots:
                # No overflows on new epoch
                for signage_point_index in range(
                    constants.NUM_SPS_SUB_SLOT - constants.NUM_SP_INTERVALS_EXTRA, constants.NUM_SPS_SUB_SLOT
                ):
                    # note that we are passing in the finished slots which include the last slot
                    signage_point: SignagePoint = get_signage_point(
                        constants,
                        sub_blocks,
                        latest_sub_block_eos,
                        sub_slot_start_total_iters,
                        uint8(signage_point_index),
                        finished_sub_slots_eos,
                        ips,
                    )
                    if signage_point_index == 0:
                        cc_sp_output_hash: bytes32 = slot_cc_challenge
                    else:
                        assert signage_point is not None
                        cc_sp_output_hash: bytes32 = signage_point.cc_vdf.output.get_hash()

                    # If did not reach the target slots to skip, don't make any proofs for this sub-slot
                    qualified_proofs: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                        constants,
                        slot_cc_challenge,
                        cc_sp_output_hash,
                        seed,
                        difficulty,
                        ips,
                    )
                    for required_iters, proof_of_space in sorted(qualified_proofs, key=lambda t: t[0]):
                        if sub_blocks_added_this_sub_slot == constants.MAX_SLOT_SUB_BLOCKS:
                            break
                        full_block, sub_block_record = get_full_block_and_sub_record(
                            constants,
                            sub_slot_start_total_iters,
                            uint8(signage_point_index),
                            proof_of_space,
                            slot_cc_challenge,
                            slot_rc_challenge,
                            farmer_reward_puzzle_hash,
                            pool_target,
                            start_timestamp,
                            start_height,
                            time_per_sub_block,
                            transaction_data,
                            height_to_hash,
                            difficulty,
                            required_iters,
                            ips,
                            self.get_plot_signature,
                            self.get_pool_key_signature,
                            finished_sub_slots_at_ip,
                            signage_point,
                            seed,
                            latest_sub_block,
                            sub_blocks,
                            overflow_cc_challenge=overflow_cc_challenge,
                            overflow_rc_challenge=overflow_rc_challenge,
                        )

                        if full_block is None:
                            continue
                        if sub_block_record.is_block:
                            transaction_data_included = True

                        block_list.append(full_block)
                        sub_blocks_added_this_sub_slot += 1
                        print(f"Added block {sub_block_record.height } ov=True, iters {sub_block_record.total_iters}")
                        num_blocks -= 1
                        if num_blocks == 0:
                            return block_list

                        sub_blocks[full_block.header_hash] = sub_block_record
                        height_to_hash[uint32(full_block.height)] = full_block.header_hash
                        latest_sub_block = sub_blocks[full_block.header_hash]
                        finished_sub_slots_at_ip = []

            finished_sub_slots_at_sp = finished_sub_slots_eos.copy()
            same_slot_as_last = False
            sub_slot_start_total_iters += sub_slot_iters
            sub_slot_iters = calculate_sub_slot_iters(constants, ips)
            if num_blocks < prev_num_of_blocks:
                num_empty_slots_added += 1

    def create_genesis_block(
        self,
        constants: ConsensusConstants,
        seed: bytes32 = b"",
        timestamp: Optional[uint64] = None,
        farmer_reward_puzzle_hash: Optional[bytes32] = None,
        force_overflow: bool = False,
        skip_slots: uint32 = uint32(0),
    ) -> FullBlock:
        if timestamp is None:
            timestamp = time.time()

        if farmer_reward_puzzle_hash is None:
            farmer_reward_puzzle_hash = self.farmer_ph
        finished_sub_slots: List[EndOfSubSlotBundle] = []
        sub_slot_iters: uint64 = uint64(constants.IPS_STARTING * constants.SLOT_TIME_TARGET)
        unfinished_block: Optional[UnfinishedBlock] = None
        ip_iters: uint64 = uint64(0)
        sub_slot_total_iters: uint128 = uint128(0)

        # Keep trying until we get a good proof of space that also passes sp filter
        while True:
            cc_challenge, rc_challenge = get_genesis_challenges(constants, finished_sub_slots)
            for signage_point_index in range(0, constants.NUM_SPS_SUB_SLOT):
                signage_point: SignagePoint = get_signage_point(
                    constants,
                    {},
                    None,
                    sub_slot_total_iters,
                    uint8(signage_point_index),
                    finished_sub_slots,
                    constants.IPS_STARTING,
                )
                if signage_point_index == 0:
                    cc_sp_output_hash: bytes32 = cc_challenge
                else:
                    assert signage_point is not None
                    cc_sp_output_hash: bytes32 = signage_point.cc_vdf.output.get_hash()
                    # If did not reach the target slots to skip, don't make any proofs for this sub-slot
                qualified_proofs: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                    constants,
                    cc_challenge,
                    cc_sp_output_hash,
                    seed,
                    constants.DIFFICULTY_STARTING,
                    constants.IPS_STARTING,
                )

                # Try each of the proofs of space
                for required_iters, proof_of_space in qualified_proofs:
                    sp_iters: uint64 = calculate_sp_iters(
                        constants, uint64(constants.IPS_STARTING), uint8(signage_point_index)
                    )
                    ip_iters = calculate_ip_iters(
                        constants, uint64(constants.IPS_STARTING), uint8(signage_point_index), required_iters
                    )
                    is_overflow_block = is_overflow_sub_block(constants, uint8(signage_point_index))
                    if force_overflow and not is_overflow_block:
                        continue
                    if len(finished_sub_slots) < skip_slots:
                        continue

                    unfinished_block = create_unfinished_block(
                        constants,
                        sub_slot_total_iters,
                        uint8(signage_point_index),
                        sp_iters,
                        ip_iters,
                        proof_of_space,
                        cc_challenge,
                        farmer_reward_puzzle_hash,
                        PoolTarget(constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH, uint32(0)),
                        self.get_plot_signature,
                        self.get_pool_key_signature,
                        signage_point,
                        timestamp,
                        seed,
                        finished_sub_slots=finished_sub_slots,
                    )
                    assert unfinished_block is not None
                    if not is_overflow_block:
                        cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
                            constants,
                            ClassgroupElement.get_default_element(),
                            cc_challenge,
                            ip_iters,
                        )
                        cc_ip_vdf = replace(
                            cc_ip_vdf, number_of_iterations=ip_iters, input=ClassgroupElement.get_default_element()
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
                            None,
                            constants.DIFFICULTY_STARTING,
                        )

                if signage_point_index == constants.NUM_SPS_SUB_SLOT - constants.NUM_SP_INTERVALS_EXTRA - 1:
                    # Finish the end of sub-slot and try again next sub-slot
                    cc_vdf, cc_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        cc_challenge,
                        sub_slot_iters,
                    )
                    rc_vdf, rc_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        rc_challenge,
                        sub_slot_iters,
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
                    return unfinished_block_to_full_block(
                        unfinished_block,
                        cc_ip_vdf,
                        cc_ip_proof,
                        rc_ip_vdf,
                        rc_ip_proof,
                        None,
                        None,
                        finished_sub_slots,
                        None,
                        constants.DIFFICULTY_STARTING,
                    )
            sub_slot_total_iters += sub_slot_iters

    def get_pospaces_for_challenge(
        self,
        constants: ConsensusConstants,
        challenge_hash: bytes32,
        signage_point: bytes32,
        seed: bytes,
        difficulty: uint64,
        ips: uint64,
    ) -> List[Tuple[uint64, ProofOfSpace]]:
        found_proofs: List[(uint64, ProofOfSpace)] = []
        plots: List[PlotInfo] = [
            plot_info for _, plot_info in sorted(list(self.plots.items()), key=lambda x: str(x[0]))
        ]
        random.seed(seed)
        for plot_info in plots:
            plot_id = plot_info.prover.get_id()
            if ProofOfSpace.passes_plot_filter(constants, plot_id, challenge_hash, signage_point):
                new_challenge: bytes32 = ProofOfSpace.calculate_new_challenge_hash(
                    plot_id, challenge_hash, signage_point
                )
                qualities = plot_info.prover.get_qualities_for_challenge(new_challenge)

                for proof_index, quality_str in enumerate(qualities):

                    required_iters = calculate_iterations_quality(
                        quality_str,
                        plot_info.prover.get_size(),
                        difficulty,
                        signage_point,
                    )
                    if required_iters < calculate_sp_interval_iters(constants, ips):
                        proof_xs: bytes = plot_info.prover.get_full_proof(new_challenge, proof_index)
                        plot_pk = ProofOfSpace.generate_plot_public_key(
                            plot_info.local_sk.get_g1(),
                            plot_info.farmer_public_key,
                        )
                        proof_of_space: ProofOfSpace = ProofOfSpace(
                            new_challenge,
                            plot_info.pool_public_key,
                            None,
                            plot_pk,
                            plot_info.prover.get_size(),
                            proof_xs,
                        )
                        found_proofs.append((required_iters, proof_of_space))
        random_sample = found_proofs
        if len(found_proofs) >= 1:
            if random.random() < 0.1:
                # Removes some proofs of space to create "random" chains, based on the seed
                random_sample = random.sample(found_proofs, len(found_proofs) - 1)
        return random_sample


def get_signage_point(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    latest_sub_block: Optional[SubBlockRecord],
    sub_slot_start_total_iters: uint128,
    signage_point_index: uint8,
    finished_sub_slots: List[EndOfSubSlotBundle],
    ips: uint64,
) -> SignagePoint:
    if signage_point_index == 0:
        return SignagePoint(None, None, None, None)
    sp_iters = calculate_sp_iters(constants, ips, signage_point_index)
    overflow = is_overflow_sub_block(constants, signage_point_index)
    sp_total_iters = sub_slot_start_total_iters + calculate_sp_iters(constants, ips, signage_point_index)
    (
        cc_vdf_challenge,
        rc_vdf_challenge,
        cc_vdf_input,
        rc_vdf_input,
        cc_vdf_iters,
        rc_vdf_iters,
    ) = get_signage_point_vdf_info(
        constants, finished_sub_slots, overflow, latest_sub_block, sub_blocks, sp_total_iters, sp_iters
    )

    cc_sp_vdf, cc_sp_proof = get_vdf_info_and_proof(
        constants,
        cc_vdf_input,
        cc_vdf_challenge,
        cc_vdf_iters,
    )
    rc_sp_vdf, rc_sp_proof = get_vdf_info_and_proof(
        constants,
        rc_vdf_input,
        rc_vdf_challenge,
        rc_vdf_iters,
    )
    cc_sp_vdf = replace(cc_sp_vdf, number_of_iterations=sp_iters, input=ClassgroupElement.get_default_element())
    return SignagePoint(cc_sp_vdf, cc_sp_proof, rc_sp_vdf, rc_sp_proof)


def finish_sub_block(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    finished_sub_slots: List[EndOfSubSlotBundle],
    sub_slot_start_total_iters: uint128,
    signage_point_index: uint8,
    unfinished_block: UnfinishedBlock,
    required_iters: uint64,
    ip_iters: uint64,
    slot_cc_challenge: bytes32,
    slot_rc_challenge: bytes32,
    latest_sub_block: SubBlockRecord,
    ips: uint64,
    difficulty: uint64,
):
    is_overflow = is_overflow_sub_block(constants, signage_point_index)
    cc_vdf_challenge = slot_cc_challenge
    slot_iters = calculate_sub_slot_iters(constants, ips)
    if len(finished_sub_slots) == 0:
        new_ip_iters = unfinished_block.total_iters - latest_sub_block.total_iters
        cc_vdf_input = latest_sub_block.challenge_vdf_output
        rc_vdf_challenge = latest_sub_block.reward_infusion_new_challenge
    else:
        new_ip_iters = ip_iters
        cc_vdf_input = ClassgroupElement.get_default_element()
        rc_vdf_challenge = slot_rc_challenge
    if new_ip_iters < 0:
        print("Bad here")
    cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
        constants,
        cc_vdf_input,
        cc_vdf_challenge,
        new_ip_iters,
    )
    cc_ip_vdf = replace(cc_ip_vdf, number_of_iterations=ip_iters, input=ClassgroupElement.get_default_element())
    deficit = calculate_deficit(
        constants, latest_sub_block.height + 1, latest_sub_block, is_overflow, len(finished_sub_slots) > 0
    )

    icc_ip_vdf, icc_ip_proof = get_icc(
        constants,
        unfinished_block.total_iters,
        finished_sub_slots,
        latest_sub_block,
        sub_blocks,
        (sub_slot_start_total_iters + slot_iters) if is_overflow else sub_slot_start_total_iters,
        deficit,
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
        latest_sub_block,
        difficulty,
    )

    sub_block_record = full_block_to_sub_block_record(
        constants,
        sub_blocks,
        height_to_hash,
        full_block,
        required_iters,
    )
    return full_block, sub_block_record


def get_challenges(
    sub_blocks: Dict[uint32, SubBlockRecord],
    finished_sub_slots: List[EndOfSubSlotBundle],
    prev_header_hash: bytes32,
):
    if len(finished_sub_slots) == 0:
        curr = sub_blocks[prev_header_hash]
        while not curr.first_in_sub_slot:
            curr = sub_blocks[curr.prev_hash]
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


def get_plot_dir():
    cache_path = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/"))) / "test-plots"
    mkdir(cache_path)
    return cache_path


def load_block_list(
    block_list: List[FullBlock], constants
) -> (Dict[uint32, bytes32], uint64, Dict[uint32, SubBlockRecord]):
    difficulty = 0
    height_to_hash: Dict[uint32, bytes32] = {}
    sub_blocks: Dict[uint32, SubBlockRecord] = {}
    for full_block in block_list:
        if full_block.height == 0:
            difficulty = uint64(constants.DIFFICULTY_STARTING)
        else:
            difficulty = full_block.weight - block_list[full_block.height - 1].weight
        if full_block.reward_chain_sub_block.signage_point_index == 0:
            if len(full_block.finished_sub_slots) > 0:
                sp_hash = full_block.finished_sub_slots[-1].challenge_chain.get_hash()
            else:
                if full_block.height == 0:
                    sp_hash = constants.FIRST_CC_CHALLENGE
                else:
                    curr = sub_blocks[full_block.prev_header_hash]
                    while not curr.first_in_sub_slot:
                        curr = sub_blocks[curr.prev_hash]
                    sp_hash = curr.finished_challenge_slot_hashes[-1]
            challenge = sp_hash
        else:
            challenge = full_block.reward_chain_sub_block.challenge_chain_sp_vdf.challenge_hash
            sp_hash = full_block.reward_chain_sub_block.challenge_chain_sp_vdf.output.get_hash()
        quality_str = full_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
            constants, challenge, sp_hash
        )
        required_iters: uint64 = calculate_iterations_quality(
            quality_str,
            full_block.reward_chain_sub_block.proof_of_space.size,
            difficulty,
            sp_hash,
        )

        sub_blocks[full_block.header_hash] = full_block_to_sub_block_record(
            constants,
            sub_blocks,
            height_to_hash,
            full_block,
            required_iters,
        )
        height_to_hash[uint32(full_block.height)] = full_block.header_hash
    return height_to_hash, difficulty, sub_blocks


def get_icc(
    constants,
    vdf_end_total_iters: uint128,
    finished_sub_slots: List[EndOfSubSlotBundle],
    latest_sub_block: SubBlockRecord,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    sub_slot_start_total_iters: uint128,
    deficit: uint8,
) -> Tuple[Optional[VDFInfo], Optional[VDFProof]]:
    if len(finished_sub_slots) == 0:
        prev_deficit = latest_sub_block.deficit
    else:
        prev_deficit = finished_sub_slots[-1].reward_chain.deficit

    if deficit == prev_deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
        # new slot / overflow sb to new slot / overflow sb
        return None, None

    if deficit == (prev_deficit - 1) == (constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1):
        # new slot / overflow sb to challenge sb
        return None, None

    if len(finished_sub_slots) != 0:
        assert finished_sub_slots[-1].reward_chain.deficit <= (constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1)
        return get_vdf_info_and_proof(
            constants,
            ClassgroupElement.get_default_element(),
            finished_sub_slots[-1].infused_challenge_chain.get_hash(),
            uint64(vdf_end_total_iters - sub_slot_start_total_iters),
        )

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
    return get_vdf_info_and_proof(
        constants,
        icc_input,
        icc_challenge_hash,
        icc_iters,
    )


def get_full_block_and_sub_record(
    constants: ConsensusConstants,
    sub_slot_start_total_iters: uint128,
    signage_point_index: uint8,
    proof_of_space: ProofOfSpace,
    slot_cc_challenge: bytes32,
    slot_rc_challenge: bytes32,
    farmer_reward_puzzle_hash: bytes32,
    pool_target: PoolTarget,
    start_timestamp: uint64,
    start_height: uint32,
    time_per_sub_block: Optional[float],
    transaction_data: Optional[SpendBundle],
    height_to_hash: Dict[uint32, bytes32],
    difficulty: uint64,
    required_iters: uint64,
    ips: uint64,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, G1Element], G2Element],
    finished_sub_slots: List[EndOfSubSlotBundle],
    signage_point: SignagePoint,
    seed: bytes = b"",
    prev_sub_block: Optional[SubBlockRecord] = None,
    sub_blocks: Dict[uint32, SubBlockRecord] = None,
    overflow_cc_challenge: bytes32 = None,
    overflow_rc_challenge: bytes32 = None,
) -> Tuple[FullBlock, SubBlockRecord]:
    sp_iters = calculate_sp_iters(constants, ips, signage_point_index)
    ip_iters = calculate_ip_iters(constants, ips, signage_point_index, required_iters)

    unfinished_block = create_unfinished_block(
        constants,
        sub_slot_start_total_iters,
        signage_point_index,
        sp_iters,
        ip_iters,
        proof_of_space,
        slot_cc_challenge,
        farmer_reward_puzzle_hash,
        pool_target,
        get_plot_signature,
        get_pool_signature,
        signage_point,
        uint64(start_timestamp + int((prev_sub_block.height + 1 - start_height) * time_per_sub_block)),
        seed,
        transaction_data,
        prev_sub_block,
        sub_blocks,
        finished_sub_slots,
    )

    if (overflow_cc_challenge is not None) and (overflow_rc_challenge is not None):
        slot_cc_challenge = overflow_cc_challenge
        slot_rc_challenge = overflow_rc_challenge

    full_block, sub_block_record = finish_sub_block(
        constants,
        sub_blocks,
        height_to_hash,
        finished_sub_slots,
        sub_slot_start_total_iters,
        signage_point_index,
        unfinished_block,
        required_iters,
        ip_iters,
        slot_cc_challenge,
        slot_rc_challenge,
        prev_sub_block,
        ips,
        difficulty,
    )
    return full_block, sub_block_record
