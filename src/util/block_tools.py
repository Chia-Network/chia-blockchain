import copy
import logging
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

from src.consensus.blockchain_interface import BlockchainInterface
from src.consensus.deficit import calculate_deficit

from src.cmds.init import create_default_chia_config, create_all_ssl
from src.cmds.plots import create_plots
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_iterations_quality,
    calculate_sp_iters,
    calculate_sp_interval_iters,
    is_overflow_block,
)
from src.consensus.full_block_to_block_record import block_to_block_record
from src.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from src.full_node.signage_point import SignagePoint
from src.consensus.block_record import BlockRecord
from src.consensus.vdf_info_computation import get_signage_point_vdf_info
from src.plotting.plot_tools import load_plots, PlotInfo
from src.types.blockchain_format.classgroup import ClassgroupElement
from src.types.blockchain_format.coin import Coin
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.blockchain_format.pool_target import PoolTarget
from src.types.blockchain_format.proof_of_space import ProofOfSpace
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.blockchain_format.slots import (
    InfusedChallengeChainSubSlot,
    ChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from src.types.spend_bundle import SpendBundle
from src.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.types.blockchain_format.vdf import VDFInfo, VDFProof
from src.consensus.block_creation import (
    create_unfinished_block,
    unfinished_block_to_full_block,
)
from src.util.bech32m import encode_puzzle_hash
from src.util.block_cache import BlockCache
from src.util.config import load_config, save_config
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
from src.consensus.default_constants import DEFAULT_CONSTANTS

test_constants = DEFAULT_CONSTANTS.replace(
    **{
        "DIFFICULTY_STARTING": 2 ** 12,
        "DISCRIMINANT_SIZE_BITS": 16,
        "SUB_EPOCH_BLOCKS": 140,
        "WEIGHT_PROOF_THRESHOLD": 2,
        "WEIGHT_PROOF_RECENT_BLOCKS": 350,
        "DIFFICULTY_CONSTANT_FACTOR": 33554432,
        "NUM_SPS_SUB_SLOT": 16,  # Must be a power of 2
        "MAX_SUB_SLOT_BLOCKS": 50,
        "EPOCH_BLOCKS": 280,
        "BLOCKS_CACHE_SIZE": 280 + 3 * 50,  # Coordinate with the above values
        "SUB_SLOT_TIME_TARGET": 600,  # The target number of seconds per slot, mainnet 600
        "SUB_SLOT_ITERS_STARTING": 2 ** 10,  # Must be a multiple of 64
        "NUMBER_ZERO_BITS_PLOT_FILTER": 1,  # H(plot signature of the challenge) must start with these many zeroes
        "MAX_FUTURE_TIME": 3600
        * 24
        * 10,  # Allows creating blockchains with timestamps up to 10 days in the future, for testing
        "MEMPOOL_BLOCK_BUFFER": 6,
        "TX_PER_SEC": 1,
        "CLVM_COST_RATIO_CONSTANT": 108,
        "INITIAL_FREEZE_PERIOD": 0,
    }
)


log = logging.getLogger(__name__)


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    def __init__(
        self,
        constants: ConsensusConstants = test_constants,
        root_path: Optional[Path] = None,
    ):
        self._tempdir = None
        if root_path is None:
            self._tempdir = tempfile.TemporaryDirectory()
            root_path = Path(self._tempdir.name)

        self.root_path = root_path
        create_default_chia_config(root_path)
        self.keychain = Keychain("testing-1.8.0", True)
        self.keychain.delete_all_keys()
        self.farmer_master_sk_entropy = std_hash(b"block_tools farmer key")
        self.pool_master_sk_entropy = std_hash(b"block_tools pool key")
        self.farmer_master_sk = self.keychain.add_private_key(bytes_to_mnemonic(self.farmer_master_sk_entropy), "")
        self.pool_master_sk = self.keychain.add_private_key(bytes_to_mnemonic(self.pool_master_sk_entropy), "")
        self.farmer_pk = master_sk_to_farmer_sk(self.farmer_master_sk).get_g1()
        self.pool_pk = master_sk_to_pool_sk(self.pool_master_sk).get_g1()
        self.farmer_ph: bytes32 = create_puzzlehash_for_pk(
            master_sk_to_wallet_sk(self.farmer_master_sk, uint32(0)).get_g1()
        )
        self.pool_ph: bytes32 = create_puzzlehash_for_pk(
            master_sk_to_wallet_sk(self.pool_master_sk, uint32(0)).get_g1()
        )
        self.init_plots(root_path)

        create_all_ssl(root_path)

        self.all_sks: List[PrivateKey] = [sk for sk, _ in self.keychain.get_all_private_keys()]
        self.pool_pubkeys: List[G1Element] = [master_sk_to_pool_sk(sk).get_g1() for sk in self.all_sks]

        farmer_pubkeys: List[G1Element] = [master_sk_to_farmer_sk(sk).get_g1() for sk in self.all_sks]
        if len(self.pool_pubkeys) == 0 or len(farmer_pubkeys) == 0:
            raise RuntimeError("Keys not generated. Run `chia generate keys`")

        _, loaded_plots, _, _ = load_plots({}, {}, farmer_pubkeys, self.pool_pubkeys, None, False, root_path)
        self.plots: Dict[Path, PlotInfo] = loaded_plots
        self._config = load_config(self.root_path, "config.yaml")
        self._config["logging"]["log_stdout"] = True
        self._config["selected_network"] = "testnet0"
        for service in ["harvester", "farmer", "full_node", "wallet", "introducer", "timelord", "pool"]:
            self._config[service]["selected_network"] = "testnet0"
        save_config(self.root_path, "config.yaml", self._config)
        overrides = self._config["network_overrides"][self._config["selected_network"]]
        updated_constants = constants.replace_str_to_bytes(**overrides)

        self.constants = updated_constants

    def init_plots(self, root_path):
        plot_dir = get_plot_dir()
        mkdir(plot_dir)
        temp_dir = plot_dir / "tmp"
        mkdir(temp_dir)
        num_pool_public_key_plots = 15
        num_pool_address_plots = 5
        args = Namespace()
        # Can't go much lower than 20, since plots start having no solutions and more buggy
        args.size = 22
        # Uses many plots for testing, in order to guarantee proofs of space at every height
        args.num = num_pool_public_key_plots  # Some plots created to a pool public key, and some to a pool puzzle hash
        args.buffer = 100
        args.farmer_public_key = bytes(self.farmer_pk).hex()
        args.pool_public_key = bytes(self.pool_pk).hex()
        args.pool_contract_address = None
        args.tmp_dir = temp_dir
        args.tmp2_dir = plot_dir
        args.final_dir = plot_dir
        args.plotid = None
        args.memo = None
        args.buckets = 0
        args.stripe_size = 2000
        args.num_threads = 0
        args.nobitfield = False
        args.exclude_final_dir = False
        args.list_duplicates = False
        test_private_keys = [
            AugSchemeMPL.key_gen(std_hash(i.to_bytes(2, "big")))
            for i in range(num_pool_public_key_plots + num_pool_address_plots)
        ]
        try:
            # No datetime in the filename, to get deterministic filenames and not re-plot
            create_plots(
                args,
                root_path,
                use_datetime=False,
                test_private_keys=test_private_keys[:num_pool_public_key_plots],
            )
            # Create more plots, but to a pool address instead of public key
            args.pool_public_key = None
            args.pool_contract_address = encode_puzzle_hash(self.pool_ph)
            args.num = num_pool_address_plots
            create_plots(
                args,
                root_path,
                use_datetime=False,
                test_private_keys=test_private_keys[num_pool_public_key_plots:],
            )
        except KeyboardInterrupt:
            shutil.rmtree(plot_dir, ignore_errors=True)
            sys.exit(1)

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

    def get_pool_key_signature(self, pool_target: PoolTarget, pool_pk: Optional[G1Element]) -> Optional[G2Element]:
        # Returns the pool signature for the corresponding pk. If no pk is provided, returns None.
        if pool_pk is None:
            return None

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
        num_blocks: int,
        block_list_input: List[FullBlock] = None,
        farmer_reward_puzzle_hash: Optional[bytes32] = None,
        pool_reward_puzzle_hash: Optional[bytes32] = None,
        transaction_data: Optional[SpendBundle] = None,
        seed: bytes = b"",
        time_per_block: Optional[float] = None,
        force_overflow: bool = False,
        skip_slots: int = 0,  # Force at least this number of empty slots before the first SB
        guarantee_transaction_block: bool = False,  # Force that this block must be a tx block
    ) -> List[FullBlock]:
        assert num_blocks > 0
        if block_list_input is not None:
            block_list = block_list_input.copy()
        else:
            block_list = []
        constants = self.constants
        transaction_data_included = False
        if time_per_block is None:
            time_per_block = float(constants.SUB_SLOT_TIME_TARGET) / float(constants.SLOT_BLOCKS_TARGET)

        if farmer_reward_puzzle_hash is None:
            farmer_reward_puzzle_hash = self.farmer_ph

        if len(block_list) == 0:
            initial_block_list_len = 0
            genesis = self.create_genesis_block(
                constants,
                seed,
                force_overflow=force_overflow,
                skip_slots=skip_slots,
                timestamp=uint64(int(time.time())),
            )
            log.info(f"Created block 0 iters: {genesis.total_iters}")
            num_empty_slots_added = skip_slots
            block_list = [genesis]
            num_blocks -= 1
        else:
            initial_block_list_len = len(block_list)
            num_empty_slots_added = uint32(0)  # Allows forcing empty slots in the beginning, for testing purposes

        if num_blocks == 0:
            return block_list

        height_to_hash, difficulty, blocks = load_block_list(block_list, constants)

        latest_block: BlockRecord = blocks[block_list[-1].header_hash]
        curr = latest_block
        while not curr.is_transaction_block:
            curr = blocks[curr.prev_hash]
        start_timestamp = curr.timestamp
        start_height = curr.height

        curr = latest_block
        blocks_added_this_sub_slot = 1

        while not curr.first_in_sub_slot:
            curr = blocks[curr.prev_hash]
            blocks_added_this_sub_slot += 1

        finished_sub_slots_at_sp: List[EndOfSubSlotBundle] = []  # Sub-slots since last block, up to signage point
        finished_sub_slots_at_ip: List[EndOfSubSlotBundle] = []  # Sub-slots since last block, up to infusion point
        sub_slot_iters: uint64 = latest_block.sub_slot_iters  # The number of iterations in one sub-slot
        same_slot_as_last = True  # Only applies to first slot, to prevent old blocks from being added
        sub_slot_start_total_iters: uint128 = latest_block.ip_sub_slot_total_iters(constants)
        sub_slots_finished = 0
        pending_ses: bool = False

        # Start at the last block in block list
        # Get the challenge for that slot
        while True:
            slot_cc_challenge, slot_rc_challenge = get_challenges(
                constants,
                blocks,
                finished_sub_slots_at_sp,
                latest_block.header_hash,
            )
            prev_num_of_blocks = num_blocks
            if num_empty_slots_added < skip_slots:
                # If did not reach the target slots to skip, don't make any proofs for this sub-slot
                num_empty_slots_added += 1
            else:
                # Loop over every signage point (Except for the last ones, which are used for overflows)
                for signage_point_index in range(0, constants.NUM_SPS_SUB_SLOT - constants.NUM_SP_INTERVALS_EXTRA):
                    curr = latest_block
                    while curr.total_iters > sub_slot_start_total_iters + calculate_sp_iters(
                        constants, sub_slot_iters, uint8(signage_point_index)
                    ):
                        if curr.height == 0:
                            break
                        curr = blocks[curr.prev_hash]
                    if curr.total_iters > sub_slot_start_total_iters:
                        finished_sub_slots_at_sp = []

                    if same_slot_as_last:
                        if signage_point_index < latest_block.signage_point_index:
                            # Ignore this signage_point because it's in the past
                            continue

                    signage_point: SignagePoint = get_signage_point(
                        constants,
                        BlockCache(blocks),
                        latest_block,
                        sub_slot_start_total_iters,
                        uint8(signage_point_index),
                        finished_sub_slots_at_sp,
                        sub_slot_iters,
                    )
                    if signage_point_index == 0:
                        cc_sp_output_hash: bytes32 = slot_cc_challenge
                    else:
                        assert signage_point.cc_vdf is not None
                        cc_sp_output_hash = signage_point.cc_vdf.output.get_hash()

                    qualified_proofs: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                        constants,
                        slot_cc_challenge,
                        cc_sp_output_hash,
                        seed,
                        difficulty,
                        sub_slot_iters,
                    )

                    for required_iters, proof_of_space in sorted(qualified_proofs, key=lambda t: t[0]):
                        if blocks_added_this_sub_slot == constants.MAX_SUB_SLOT_BLOCKS or force_overflow:
                            break
                        if same_slot_as_last:
                            if signage_point_index == latest_block.signage_point_index:
                                # Ignore this block because it's in the past
                                if required_iters <= latest_block.required_iters:
                                    continue
                        assert latest_block.header_hash in blocks
                        additions = None
                        removals = None
                        if transaction_data_included:
                            transaction_data = None
                        if transaction_data is not None and not transaction_data_included:
                            additions = transaction_data.additions()
                            removals = transaction_data.removals()
                        assert start_timestamp is not None
                        if proof_of_space.pool_contract_puzzle_hash is not None:
                            if pool_reward_puzzle_hash is not None:
                                # The caller wants to be paid to a specific address, but this PoSpace is tied to an
                                # address, so continue until a proof of space tied to a pk is found
                                continue
                            pool_target = PoolTarget(proof_of_space.pool_contract_puzzle_hash, uint32(0))
                        else:
                            if pool_reward_puzzle_hash is not None:
                                pool_target = PoolTarget(pool_reward_puzzle_hash, uint32(0))
                            else:
                                pool_target = PoolTarget(self.pool_ph, uint32(0))

                        full_block, block_record = get_full_block_and_sub_record(
                            constants,
                            blocks,
                            sub_slot_start_total_iters,
                            uint8(signage_point_index),
                            proof_of_space,
                            slot_cc_challenge,
                            slot_rc_challenge,
                            farmer_reward_puzzle_hash,
                            pool_target,
                            start_timestamp,
                            start_height,
                            time_per_block,
                            transaction_data,
                            additions,
                            removals,
                            height_to_hash,
                            difficulty,
                            required_iters,
                            sub_slot_iters,
                            self.get_plot_signature,
                            self.get_pool_key_signature,
                            finished_sub_slots_at_ip,
                            signage_point,
                            latest_block,
                            seed,
                        )
                        if block_record.is_transaction_block:
                            transaction_data_included = True
                        else:
                            if guarantee_transaction_block:
                                continue
                        if pending_ses:
                            pending_ses = False
                        block_list.append(full_block)
                        blocks_added_this_sub_slot += 1

                        blocks[full_block.header_hash] = block_record
                        log.info(f"Created block {block_record.height} ove=False, iters " f"{block_record.total_iters}")
                        height_to_hash[uint32(full_block.height)] = full_block.header_hash
                        latest_block = blocks[full_block.header_hash]
                        finished_sub_slots_at_ip = []
                        num_blocks -= 1
                        if num_blocks == 0:
                            return block_list

            # Finish the end of sub-slot and try again next sub-slot
            # End of sub-slot logic
            if len(finished_sub_slots_at_ip) == 0:
                # Block has been created within this sub-slot
                eos_iters: uint64 = uint64(sub_slot_iters - (latest_block.total_iters - sub_slot_start_total_iters))
                cc_input: ClassgroupElement = latest_block.challenge_vdf_output
                rc_challenge: bytes32 = latest_block.reward_infusion_new_challenge
            else:
                # No blocks were successfully created within this sub-slot
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
                latest_block.deficit if latest_block.deficit > 0 else constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
            )
            icc_ip_vdf, icc_ip_proof = get_icc(
                constants,
                uint128(sub_slot_start_total_iters + sub_slot_iters),
                finished_sub_slots_at_ip,
                latest_block,
                blocks,
                sub_slot_start_total_iters,
                eos_deficit,
            )
            # End of slot vdf info for icc and cc have to be from challenge block or start of slot, respectively,
            # in order for light clients to validate.
            cc_vdf = VDFInfo(cc_vdf.challenge, sub_slot_iters, cc_vdf.output)

            if pending_ses:
                sub_epoch_summary: Optional[SubEpochSummary] = None
            else:
                sub_epoch_summary = next_sub_epoch_summary(
                    constants,
                    BlockCache(blocks, height_to_hash),
                    latest_block.required_iters,
                    block_list[-1],
                    False,
                )
                pending_ses = True

            if sub_epoch_summary is not None:
                ses_hash = sub_epoch_summary.get_hash()
                new_sub_slot_iters: Optional[uint64] = sub_epoch_summary.new_sub_slot_iters
                new_difficulty: Optional[uint64] = sub_epoch_summary.new_difficulty

                log.info(f"Sub epoch summary: {sub_epoch_summary}")
            else:
                ses_hash = None
                new_sub_slot_iters = None
                new_difficulty = None

            if icc_ip_vdf is not None:
                # Icc vdf (Deficit of latest block is <= 4)
                if len(finished_sub_slots_at_ip) == 0:
                    # This means there are blocks in this sub-slot
                    curr = latest_block
                    while not curr.is_challenge_block(constants) and not curr.first_in_sub_slot:
                        curr = blocks[curr.prev_hash]
                    if curr.is_challenge_block(constants):
                        icc_eos_iters = uint64(sub_slot_start_total_iters + sub_slot_iters - curr.total_iters)
                    else:
                        icc_eos_iters = sub_slot_iters
                else:
                    # This means there are no blocks in this sub-slot
                    icc_eos_iters = sub_slot_iters
                icc_ip_vdf = VDFInfo(
                    icc_ip_vdf.challenge,
                    icc_eos_iters,
                    icc_ip_vdf.output,
                )
                icc_sub_slot: Optional[InfusedChallengeChainSubSlot] = InfusedChallengeChainSubSlot(icc_ip_vdf)
                assert icc_sub_slot is not None
                icc_sub_slot_hash = icc_sub_slot.get_hash() if latest_block.deficit == 0 else None
                cc_sub_slot = ChallengeChainSubSlot(
                    cc_vdf,
                    icc_sub_slot_hash,
                    ses_hash,
                    new_sub_slot_iters,
                    new_difficulty,
                )
            else:
                # No icc
                icc_sub_slot = None
                cc_sub_slot = ChallengeChainSubSlot(cc_vdf, None, ses_hash, new_sub_slot_iters, new_difficulty)

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
            latest_block_eos = latest_block
            overflow_cc_challenge = finished_sub_slots_at_ip[-1].challenge_chain.get_hash()
            overflow_rc_challenge = finished_sub_slots_at_ip[-1].reward_chain.get_hash()
            additions = None
            removals = None
            if transaction_data_included:
                transaction_data = None
            if transaction_data is not None and not transaction_data_included:
                additions = transaction_data.additions()
                removals = transaction_data.removals()
            sub_slots_finished += 1
            log.info(
                f"Sub slot finished. blocks included: {blocks_added_this_sub_slot} blocks_per_slot: "
                f"{(len(block_list) - initial_block_list_len)/sub_slots_finished}"
            )
            blocks_added_this_sub_slot = 0  # Sub slot ended, overflows are in next sub slot

            # Handle overflows: No overflows on new epoch
            if new_sub_slot_iters is None and num_empty_slots_added >= skip_slots and new_difficulty is None:
                for signage_point_index in range(
                    constants.NUM_SPS_SUB_SLOT - constants.NUM_SP_INTERVALS_EXTRA,
                    constants.NUM_SPS_SUB_SLOT,
                ):
                    # note that we are passing in the finished slots which include the last slot
                    signage_point = get_signage_point(
                        constants,
                        BlockCache(blocks),
                        latest_block_eos,
                        sub_slot_start_total_iters,
                        uint8(signage_point_index),
                        finished_sub_slots_eos,
                        sub_slot_iters,
                    )
                    if signage_point_index == 0:
                        cc_sp_output_hash = slot_cc_challenge
                    else:
                        assert signage_point is not None
                        assert signage_point.cc_vdf is not None
                        cc_sp_output_hash = signage_point.cc_vdf.output.get_hash()

                    # If did not reach the target slots to skip, don't make any proofs for this sub-slot
                    qualified_proofs = self.get_pospaces_for_challenge(
                        constants,
                        slot_cc_challenge,
                        cc_sp_output_hash,
                        seed,
                        difficulty,
                        sub_slot_iters,
                    )
                    for required_iters, proof_of_space in sorted(qualified_proofs, key=lambda t: t[0]):
                        if blocks_added_this_sub_slot == constants.MAX_SUB_SLOT_BLOCKS:
                            break
                        assert start_timestamp is not None

                        if proof_of_space.pool_contract_puzzle_hash is not None:
                            if pool_reward_puzzle_hash is not None:
                                # The caller wants to be paid to a specific address, but this PoSpace is tied to an
                                # address, so continue until a proof of space tied to a pk is found
                                continue
                            pool_target = PoolTarget(proof_of_space.pool_contract_puzzle_hash, uint32(0))
                        else:
                            if pool_reward_puzzle_hash is not None:
                                pool_target = PoolTarget(pool_reward_puzzle_hash, uint32(0))
                            else:
                                pool_target = PoolTarget(self.pool_ph, uint32(0))
                        full_block, block_record = get_full_block_and_sub_record(
                            constants,
                            blocks,
                            sub_slot_start_total_iters,
                            uint8(signage_point_index),
                            proof_of_space,
                            slot_cc_challenge,
                            slot_rc_challenge,
                            farmer_reward_puzzle_hash,
                            pool_target,
                            start_timestamp,
                            start_height,
                            time_per_block,
                            transaction_data,
                            additions,
                            removals,
                            height_to_hash,
                            difficulty,
                            required_iters,
                            sub_slot_iters,
                            self.get_plot_signature,
                            self.get_pool_key_signature,
                            finished_sub_slots_at_ip,
                            signage_point,
                            latest_block,
                            seed,
                            overflow_cc_challenge=overflow_cc_challenge,
                            overflow_rc_challenge=overflow_rc_challenge,
                        )

                        if block_record.is_transaction_block:
                            transaction_data_included = True
                        elif guarantee_transaction_block:
                            continue
                        if pending_ses:
                            pending_ses = False

                        block_list.append(full_block)
                        blocks_added_this_sub_slot += 1
                        log.info(f"Created block {block_record.height } ov=True, iters " f"{block_record.total_iters}")
                        num_blocks -= 1
                        if num_blocks == 0:
                            return block_list

                        blocks[full_block.header_hash] = block_record
                        height_to_hash[uint32(full_block.height)] = full_block.header_hash
                        latest_block = blocks[full_block.header_hash]
                        finished_sub_slots_at_ip = []

            finished_sub_slots_at_sp = finished_sub_slots_eos.copy()
            same_slot_as_last = False
            sub_slot_start_total_iters = uint128(sub_slot_start_total_iters + sub_slot_iters)
            if num_blocks < prev_num_of_blocks:
                num_empty_slots_added += 1

            if new_sub_slot_iters is not None:
                assert new_difficulty is not None
                sub_slot_iters = new_sub_slot_iters
                difficulty = new_difficulty

    def create_genesis_block(
        self,
        constants: ConsensusConstants,
        seed: bytes32 = b"",
        timestamp: Optional[uint64] = None,
        force_overflow: bool = False,
        skip_slots: int = 0,
    ) -> FullBlock:
        if timestamp is None:
            timestamp = uint64(int(time.time()))

        finished_sub_slots: List[EndOfSubSlotBundle] = []
        unfinished_block: Optional[UnfinishedBlock] = None
        ip_iters: uint64 = uint64(0)
        sub_slot_total_iters: uint128 = uint128(0)

        # Keep trying until we get a good proof of space that also passes sp filter
        while True:
            cc_challenge, rc_challenge = get_challenges(constants, {}, finished_sub_slots, None)
            for signage_point_index in range(0, constants.NUM_SPS_SUB_SLOT):
                signage_point: SignagePoint = get_signage_point(
                    constants,
                    BlockCache({}, {}),
                    None,
                    sub_slot_total_iters,
                    uint8(signage_point_index),
                    finished_sub_slots,
                    constants.SUB_SLOT_ITERS_STARTING,
                )
                if signage_point_index == 0:
                    cc_sp_output_hash: bytes32 = cc_challenge
                else:
                    assert signage_point is not None
                    assert signage_point.cc_vdf is not None
                    cc_sp_output_hash = signage_point.cc_vdf.output.get_hash()
                    # If did not reach the target slots to skip, don't make any proofs for this sub-slot
                qualified_proofs: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                    constants,
                    cc_challenge,
                    cc_sp_output_hash,
                    seed,
                    constants.DIFFICULTY_STARTING,
                    constants.SUB_SLOT_ITERS_STARTING,
                )

                # Try each of the proofs of space
                for required_iters, proof_of_space in qualified_proofs:
                    sp_iters: uint64 = calculate_sp_iters(
                        constants,
                        uint64(constants.SUB_SLOT_ITERS_STARTING),
                        uint8(signage_point_index),
                    )
                    ip_iters = calculate_ip_iters(
                        constants,
                        uint64(constants.SUB_SLOT_ITERS_STARTING),
                        uint8(signage_point_index),
                        required_iters,
                    )
                    is_overflow = is_overflow_block(constants, uint8(signage_point_index))
                    if force_overflow and not is_overflow:
                        continue
                    if len(finished_sub_slots) < skip_slots:
                        continue

                    unfinished_block = create_unfinished_block(
                        constants,
                        sub_slot_total_iters,
                        constants.SUB_SLOT_ITERS_STARTING,
                        uint8(signage_point_index),
                        sp_iters,
                        ip_iters,
                        proof_of_space,
                        cc_challenge,
                        constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH,
                        PoolTarget(constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH, uint32(0)),
                        self.get_plot_signature,
                        self.get_pool_key_signature,
                        signage_point,
                        timestamp,
                        BlockCache({}),
                        seed=seed,
                        finished_sub_slots_input=finished_sub_slots,
                    )
                    assert unfinished_block is not None
                    if not is_overflow:
                        cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
                            constants,
                            ClassgroupElement.get_default_element(),
                            cc_challenge,
                            ip_iters,
                        )
                        cc_ip_vdf = replace(cc_ip_vdf, number_of_iterations=ip_iters)
                        rc_ip_vdf, rc_ip_proof = get_vdf_info_and_proof(
                            constants,
                            ClassgroupElement.get_default_element(),
                            rc_challenge,
                            ip_iters,
                        )
                        assert unfinished_block is not None
                        total_iters_sp = uint128(sub_slot_total_iters + sp_iters)
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
                            BlockCache({}),
                            total_iters_sp,
                            constants.DIFFICULTY_STARTING,
                        )

                if signage_point_index == constants.NUM_SPS_SUB_SLOT - constants.NUM_SP_INTERVALS_EXTRA - 1:
                    # Finish the end of sub-slot and try again next sub-slot
                    cc_vdf, cc_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        cc_challenge,
                        constants.SUB_SLOT_ITERS_STARTING,
                    )
                    rc_vdf, rc_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        rc_challenge,
                        constants.SUB_SLOT_ITERS_STARTING,
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
                                uint8(constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK),
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
                    total_iters_sp = uint128(
                        sub_slot_total_iters
                        + calculate_sp_iters(
                            self.constants,
                            self.constants.SUB_SLOT_ITERS_STARTING,
                            unfinished_block.reward_chain_block.signage_point_index,
                        )
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
                        BlockCache({}),
                        total_iters_sp,
                        constants.DIFFICULTY_STARTING,
                    )
            sub_slot_total_iters = uint128(sub_slot_total_iters + constants.SUB_SLOT_ITERS_STARTING)

    def get_pospaces_for_challenge(
        self,
        constants: ConsensusConstants,
        challenge_hash: bytes32,
        signage_point: bytes32,
        seed: bytes,
        difficulty: uint64,
        sub_slot_iters: uint64,
    ) -> List[Tuple[uint64, ProofOfSpace]]:
        found_proofs: List[Tuple[uint64, ProofOfSpace]] = []
        plots: List[PlotInfo] = [
            plot_info for _, plot_info in sorted(list(self.plots.items()), key=lambda x: str(x[0]))
        ]
        random.seed(seed)
        for plot_info in plots:
            plot_id = plot_info.prover.get_id()
            if ProofOfSpace.passes_plot_filter(constants, plot_id, challenge_hash, signage_point):
                new_challenge: bytes32 = ProofOfSpace.calculate_pos_challenge(plot_id, challenge_hash, signage_point)
                qualities = plot_info.prover.get_qualities_for_challenge(new_challenge)

                for proof_index, quality_str in enumerate(qualities):

                    required_iters = calculate_iterations_quality(
                        constants.DIFFICULTY_CONSTANT_FACTOR,
                        quality_str,
                        plot_info.prover.get_size(),
                        difficulty,
                        signage_point,
                    )
                    if required_iters < calculate_sp_interval_iters(constants, sub_slot_iters):
                        proof_xs: bytes = plot_info.prover.get_full_proof(new_challenge, proof_index)
                        plot_pk = ProofOfSpace.generate_plot_public_key(
                            plot_info.local_sk.get_g1(),
                            plot_info.farmer_public_key,
                        )
                        proof_of_space: ProofOfSpace = ProofOfSpace(
                            new_challenge,
                            plot_info.pool_public_key,
                            plot_info.pool_contract_puzzle_hash,
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
    blocks: BlockchainInterface,
    latest_block: Optional[BlockRecord],
    sub_slot_start_total_iters: uint128,
    signage_point_index: uint8,
    finished_sub_slots: List[EndOfSubSlotBundle],
    sub_slot_iters: uint64,
) -> SignagePoint:
    if signage_point_index == 0:
        return SignagePoint(None, None, None, None)
    sp_iters = calculate_sp_iters(constants, sub_slot_iters, signage_point_index)
    overflow = is_overflow_block(constants, signage_point_index)
    sp_total_iters = uint128(
        sub_slot_start_total_iters + calculate_sp_iters(constants, sub_slot_iters, signage_point_index)
    )

    (
        cc_vdf_challenge,
        rc_vdf_challenge,
        cc_vdf_input,
        rc_vdf_input,
        cc_vdf_iters,
        rc_vdf_iters,
    ) = get_signage_point_vdf_info(
        constants,
        finished_sub_slots,
        overflow,
        latest_block,
        blocks,
        sp_total_iters,
        sp_iters,
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
    cc_sp_vdf = replace(cc_sp_vdf, number_of_iterations=sp_iters)
    return SignagePoint(cc_sp_vdf, cc_sp_proof, rc_sp_vdf, rc_sp_proof)


def finish_block(
    constants: ConsensusConstants,
    blocks: Dict[bytes32, BlockRecord],
    height_to_hash: Dict[uint32, bytes32],
    finished_sub_slots: List[EndOfSubSlotBundle],
    sub_slot_start_total_iters: uint128,
    signage_point_index: uint8,
    unfinished_block: UnfinishedBlock,
    required_iters: uint64,
    ip_iters: uint64,
    slot_cc_challenge: bytes32,
    slot_rc_challenge: bytes32,
    latest_block: BlockRecord,
    sub_slot_iters: uint64,
    difficulty: uint64,
):
    is_overflow = is_overflow_block(constants, signage_point_index)
    cc_vdf_challenge = slot_cc_challenge
    if len(finished_sub_slots) == 0:
        new_ip_iters = unfinished_block.total_iters - latest_block.total_iters
        cc_vdf_input = latest_block.challenge_vdf_output
        rc_vdf_challenge = latest_block.reward_infusion_new_challenge
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
    cc_ip_vdf = replace(cc_ip_vdf, number_of_iterations=ip_iters)
    deficit = calculate_deficit(
        constants,
        uint32(latest_block.height + 1),
        latest_block,
        is_overflow,
        len(finished_sub_slots),
    )

    icc_ip_vdf, icc_ip_proof = get_icc(
        constants,
        unfinished_block.total_iters,
        finished_sub_slots,
        latest_block,
        blocks,
        uint128(sub_slot_start_total_iters + sub_slot_iters) if is_overflow else sub_slot_start_total_iters,
        deficit,
    )

    rc_ip_vdf, rc_ip_proof = get_vdf_info_and_proof(
        constants,
        ClassgroupElement.get_default_element(),
        rc_vdf_challenge,
        new_ip_iters,
    )
    assert unfinished_block is not None
    sp_total_iters = uint128(
        sub_slot_start_total_iters + calculate_sp_iters(constants, sub_slot_iters, signage_point_index)
    )
    full_block: FullBlock = unfinished_block_to_full_block(
        unfinished_block,
        cc_ip_vdf,
        cc_ip_proof,
        rc_ip_vdf,
        rc_ip_proof,
        icc_ip_vdf,
        icc_ip_proof,
        finished_sub_slots,
        latest_block,
        BlockCache(blocks),
        sp_total_iters,
        difficulty,
    )

    block_record = block_to_block_record(constants, BlockCache(blocks), required_iters, full_block, None)
    return full_block, block_record


def get_challenges(
    constants: ConsensusConstants,
    blocks: Dict[uint32, BlockRecord],
    finished_sub_slots: List[EndOfSubSlotBundle],
    prev_header_hash: Optional[bytes32],
):
    if len(finished_sub_slots) == 0:
        if prev_header_hash is None:
            return constants.GENESIS_CHALLENGE, constants.GENESIS_CHALLENGE
        curr = blocks[prev_header_hash]
        while not curr.first_in_sub_slot:
            curr = blocks[curr.prev_hash]
        assert curr.finished_challenge_slot_hashes is not None
        assert curr.finished_reward_slot_hashes is not None
        cc_challenge = curr.finished_challenge_slot_hashes[-1]
        rc_challenge = curr.finished_reward_slot_hashes[-1]
    else:
        cc_challenge = finished_sub_slots[-1].challenge_chain.get_hash()
        rc_challenge = finished_sub_slots[-1].reward_chain.get_hash()
    return cc_challenge, rc_challenge


def get_plot_dir():
    cache_path = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/"))) / "test-plots"
    mkdir(cache_path)
    return cache_path


def load_block_list(
    block_list: List[FullBlock], constants
) -> Tuple[Dict[uint32, bytes32], uint64, Dict[uint32, BlockRecord]]:
    difficulty = 0
    height_to_hash: Dict[uint32, bytes32] = {}
    blocks: Dict[uint32, BlockRecord] = {}
    for full_block in block_list:
        if full_block.height == 0:
            difficulty = uint64(constants.DIFFICULTY_STARTING)
        else:
            difficulty = full_block.weight - block_list[full_block.height - 1].weight
        if full_block.reward_chain_block.signage_point_index == 0:
            challenge = full_block.reward_chain_block.pos_ss_cc_challenge_hash
            sp_hash = challenge
        else:
            assert full_block.reward_chain_block.challenge_chain_sp_vdf is not None
            challenge = full_block.reward_chain_block.challenge_chain_sp_vdf.challenge
            sp_hash = full_block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
        quality_str = full_block.reward_chain_block.proof_of_space.verify_and_get_quality_string(
            constants, challenge, sp_hash
        )
        required_iters: uint64 = calculate_iterations_quality(
            constants.DIFFICULTY_CONSTANT_FACTOR,
            quality_str,
            full_block.reward_chain_block.proof_of_space.size,
            uint64(difficulty),
            sp_hash,
        )

        blocks[full_block.header_hash] = block_to_block_record(
            constants,
            BlockCache(blocks),
            required_iters,
            full_block,
            None,
        )
        height_to_hash[uint32(full_block.height)] = full_block.header_hash
    return height_to_hash, uint64(difficulty), blocks


def get_icc(
    constants,
    vdf_end_total_iters: uint128,
    finished_sub_slots: List[EndOfSubSlotBundle],
    latest_block: BlockRecord,
    blocks: Dict[bytes32, BlockRecord],
    sub_slot_start_total_iters: uint128,
    deficit: uint8,
) -> Tuple[Optional[VDFInfo], Optional[VDFProof]]:
    if len(finished_sub_slots) == 0:
        prev_deficit = latest_block.deficit
    else:
        prev_deficit = finished_sub_slots[-1].reward_chain.deficit

    if deficit == prev_deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
        # new slot / overflow sb to new slot / overflow sb
        return None, None

    if deficit == (prev_deficit - 1) == (constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1):
        # new slot / overflow sb to challenge sb
        return None, None

    if len(finished_sub_slots) != 0:
        last_ss = finished_sub_slots[-1]
        assert last_ss.infused_challenge_chain is not None
        assert finished_sub_slots[-1].reward_chain.deficit <= (constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1)
        return get_vdf_info_and_proof(
            constants,
            ClassgroupElement.get_default_element(),
            last_ss.infused_challenge_chain.get_hash(),
            uint64(vdf_end_total_iters - sub_slot_start_total_iters),
        )

    curr = latest_block  # curr deficit is 0, 1, 2, 3, or 4
    while not curr.is_challenge_block(constants) and not curr.first_in_sub_slot:
        curr = blocks[curr.prev_hash]
    icc_iters = uint64(vdf_end_total_iters - latest_block.total_iters)
    if latest_block.is_challenge_block(constants):
        icc_input = ClassgroupElement.get_default_element()
    else:
        icc_input = latest_block.infused_challenge_vdf_output
    if curr.is_challenge_block(constants):  # Deficit 4
        icc_challenge_hash = curr.challenge_block_info_hash
    else:
        assert curr.finished_infused_challenge_slot_hashes is not None
        # First block in sub slot has deficit 0,1,2 or 3
        icc_challenge_hash = curr.finished_infused_challenge_slot_hashes[-1]
    return get_vdf_info_and_proof(
        constants,
        icc_input,
        icc_challenge_hash,
        icc_iters,
    )


def get_full_block_and_sub_record(
    constants: ConsensusConstants,
    blocks: Dict[uint32, BlockRecord],
    sub_slot_start_total_iters: uint128,
    signage_point_index: uint8,
    proof_of_space: ProofOfSpace,
    slot_cc_challenge: bytes32,
    slot_rc_challenge: bytes32,
    farmer_reward_puzzle_hash: bytes32,
    pool_target: PoolTarget,
    start_timestamp: uint64,
    start_height: uint32,
    time_per_block: float,
    transaction_data: Optional[SpendBundle],
    additions: Optional[List[Coin]],
    removals: Optional[List[Coin]],
    height_to_hash: Dict[uint32, bytes32],
    difficulty: uint64,
    required_iters: uint64,
    sub_slot_iters: uint64,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, Optional[G1Element]], Optional[G2Element]],
    finished_sub_slots: List[EndOfSubSlotBundle],
    signage_point: SignagePoint,
    prev_block: BlockRecord,
    seed: bytes = b"",
    overflow_cc_challenge: bytes32 = None,
    overflow_rc_challenge: bytes32 = None,
) -> Tuple[FullBlock, BlockRecord]:
    sp_iters = calculate_sp_iters(constants, sub_slot_iters, signage_point_index)
    ip_iters = calculate_ip_iters(constants, sub_slot_iters, signage_point_index, required_iters)
    unfinished_block = create_unfinished_block(
        constants,
        sub_slot_start_total_iters,
        sub_slot_iters,
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
        uint64(start_timestamp + int((prev_block.height + 1 - start_height) * time_per_block)),
        BlockCache(blocks),
        seed,
        transaction_data,
        additions,
        removals,
        prev_block,
        finished_sub_slots,
    )

    if (overflow_cc_challenge is not None) and (overflow_rc_challenge is not None):
        slot_cc_challenge = overflow_cc_challenge
        slot_rc_challenge = overflow_rc_challenge

    full_block, block_record = finish_block(
        constants,
        blocks,
        height_to_hash,
        finished_sub_slots,
        sub_slot_start_total_iters,
        signage_point_index,
        unfinished_block,
        required_iters,
        ip_iters,
        slot_cc_challenge,
        slot_rc_challenge,
        prev_block,
        sub_slot_iters,
        difficulty,
    )

    return full_block, block_record
