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
from typing import Callable, Dict, List, Optional, Tuple, Any

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
from chiabip158 import PyBIP158

from chia.cmds.init_funcs import create_all_ssl, create_default_chia_config
from chia.full_node.bundle_tools import (
    best_solution_generator_from_template,
    detect_potential_template_generator,
    simple_solution_generator,
)
from chia.util.errors import Err
from chia.full_node.generator import setup_generator_args
from chia.full_node.mempool_check_conditions import GENERATOR_MOD
from chia.plotting.create_plots import create_plots
from chia.consensus.block_creation import unfinished_block_to_full_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.coinbase import create_puzzlehash_for_pk, create_farmer_coin, create_pool_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.deficit import calculate_deficit
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.consensus.cost_calculator import NPCResult, calculate_cost_of_program
from chia.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_iterations_quality,
    calculate_sp_interval_iters,
    calculate_sp_iters,
    is_overflow_block,
)
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info
from chia.full_node.signage_point import SignagePoint
from chia.plotting.plot_tools import PlotInfo, load_plots, parse_plot_info
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin, hash_coin_list
from chia.types.blockchain_format.foliage import Foliage, FoliageBlockData, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.reward_chain_block import RewardChainBlockUnfinished
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import (
    ChallengeChainSubSlot,
    InfusedChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator, CompressorArg
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.types.name_puzzle_condition import NPC
from chia.util.bech32m import encode_puzzle_hash
from chia.util.block_cache import BlockCache
from chia.util.condition_tools import ConditionOpcode, conditions_by_opcode
from chia.util.config import load_config, save_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64, uint128
from chia.util.keychain import Keychain, bytes_to_mnemonic
from chia.util.merkle_set import MerkleSet
from chia.util.prev_transaction_block import get_prev_transaction_block
from chia.util.path import mkdir
from chia.util.vdf_prover import get_vdf_info_and_proof
from tests.wallet_tools import WalletTool
from chia.wallet.derive_keys import (
    master_sk_to_farmer_sk,
    master_sk_to_local_sk,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk,
)

test_constants = DEFAULT_CONSTANTS.replace(
    **{
        "MIN_PLOT_SIZE": 18,
        "MIN_BLOCKS_PER_CHALLENGE_BLOCK": 12,
        "DIFFICULTY_STARTING": 2 ** 12,
        "DISCRIMINANT_SIZE_BITS": 16,
        "SUB_EPOCH_BLOCKS": 170,
        "WEIGHT_PROOF_THRESHOLD": 2,
        "WEIGHT_PROOF_RECENT_BLOCKS": 380,
        "DIFFICULTY_CONSTANT_FACTOR": 33554432,
        "NUM_SPS_SUB_SLOT": 16,  # Must be a power of 2
        "MAX_SUB_SLOT_BLOCKS": 50,
        "EPOCH_BLOCKS": 340,
        "BLOCKS_CACHE_SIZE": 340 + 3 * 50,  # Coordinate with the above values
        "SUB_SLOT_TIME_TARGET": 600,  # The target number of seconds per slot, mainnet 600
        "SUB_SLOT_ITERS_STARTING": 2 ** 10,  # Must be a multiple of 64
        "NUMBER_ZERO_BITS_PLOT_FILTER": 1,  # H(plot signature of the challenge) must start with these many zeroes
        "MAX_FUTURE_TIME": 3600
        * 24
        * 10,  # Allows creating blockchains with timestamps up to 10 days in the future, for testing
        "COST_PER_BYTE": 1337,
        "MEMPOOL_BLOCK_BUFFER": 6,
        "NETWORK_TYPE": 1,
    }
)


log = logging.getLogger(__name__)


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    def __init__(
        self, constants: ConsensusConstants = test_constants, root_path: Optional[Path] = None, const_dict=None
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

        self.farmer_pubkeys: List[G1Element] = [master_sk_to_farmer_sk(sk).get_g1() for sk in self.all_sks]
        if len(self.pool_pubkeys) == 0 or len(self.farmer_pubkeys) == 0:
            raise RuntimeError("Keys not generated. Run `chia generate keys`")

        self.load_plots()
        self.local_sk_cache: Dict[bytes32, Tuple[PrivateKey, Any]] = {}
        self._config = load_config(self.root_path, "config.yaml")
        self._config["logging"]["log_stdout"] = True
        self._config["selected_network"] = "testnet0"
        for service in ["harvester", "farmer", "full_node", "wallet", "introducer", "timelord", "pool"]:
            self._config[service]["selected_network"] = "testnet0"
        save_config(self.root_path, "config.yaml", self._config)
        overrides = self._config["network_overrides"]["constants"][self._config["selected_network"]]
        updated_constants = constants.replace_str_to_bytes(**overrides)
        if const_dict is not None:
            updated_constants = updated_constants.replace(**const_dict)
        self.constants = updated_constants

    def change_config(self, new_config: Dict):
        self._config = new_config
        overrides = self._config["network_overrides"]["constants"][self._config["selected_network"]]
        updated_constants = self.constants.replace_str_to_bytes(**overrides)
        self.constants = updated_constants
        save_config(self.root_path, "config.yaml", self._config)

    def load_plots(self):
        _, loaded_plots, _, _ = load_plots({}, {}, self.farmer_pubkeys, self.pool_pubkeys, None, False, self.root_path)
        self.plots: Dict[Path, PlotInfo] = loaded_plots

    def init_plots(self, root_path: Path):
        plot_dir = get_plot_dir()
        mkdir(plot_dir)
        temp_dir = get_plot_tmp_dir()
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
            args.pool_contract_address = encode_puzzle_hash(self.pool_ph, "xch")
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
            if plot_pk == plot_info.plot_public_key:
                # Look up local_sk from plot to save locked memory
                if plot_info.prover.get_id() in self.local_sk_cache:
                    local_master_sk, pool_pk_or_ph = self.local_sk_cache[plot_info.prover.get_id()]
                else:
                    pool_pk_or_ph, _, local_master_sk = parse_plot_info(plot_info.prover.get_memo())
                    self.local_sk_cache[plot_info.prover.get_id()] = (local_master_sk, pool_pk_or_ph)
                if isinstance(pool_pk_or_ph, G1Element):
                    include_taproot = False
                else:
                    assert isinstance(pool_pk_or_ph, bytes32)
                    include_taproot = True
                local_sk = master_sk_to_local_sk(local_master_sk)
                agg_pk = ProofOfSpace.generate_plot_public_key(local_sk.get_g1(), farmer_sk.get_g1(), include_taproot)
                assert agg_pk == plot_pk
                harv_share = AugSchemeMPL.sign(local_sk, m, agg_pk)
                farm_share = AugSchemeMPL.sign(farmer_sk, m, agg_pk)
                if include_taproot:
                    taproot_sk: PrivateKey = ProofOfSpace.generate_taproot_sk(local_sk.get_g1(), farmer_sk.get_g1())
                    taproot_share: G2Element = AugSchemeMPL.sign(taproot_sk, m, agg_pk)
                else:
                    taproot_share = G2Element()
                return AugSchemeMPL.aggregate([harv_share, farm_share, taproot_share])

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
        return WalletTool(self.constants, self.farmer_master_sk)

    def get_pool_wallet_tool(self) -> WalletTool:
        return WalletTool(self.constants, self.pool_master_sk)

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
        normalized_to_identity_cc_eos: bool = False,
        normalized_to_identity_icc_eos: bool = False,
        normalized_to_identity_cc_sp: bool = False,
        normalized_to_identity_cc_ip: bool = False,
        current_time: bool = False,
        previous_generator: CompressorArg = None,
        genesis_timestamp: Optional[uint64] = None,
        force_plot_id: Optional[bytes32] = None,
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
            if force_plot_id is not None:
                raise ValueError("Cannot specify plot_id for genesis block")
            initial_block_list_len = 0
            genesis = self.create_genesis_block(
                constants,
                seed,
                force_overflow=force_overflow,
                skip_slots=skip_slots,
                timestamp=(uint64(int(time.time())) if genesis_timestamp is None else genesis_timestamp),
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
                        normalized_to_identity_cc_sp,
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
                        force_plot_id=force_plot_id,
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

                        if transaction_data is not None:
                            if previous_generator is not None:
                                block_generator: Optional[BlockGenerator] = best_solution_generator_from_template(
                                    previous_generator, transaction_data
                                )
                            else:
                                block_generator = simple_solution_generator(transaction_data)

                            aggregate_signature = transaction_data.aggregated_signature
                        else:
                            block_generator = None
                            aggregate_signature = G2Element()

                        full_block, block_record = get_full_block_and_block_record(
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
                            block_generator,
                            aggregate_signature,
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
                            normalized_to_identity_cc_ip,
                            current_time=current_time,
                        )
                        if block_record.is_transaction_block:
                            transaction_data_included = True
                        else:
                            if guarantee_transaction_block:
                                continue
                        if pending_ses:
                            pending_ses = False
                        block_list.append(full_block)
                        if full_block.transactions_generator is not None:
                            compressor_arg = detect_potential_template_generator(
                                full_block.height, full_block.transactions_generator
                            )
                            if compressor_arg is not None:
                                previous_generator = compressor_arg

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
            icc_eos_vdf, icc_ip_proof = get_icc(
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
            if normalized_to_identity_cc_eos:
                _, cc_proof = get_vdf_info_and_proof(
                    constants,
                    ClassgroupElement.get_default_element(),
                    cc_vdf.challenge,
                    sub_slot_iters,
                    True,
                )
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

            if icc_eos_vdf is not None:
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
                icc_eos_vdf = VDFInfo(
                    icc_eos_vdf.challenge,
                    icc_eos_iters,
                    icc_eos_vdf.output,
                )
                if normalized_to_identity_icc_eos:
                    _, icc_ip_proof = get_vdf_info_and_proof(
                        constants,
                        ClassgroupElement.get_default_element(),
                        icc_eos_vdf.challenge,
                        icc_eos_iters,
                        True,
                    )
                icc_sub_slot: Optional[InfusedChallengeChainSubSlot] = InfusedChallengeChainSubSlot(icc_eos_vdf)
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
                        normalized_to_identity_cc_sp,
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
                        force_plot_id=force_plot_id,
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
                        if transaction_data is not None:
                            if previous_generator is not None:
                                block_generator = best_solution_generator_from_template(
                                    previous_generator, transaction_data
                                )
                            else:
                                block_generator = simple_solution_generator(transaction_data)
                            aggregate_signature = transaction_data.aggregated_signature
                        else:
                            block_generator = None
                            aggregate_signature = G2Element()
                        full_block, block_record = get_full_block_and_block_record(
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
                            block_generator,
                            aggregate_signature,
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
                            normalized_to_identity_cc_ip=normalized_to_identity_cc_ip,
                            current_time=current_time,
                        )

                        if block_record.is_transaction_block:
                            transaction_data_included = True
                        elif guarantee_transaction_block:
                            continue
                        if pending_ses:
                            pending_ses = False

                        block_list.append(full_block)
                        if full_block.transactions_generator is not None:
                            compressor_arg = detect_potential_template_generator(
                                full_block.height, full_block.transactions_generator
                            )
                            if compressor_arg is not None:
                                previous_generator = compressor_arg

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

                    unfinished_block = create_test_unfinished_block(
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
        force_plot_id: Optional[bytes32] = None,
    ) -> List[Tuple[uint64, ProofOfSpace]]:
        found_proofs: List[Tuple[uint64, ProofOfSpace]] = []
        plots: List[PlotInfo] = [
            plot_info for _, plot_info in sorted(list(self.plots.items()), key=lambda x: str(x[0]))
        ]
        random.seed(seed)
        for plot_info in plots:
            plot_id: bytes32 = plot_info.prover.get_id()
            if force_plot_id is not None and plot_id != force_plot_id:
                continue
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

                        # Look up local_sk from plot to save locked memory
                        (
                            pool_public_key_or_puzzle_hash,
                            farmer_public_key,
                            local_master_sk,
                        ) = parse_plot_info(plot_info.prover.get_memo())
                        local_sk = master_sk_to_local_sk(local_master_sk)

                        if isinstance(pool_public_key_or_puzzle_hash, G1Element):
                            include_taproot = False
                        else:
                            assert isinstance(pool_public_key_or_puzzle_hash, bytes32)
                            include_taproot = True
                        plot_pk = ProofOfSpace.generate_plot_public_key(
                            local_sk.get_g1(), farmer_public_key, include_taproot
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
    normalized_to_identity_cc_sp: bool = False,
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
    if normalized_to_identity_cc_sp:
        _, cc_sp_proof = get_vdf_info_and_proof(
            constants,
            ClassgroupElement.get_default_element(),
            cc_sp_vdf.challenge,
            sp_iters,
            True,
        )
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
    normalized_to_identity_cc_ip: bool = False,
) -> Tuple[FullBlock, BlockRecord]:
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
    if normalized_to_identity_cc_ip:
        _, cc_ip_proof = get_vdf_info_and_proof(
            constants,
            ClassgroupElement.get_default_element(),
            cc_ip_vdf.challenge,
            ip_iters,
            True,
        )
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
) -> Tuple[bytes32, bytes32]:
    if len(finished_sub_slots) == 0:
        if prev_header_hash is None:
            return constants.GENESIS_CHALLENGE, constants.GENESIS_CHALLENGE
        curr: BlockRecord = blocks[prev_header_hash]
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


def get_plot_dir() -> Path:
    cache_path = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/"))) / "test-plots"
    mkdir(cache_path)
    return cache_path


def get_plot_tmp_dir():
    return get_plot_dir() / "tmp"


def load_block_list(
    block_list: List[FullBlock], constants: ConsensusConstants
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
    constants: ConsensusConstants,
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
        icc_input: Optional[ClassgroupElement] = ClassgroupElement.get_default_element()
    else:
        icc_input = latest_block.infused_challenge_vdf_output
    assert icc_input is not None

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


def get_full_block_and_block_record(
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
    block_generator: Optional[BlockGenerator],
    aggregate_signature: G2Element,
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
    normalized_to_identity_cc_ip: bool = False,
    current_time: bool = False,
) -> Tuple[FullBlock, BlockRecord]:
    if current_time is True:
        if prev_block.timestamp is not None:
            timestamp = uint64(max(int(time.time()), prev_block.timestamp + int(time_per_block)))
        else:
            timestamp = uint64(int(time.time()))
    else:
        timestamp = uint64(start_timestamp + int((prev_block.height + 1 - start_height) * time_per_block))
    sp_iters = calculate_sp_iters(constants, sub_slot_iters, signage_point_index)
    ip_iters = calculate_ip_iters(constants, sub_slot_iters, signage_point_index, required_iters)

    unfinished_block = create_test_unfinished_block(
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
        timestamp,
        BlockCache(blocks),
        seed,
        block_generator,
        aggregate_signature,
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
        normalized_to_identity_cc_ip,
    )

    return full_block, block_record


def get_name_puzzle_conditions_test(generator: BlockGenerator, max_cost: int) -> NPCResult:
    """
    This is similar to get_name_puzzle_conditions(), but it doesn't validate
    the conditions. We rely on this in tests to create invalid blocks.
    safe_mode is implicitly True in this call
    """
    try:
        block_program, block_program_args = setup_generator_args(generator)
        clvm_cost, result = GENERATOR_MOD.run_safe_with_cost(max_cost, block_program, block_program_args)

        npc_list: List[NPC] = []

        for res in result.first().as_iter():
            conditions_list: List[ConditionWithArgs] = []

            spent_coin_parent_id: bytes32 = res.first().as_atom()
            res = res.rest()
            spent_coin_puzzle_hash: bytes32 = res.first().as_atom()
            res = res.rest()
            spent_coin_amount: uint64 = uint64(res.first().as_int())
            res = res.rest()
            spent_coin: Coin = Coin(spent_coin_parent_id, spent_coin_puzzle_hash, spent_coin_amount)

            for cond in res.first().as_iter():
                condition = cond.first().as_atom()
                cvl = ConditionWithArgs(ConditionOpcode(condition), cond.rest().as_atom_list())
                conditions_list.append(cvl)

            conditions_dict = conditions_by_opcode(conditions_list)
            if conditions_dict is None:
                conditions_dict = {}
            npc_list.append(
                NPC(spent_coin.name(), spent_coin.puzzle_hash, [(a, b) for a, b in conditions_dict.items()])
            )
        return NPCResult(None, npc_list, uint64(clvm_cost))
    except Exception:
        return NPCResult(uint16(Err.GENERATOR_RUNTIME_ERROR.value), [], uint64(0))


def create_test_foliage(
    constants: ConsensusConstants,
    reward_block_unfinished: RewardChainBlockUnfinished,
    block_generator: Optional[BlockGenerator],
    aggregate_sig: G2Element,
    additions: List[Coin],
    removals: List[Coin],
    prev_block: Optional[BlockRecord],
    blocks: BlockchainInterface,
    total_iters_sp: uint128,
    timestamp: uint64,
    farmer_reward_puzzlehash: bytes32,
    pool_target: PoolTarget,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, Optional[G1Element]], Optional[G2Element]],
    seed: bytes32 = b"",
) -> Tuple[Foliage, Optional[FoliageTransactionBlock], Optional[TransactionsInfo]]:
    """
    Creates a foliage for a given reward chain block. This may or may not be a tx block. In the case of a tx block,
    the return values are not None. This is called at the signage point, so some of this information may be
    tweaked at the infusion point.

    Args:
        constants: consensus constants being used for this chain
        reward_block_unfinished: the reward block to look at, potentially at the signage point
        block_generator: transactions to add to the foliage block, if created
        aggregate_sig: aggregate of all transctions (or infinity element)
        prev_block: the previous block at the signage point
        blocks: dict from header hash to blocks, of all ancestor blocks
        total_iters_sp: total iters at the signage point
        timestamp: timestamp to put into the foliage block
        farmer_reward_puzzlehash: where to pay out farming reward
        pool_target: where to pay out pool reward
        get_plot_signature: retrieve the signature corresponding to the plot public key
        get_pool_signature: retrieve the signature corresponding to the pool public key
        seed: seed to randomize block

    """

    if prev_block is not None:
        res = get_prev_transaction_block(prev_block, blocks, total_iters_sp)
        is_transaction_block: bool = res[0]
        prev_transaction_block: Optional[BlockRecord] = res[1]
    else:
        # Genesis is a transaction block
        prev_transaction_block = None
        is_transaction_block = True

    random.seed(seed)
    # Use the extension data to create different blocks based on header hash
    extension_data: bytes32 = random.randint(0, 100000000).to_bytes(32, "big")
    if prev_block is None:
        height: uint32 = uint32(0)
    else:
        height = uint32(prev_block.height + 1)

    # Create filter
    byte_array_tx: List[bytes32] = []
    tx_additions: List[Coin] = []
    tx_removals: List[bytes32] = []

    pool_target_signature: Optional[G2Element] = get_pool_signature(
        pool_target, reward_block_unfinished.proof_of_space.pool_public_key
    )

    foliage_data = FoliageBlockData(
        reward_block_unfinished.get_hash(),
        pool_target,
        pool_target_signature,
        farmer_reward_puzzlehash,
        extension_data,
    )

    foliage_block_data_signature: G2Element = get_plot_signature(
        foliage_data.get_hash(),
        reward_block_unfinished.proof_of_space.plot_public_key,
    )

    prev_block_hash: bytes32 = constants.GENESIS_CHALLENGE
    if height != 0:
        assert prev_block is not None
        prev_block_hash = prev_block.header_hash

    generator_block_heights_list: List[uint32] = []

    if is_transaction_block:
        cost = uint64(0)

        # Calculate the cost of transactions
        if block_generator is not None:
            generator_block_heights_list = block_generator.block_height_list()
            result: NPCResult = get_name_puzzle_conditions_test(block_generator, constants.MAX_BLOCK_COST_CLVM)
            cost = calculate_cost_of_program(block_generator.program, result, constants.COST_PER_BYTE)

            removal_amount = 0
            addition_amount = 0
            for coin in removals:
                removal_amount += coin.amount
            for coin in additions:
                addition_amount += coin.amount
            spend_bundle_fees = removal_amount - addition_amount
            # in order to allow creating blocks that mint coins, clamp the fee
            # to 0, if it ends up being negative
            if spend_bundle_fees < 0:
                spend_bundle_fees = 0
        else:
            spend_bundle_fees = 0

        reward_claims_incorporated = []
        if height > 0:
            assert prev_transaction_block is not None
            assert prev_block is not None
            curr: BlockRecord = prev_block
            while not curr.is_transaction_block:
                curr = blocks.block_record(curr.prev_hash)

            assert curr.fees is not None
            pool_coin = create_pool_coin(
                curr.height, curr.pool_puzzle_hash, calculate_pool_reward(curr.height), constants.GENESIS_CHALLENGE
            )

            farmer_coin = create_farmer_coin(
                curr.height,
                curr.farmer_puzzle_hash,
                uint64(calculate_base_farmer_reward(curr.height) + curr.fees),
                constants.GENESIS_CHALLENGE,
            )
            assert curr.header_hash == prev_transaction_block.header_hash
            reward_claims_incorporated += [pool_coin, farmer_coin]

            if curr.height > 0:
                curr = blocks.block_record(curr.prev_hash)
                # Prev block is not genesis
                while not curr.is_transaction_block:
                    pool_coin = create_pool_coin(
                        curr.height,
                        curr.pool_puzzle_hash,
                        calculate_pool_reward(curr.height),
                        constants.GENESIS_CHALLENGE,
                    )
                    farmer_coin = create_farmer_coin(
                        curr.height,
                        curr.farmer_puzzle_hash,
                        calculate_base_farmer_reward(curr.height),
                        constants.GENESIS_CHALLENGE,
                    )
                    reward_claims_incorporated += [pool_coin, farmer_coin]
                    curr = blocks.block_record(curr.prev_hash)
        additions.extend(reward_claims_incorporated.copy())
        for coin in additions:
            tx_additions.append(coin)
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for coin in removals:
            tx_removals.append(coin.name())
            byte_array_tx.append(bytearray(coin.name()))

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

        generator_hash = bytes32([0] * 32)
        if block_generator is not None:
            generator_hash = std_hash(block_generator.program)

        generator_refs_hash = bytes32([1] * 32)
        if generator_block_heights_list not in (None, []):
            generator_ref_list_bytes = b"".join([bytes(i) for i in generator_block_heights_list])
            generator_refs_hash = std_hash(generator_ref_list_bytes)

        filter_hash: bytes32 = std_hash(encoded)

        transactions_info: Optional[TransactionsInfo] = TransactionsInfo(
            generator_hash,
            generator_refs_hash,
            aggregate_sig,
            uint64(spend_bundle_fees),
            cost,
            reward_claims_incorporated,
        )
        if prev_transaction_block is None:
            prev_transaction_block_hash: bytes32 = constants.GENESIS_CHALLENGE
        else:
            prev_transaction_block_hash = prev_transaction_block.header_hash

        assert transactions_info is not None
        foliage_transaction_block: Optional[FoliageTransactionBlock] = FoliageTransactionBlock(
            prev_transaction_block_hash,
            timestamp,
            filter_hash,
            additions_root,
            removals_root,
            transactions_info.get_hash(),
        )
        assert foliage_transaction_block is not None

        foliage_transaction_block_hash: Optional[bytes32] = foliage_transaction_block.get_hash()
        foliage_transaction_block_signature: Optional[G2Element] = get_plot_signature(
            foliage_transaction_block_hash, reward_block_unfinished.proof_of_space.plot_public_key
        )
        assert foliage_transaction_block_signature is not None
    else:
        foliage_transaction_block_hash = None
        foliage_transaction_block_signature = None
        foliage_transaction_block = None
        transactions_info = None
    assert (foliage_transaction_block_hash is None) == (foliage_transaction_block_signature is None)

    foliage = Foliage(
        prev_block_hash,
        reward_block_unfinished.get_hash(),
        foliage_data,
        foliage_block_data_signature,
        foliage_transaction_block_hash,
        foliage_transaction_block_signature,
    )

    return foliage, foliage_transaction_block, transactions_info


def create_test_unfinished_block(
    constants: ConsensusConstants,
    sub_slot_start_total_iters: uint128,
    sub_slot_iters: uint64,
    signage_point_index: uint8,
    sp_iters: uint64,
    ip_iters: uint64,
    proof_of_space: ProofOfSpace,
    slot_cc_challenge: bytes32,
    farmer_reward_puzzle_hash: bytes32,
    pool_target: PoolTarget,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, Optional[G1Element]], Optional[G2Element]],
    signage_point: SignagePoint,
    timestamp: uint64,
    blocks: BlockchainInterface,
    seed: bytes32 = b"",
    block_generator: Optional[BlockGenerator] = None,
    aggregate_sig: G2Element = G2Element(),
    additions: Optional[List[Coin]] = None,
    removals: Optional[List[Coin]] = None,
    prev_block: Optional[BlockRecord] = None,
    finished_sub_slots_input: List[EndOfSubSlotBundle] = None,
) -> UnfinishedBlock:
    """
    Creates a new unfinished block using all the information available at the signage point. This will have to be
    modified using information from the infusion point.

    Args:
        constants: consensus constants being used for this chain
        sub_slot_start_total_iters: the starting sub-slot iters at the signage point sub-slot
        sub_slot_iters: sub-slot-iters at the infusion point epoch
        signage_point_index: signage point index of the block to create
        sp_iters: sp_iters of the block to create
        ip_iters: ip_iters of the block to create
        proof_of_space: proof of space of the block to create
        slot_cc_challenge: challenge hash at the sp sub-slot
        farmer_reward_puzzle_hash: where to pay out farmer rewards
        pool_target: where to pay out pool rewards
        get_plot_signature: function that returns signature corresponding to plot public key
        get_pool_signature: function that returns signature corresponding to pool public key
        signage_point: signage point information (VDFs)
        timestamp: timestamp to add to the foliage block, if created
        seed: seed to randomize chain
        block_generator: transactions to add to the foliage block, if created
        aggregate_sig: aggregate of all transctions (or infinity element)
        additions: Coins added in spend_bundle
        removals: Coins removed in spend_bundle
        prev_block: previous block (already in chain) from the signage point
        blocks: dictionary from header hash to SBR of all included SBR
        finished_sub_slots_input: finished_sub_slots at the signage point

    Returns:

    """
    if finished_sub_slots_input is None:
        finished_sub_slots: List[EndOfSubSlotBundle] = []
    else:
        finished_sub_slots = finished_sub_slots_input.copy()
    overflow: bool = sp_iters > ip_iters
    total_iters_sp: uint128 = uint128(sub_slot_start_total_iters + sp_iters)
    is_genesis: bool = prev_block is None

    new_sub_slot: bool = len(finished_sub_slots) > 0

    cc_sp_hash: Optional[bytes32] = slot_cc_challenge

    # Only enters this if statement if we are in testing mode (making VDF proofs here)
    if signage_point.cc_vdf is not None:
        assert signage_point.rc_vdf is not None
        cc_sp_hash = signage_point.cc_vdf.output.get_hash()
        rc_sp_hash = signage_point.rc_vdf.output.get_hash()
    else:
        if new_sub_slot:
            rc_sp_hash = finished_sub_slots[-1].reward_chain.get_hash()
        else:
            if is_genesis:
                rc_sp_hash = constants.GENESIS_CHALLENGE
            else:
                assert prev_block is not None
                assert blocks is not None
                curr = prev_block
                while not curr.first_in_sub_slot:
                    curr = blocks.block_record(curr.prev_hash)
                assert curr.finished_reward_slot_hashes is not None
                rc_sp_hash = curr.finished_reward_slot_hashes[-1]
        signage_point = SignagePoint(None, None, None, None)

    cc_sp_signature: Optional[G2Element] = get_plot_signature(cc_sp_hash, proof_of_space.plot_public_key)
    rc_sp_signature: Optional[G2Element] = get_plot_signature(rc_sp_hash, proof_of_space.plot_public_key)
    assert cc_sp_signature is not None
    assert rc_sp_signature is not None
    assert AugSchemeMPL.verify(proof_of_space.plot_public_key, cc_sp_hash, cc_sp_signature)

    total_iters = uint128(sub_slot_start_total_iters + ip_iters + (sub_slot_iters if overflow else 0))

    rc_block = RewardChainBlockUnfinished(
        total_iters,
        signage_point_index,
        slot_cc_challenge,
        proof_of_space,
        signage_point.cc_vdf,
        cc_sp_signature,
        signage_point.rc_vdf,
        rc_sp_signature,
    )
    if additions is None:
        additions = []
    if removals is None:
        removals = []
    (foliage, foliage_transaction_block, transactions_info,) = create_test_foliage(
        constants,
        rc_block,
        block_generator,
        aggregate_sig,
        additions,
        removals,
        prev_block,
        blocks,
        total_iters_sp,
        timestamp,
        farmer_reward_puzzle_hash,
        pool_target,
        get_plot_signature,
        get_pool_signature,
        seed,
    )
    return UnfinishedBlock(
        finished_sub_slots,
        rc_block,
        signage_point.cc_proof,
        signage_point.rc_proof,
        foliage,
        foliage_transaction_block,
        transactions_info,
        block_generator.program if block_generator else None,
        block_generator.block_height_list() if block_generator else [],
    )
