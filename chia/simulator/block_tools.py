from __future__ import annotations

import asyncio
import copy
import dataclasses
import logging
import os
import random
import shutil
import ssl
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from random import Random
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import anyio
from chia_rs import ALLOW_BACKREFS, MEMPOOL_MODE, AugSchemeMPL, G1Element, G2Element, PrivateKey, solution_generator

from chia.consensus.block_creation import create_unfinished_block, unfinished_block_to_full_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.consensus.condition_costs import ConditionCost
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.deficit import calculate_deficit
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_iterations_quality,
    calculate_sp_interval_iters,
    calculate_sp_iters,
    is_overflow_block,
)
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info
from chia.daemon.keychain_proxy import KeychainProxy, connect_to_keychain_and_validate, wrap_local_keychain
from chia.full_node.bundle_tools import (
    best_solution_generator_from_template,
    detect_potential_template_generator,
    simple_solution_generator,
    simple_solution_generator_backrefs,
)
from chia.full_node.signage_point import SignagePoint
from chia.plotting.create_plots import PlotKeys, create_plots
from chia.plotting.manager import PlotManager
from chia.plotting.util import (
    Params,
    PlotRefreshEvents,
    PlotRefreshResult,
    PlotsRefreshParameter,
    add_plot_directory,
    parse_plot_info,
)
from chia.server.server import ssl_context_for_client
from chia.simulator.socket import find_available_listen_port
from chia.simulator.ssl_certs import (
    SSLTestCACertAndPrivateKey,
    SSLTestCollateralWrapper,
    SSLTestNodeCertsAndKeys,
    get_next_nodes_certs_and_keys,
    get_next_private_ca_cert_and_key,
)
from chia.simulator.wallet_tools import WalletTool
from chia.ssl.create_ssl import create_all_ssl
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.proof_of_space import (
    ProofOfSpace,
    calculate_pos_challenge,
    calculate_prefix_bits,
    generate_plot_public_key,
    generate_taproot_sk,
    passes_plot_filter,
    verify_and_get_quality_string,
)
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import (
    ChallengeChainSubSlot,
    InfusedChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator, CompressorArg
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.bech32m import encode_puzzle_hash
from chia.util.block_cache import BlockCache
from chia.util.config import (
    config_path_for_filename,
    create_default_chia_config,
    load_config,
    lock_config,
    override_config,
    save_config,
)
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.keychain import Keychain, bytes_to_mnemonic
from chia.util.ssl_check import fix_ssl
from chia.util.timing import adjusted_timeout, backoff_times
from chia.util.vdf_prover import get_vdf_info_and_proof
from chia.wallet.derive_keys import (
    master_sk_to_farmer_sk,
    master_sk_to_local_sk,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk,
)
from chia.wallet.puzzles.load_clvm import load_serialized_clvm_maybe_recompile

GENERATOR_MOD: SerializedProgram = load_serialized_clvm_maybe_recompile(
    "rom_bootstrap_generator.clsp", package_or_requirement="chia.consensus.puzzles"
)

DESERIALIZE_MOD = load_serialized_clvm_maybe_recompile(
    "chialisp_deserialisation.clsp", package_or_requirement="chia.consensus.puzzles"
)

test_constants = dataclasses.replace(
    DEFAULT_CONSTANTS,
    MIN_PLOT_SIZE=18,
    MIN_BLOCKS_PER_CHALLENGE_BLOCK=uint8(12),
    DIFFICULTY_STARTING=uint64(2**10),
    DISCRIMINANT_SIZE_BITS=16,
    SUB_EPOCH_BLOCKS=uint32(170),
    WEIGHT_PROOF_THRESHOLD=uint8(2),
    WEIGHT_PROOF_RECENT_BLOCKS=uint32(380),
    DIFFICULTY_CONSTANT_FACTOR=uint128(33554432),
    NUM_SPS_SUB_SLOT=uint32(16),  # Must be a power of 2
    MAX_SUB_SLOT_BLOCKS=uint32(50),
    EPOCH_BLOCKS=uint32(340),
    # the block cache must contain at least 3 epochs in order for
    # create_prev_sub_epoch_segments() to have access to all the blocks it needs
    # from the cache
    BLOCKS_CACHE_SIZE=uint32(340 * 3),  # Coordinate with the above values
    SUB_SLOT_TIME_TARGET=600,  # The target number of seconds per slot, mainnet 600
    SUB_SLOT_ITERS_STARTING=uint64(2**10),  # Must be a multiple of 64
    NUMBER_ZERO_BITS_PLOT_FILTER=1,  # H(plot signature of the challenge) must start with these many zeroes
    # Allows creating blockchains with timestamps up to 10 days in the future, for testing
    MAX_FUTURE_TIME2=3600 * 24 * 10,
    MEMPOOL_BLOCK_BUFFER=6,
    # we deliberately make this different from HARD_FORK_HEIGHT in the
    # tests, to ensure they operate independently (which they need to do for
    # testnet10)
    HARD_FORK_FIX_HEIGHT=uint32(5496100),
)


def compute_additions_unchecked(sb: SpendBundle) -> List[Coin]:
    ret: List[Coin] = []
    for cs in sb.coin_spends:
        parent_id = cs.coin.name()
        _, r = cs.puzzle_reveal.run_with_cost(INFINITE_COST, cs.solution)
        for cond in Program.to(r).as_iter():
            atoms = cond.as_iter()
            op = next(atoms).atom
            if op != ConditionOpcode.CREATE_COIN.value:
                continue
            puzzle_hash = next(atoms).as_atom()
            amount = next(atoms).as_int()
            ret.append(Coin(parent_id, puzzle_hash, amount))
    return ret


def make_spend_bundle(coins: List[Coin], wallet: WalletTool, rng: Random) -> Tuple[SpendBundle, List[Coin]]:
    """
    makes a new spend bundle (block generator) spending some of the coins in the
    list of coins. The list will be updated to have spent coins removed and new
    coins appended.
    """
    new_coins: List[Coin] = []
    spend_bundles: List[SpendBundle] = []
    to_spend = rng.sample(coins, min(5, len(coins)))
    receiver = wallet.get_new_puzzlehash()
    for c in to_spend:
        bundle = wallet.generate_signed_transaction(uint64(c.amount // 2), receiver, c)
        new_coins.extend(bundle.additions())
        spend_bundles.append(bundle)
        coins.remove(c)

    coins.extend(new_coins)

    return SpendBundle.aggregate(spend_bundles), new_coins


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    _block_cache_header: bytes32
    _block_cache_height_to_hash: Dict[uint32, bytes32]
    _block_cache_difficulty: uint64
    _block_cache: Dict[bytes32, BlockRecord]

    def __init__(
        self,
        constants: ConsensusConstants = test_constants,
        root_path: Optional[Path] = None,
        keychain: Optional[Keychain] = None,
        config_overrides: Optional[Dict[str, Any]] = None,
        automated_testing: bool = True,
        plot_dir: str = "test-plots",
        log: logging.Logger = logging.getLogger(__name__),
    ) -> None:
        self._block_cache_header = bytes32([0] * 32)

        self._tempdir = None
        if root_path is None:
            self._tempdir = tempfile.TemporaryDirectory()
            root_path = Path(self._tempdir.name)

        self.root_path = root_path
        self.log = log
        self.local_keychain = keychain
        self.local_sk_cache: Dict[bytes32, Tuple[PrivateKey, Any]] = {}
        self.automated_testing = automated_testing
        self.plot_dir_name = plot_dir

        if automated_testing:
            # Hold onto the wrappers so that they can keep track of whether the certs/keys
            # are in use by another BlockTools instance.
            self.ssl_ca_cert_and_key_wrapper: SSLTestCollateralWrapper[
                SSLTestCACertAndPrivateKey
            ] = get_next_private_ca_cert_and_key()
            self.ssl_nodes_certs_and_keys_wrapper: SSLTestCollateralWrapper[
                SSLTestNodeCertsAndKeys
            ] = get_next_nodes_certs_and_keys()
            create_default_chia_config(root_path)
            create_all_ssl(
                root_path,
                private_ca_crt_and_key=self.ssl_ca_cert_and_key_wrapper.collateral.cert_and_key,
                node_certs_and_keys=self.ssl_nodes_certs_and_keys_wrapper.collateral.certs_and_keys,
            )
            fix_ssl(root_path)
            with lock_config(root_path=root_path, filename="config.yaml"):
                path = config_path_for_filename(root_path=root_path, filename="config.yaml")
                path.write_text(path.read_text().replace("localhost", "127.0.0.1"))
        self._config = load_config(self.root_path, "config.yaml")
        if automated_testing:
            if config_overrides is None:
                config_overrides = {}
            config_overrides["logging.log_stdout"] = True
            config_overrides["selected_network"] = "testnet0"
            for service in [
                "harvester",
                "farmer",
                "full_node",
                "wallet",
                "introducer",
                "timelord",
                "pool",
                "simulator",
            ]:
                config_overrides[service + ".selected_network"] = "testnet0"

            # some tests start the daemon, make sure it's on a free port
            config_overrides["daemon_port"] = find_available_listen_port("BlockTools daemon")

        self._config = override_config(self._config, config_overrides)

        with lock_config(self.root_path, "config.yaml"):
            save_config(self.root_path, "config.yaml", self._config)
        overrides = self._config["network_overrides"]["constants"][self._config["selected_network"]]
        updated_constants = constants.replace_str_to_bytes(**overrides)
        self.constants = updated_constants

        self.plot_dir: Path = get_plot_dir(self.plot_dir_name, self.automated_testing)
        self.temp_dir: Path = get_plot_tmp_dir(self.plot_dir_name, self.automated_testing)
        self.plot_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.expected_plots: Dict[bytes32, Path] = {}
        self.created_plots: int = 0
        self.total_result = PlotRefreshResult()

        def test_callback(event: PlotRefreshEvents, update_result: PlotRefreshResult) -> None:
            assert update_result.duration < 120
            if event == PlotRefreshEvents.started:
                self.total_result = PlotRefreshResult()

            if event == PlotRefreshEvents.batch_processed:
                self.total_result.loaded += update_result.loaded
                self.total_result.processed += update_result.processed
                self.total_result.duration += update_result.duration
                assert update_result.remaining >= len(self.expected_plots) - self.total_result.processed
                assert len(update_result.loaded) <= self.plot_manager.refresh_parameter.batch_size

            if event == PlotRefreshEvents.done:
                assert self.total_result.loaded == update_result.loaded
                assert self.total_result.processed == update_result.processed
                assert self.total_result.duration == update_result.duration
                assert update_result.remaining == 0
                assert len(self.plot_manager.plots) == len(self.expected_plots)

        self.plot_manager: PlotManager = PlotManager(
            self.root_path,
            refresh_parameter=PlotsRefreshParameter(batch_size=uint32(2)),
            refresh_callback=test_callback,
            match_str=str(self.plot_dir.relative_to(DEFAULT_ROOT_PATH.parent)) if not automated_testing else None,
        )

    async def setup_keys(self, fingerprint: Optional[int] = None, reward_ph: Optional[bytes32] = None) -> None:
        keychain_proxy: Optional[KeychainProxy]
        try:
            if self.local_keychain:
                keychain_proxy = wrap_local_keychain(self.local_keychain, log=self.log)
            elif not self.automated_testing and fingerprint is not None:
                keychain_proxy = await connect_to_keychain_and_validate(self.root_path, self.log)
            else:  # if we are automated testing or if we don't have a fingerprint.
                keychain_proxy = await connect_to_keychain_and_validate(
                    self.root_path, self.log, user="testing-1.8.0", service="chia-testing-1.8.0"
                )
            assert keychain_proxy is not None
            if fingerprint is None:  # if we are not specifying an existing key
                await keychain_proxy.delete_all_keys()
                self.farmer_master_sk_entropy = std_hash(b"block_tools farmer key")  # both entropies are only used here
                self.pool_master_sk_entropy = std_hash(b"block_tools pool key")
                self.farmer_master_sk = await keychain_proxy.add_private_key(
                    bytes_to_mnemonic(self.farmer_master_sk_entropy)
                )
                self.pool_master_sk = await keychain_proxy.add_private_key(
                    bytes_to_mnemonic(self.pool_master_sk_entropy),
                )
            else:
                sk = await keychain_proxy.get_key_for_fingerprint(fingerprint)
                assert sk is not None
                self.farmer_master_sk = sk
                sk = await keychain_proxy.get_key_for_fingerprint(fingerprint)
                assert sk is not None
                self.pool_master_sk = sk

            self.farmer_pk = master_sk_to_farmer_sk(self.farmer_master_sk).get_g1()
            self.pool_pk = master_sk_to_pool_sk(self.pool_master_sk).get_g1()

            if reward_ph is None:
                self.farmer_ph: bytes32 = create_puzzlehash_for_pk(
                    master_sk_to_wallet_sk(self.farmer_master_sk, uint32(0)).get_g1()
                )
                self.pool_ph: bytes32 = create_puzzlehash_for_pk(
                    master_sk_to_wallet_sk(self.pool_master_sk, uint32(0)).get_g1()
                )
            else:
                self.farmer_ph = reward_ph
                self.pool_ph = reward_ph
            if self.automated_testing:
                self.all_sks: List[PrivateKey] = [sk for sk, _ in await keychain_proxy.get_all_private_keys()]
            else:
                self.all_sks = [self.farmer_master_sk]  # we only want to include plots under the same fingerprint
            self.pool_pubkeys: List[G1Element] = [master_sk_to_pool_sk(sk).get_g1() for sk in self.all_sks]

            self.farmer_pubkeys: List[G1Element] = [master_sk_to_farmer_sk(sk).get_g1() for sk in self.all_sks]
            if len(self.pool_pubkeys) == 0 or len(self.farmer_pubkeys) == 0:
                raise RuntimeError("Keys not generated. Run `chia keys generate`")

            self.plot_manager.set_public_keys(self.farmer_pubkeys, self.pool_pubkeys)
        finally:
            if keychain_proxy is not None:
                await keychain_proxy.close()  # close the keychain proxy

    def change_config(self, new_config: Dict[str, Any]) -> None:
        self._config = new_config
        overrides = self._config["network_overrides"]["constants"][self._config["selected_network"]]
        updated_constants = self.constants.replace_str_to_bytes(**overrides)
        self.constants = updated_constants
        with lock_config(self.root_path, "config.yaml"):
            save_config(self.root_path, "config.yaml", self._config)

    def add_plot_directory(self, path: Path) -> None:
        # don't add to config if block_tools is user run and the directory is already in the config.
        if str(path.resolve()) not in self._config["harvester"]["plot_directories"] or self.automated_testing:
            self._config = add_plot_directory(self.root_path, str(path))

    async def setup_plots(
        self,
        num_og_plots: int = 15,
        num_pool_plots: int = 5,
        num_non_keychain_plots: int = 3,
        plot_size: int = 20,
        bitfield: bool = True,
    ) -> bool:
        self.add_plot_directory(self.plot_dir)
        assert self.created_plots == 0
        existing_plots: bool = True
        # OG Plots
        for i in range(num_og_plots):
            plot = await self.new_plot(plot_size=plot_size, bitfield=bitfield)
            if plot.new_plot:
                existing_plots = False
        # Pool Plots
        for i in range(num_pool_plots):
            plot = await self.new_plot(self.pool_ph, plot_size=plot_size, bitfield=bitfield)
            if plot.new_plot:
                existing_plots = False
        # Some plots with keys that are not in the keychain
        for i in range(num_non_keychain_plots):
            plot = await self.new_plot(
                path=self.plot_dir / "not_in_keychain",
                plot_keys=PlotKeys(G1Element(), G1Element(), None),
                exclude_plots=True,
                plot_size=plot_size,
                bitfield=bitfield,
            )
            if plot.new_plot:
                existing_plots = False
        await self.refresh_plots()
        assert len(self.plot_manager.plots) == len(self.expected_plots)
        return existing_plots

    async def new_plot(
        self,
        pool_contract_puzzle_hash: Optional[bytes32] = None,
        path: Optional[Path] = None,
        tmp_dir: Optional[Path] = None,
        plot_keys: Optional[PlotKeys] = None,
        exclude_plots: bool = False,
        plot_size: int = 20,
        bitfield: bool = True,
    ) -> BlockToolsNewPlotResult:
        final_dir = self.plot_dir
        if path is not None:
            final_dir = path
            final_dir.mkdir(parents=True, exist_ok=True)
        if tmp_dir is None:
            tmp_dir = self.temp_dir
        params = Params(
            # Can't go much lower than 20, since plots start having no solutions and more buggy
            size=plot_size,
            # Uses many plots for testing, in order to guarantee proofs of space at every height
            num=1,
            buffer=100,
            tmp_dir=Path(tmp_dir),
            tmp2_dir=Path(tmp_dir),
            final_dir=Path(final_dir),
            plotid=None,
            memo=None,
            buckets=0,
            stripe_size=2000,
            num_threads=0,
            nobitfield=not bitfield,
        )
        try:
            if plot_keys is None:
                pool_pk: Optional[G1Element] = None
                pool_address: Optional[str] = None
                if pool_contract_puzzle_hash is None:
                    pool_pk = self.pool_pk
                else:
                    pool_address = encode_puzzle_hash(pool_contract_puzzle_hash, "xch")

                plot_keys = PlotKeys(self.farmer_pk, pool_pk, pool_address)
            # No datetime in the filename, to get deterministic filenames and not re-plot
            created, existed = await create_plots(
                params,
                plot_keys,
                use_datetime=False,
                test_private_keys=[AugSchemeMPL.key_gen(std_hash(self.created_plots.to_bytes(2, "big")))],
            )
            self.created_plots += 1

            plot_id_new: Optional[bytes32] = None
            path_new: Optional[Path] = None
            new_plot: bool = True

            if len(created):
                assert len(existed) == 0
                plot_id_new, path_new = list(created.items())[0]

            if len(existed):
                assert len(created) == 0
                plot_id_new, path_new = list(existed.items())[0]
                new_plot = False
            assert plot_id_new is not None
            assert path_new is not None

            if not exclude_plots:
                self.expected_plots[plot_id_new] = path_new

            return BlockToolsNewPlotResult(plot_id_new, new_plot)

        except KeyboardInterrupt:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            sys.exit(1)

    async def refresh_plots(self) -> None:
        self.plot_manager.refresh_parameter = replace(
            self.plot_manager.refresh_parameter, batch_size=uint32(4 if len(self.expected_plots) % 3 == 0 else 3)
        )  # Make sure we have at least some batches + a remainder
        self.plot_manager.trigger_refresh()
        assert self.plot_manager.needs_refresh()
        self.plot_manager.start_refreshing(sleep_interval_ms=1)

        with anyio.fail_after(delay=adjusted_timeout(120)):
            for backoff in backoff_times():
                if not self.plot_manager.needs_refresh():
                    break

                await asyncio.sleep(backoff)

        self.plot_manager.stop_refreshing()
        assert not self.plot_manager.needs_refresh()

    async def delete_plot(self, plot_id: bytes32) -> None:
        assert plot_id in self.expected_plots
        self.expected_plots[plot_id].unlink()
        del self.expected_plots[plot_id]
        await self.refresh_plots()

    @property
    def config(self) -> Dict[str, Any]:
        return copy.deepcopy(self._config)

    def get_daemon_ssl_context(self) -> ssl.SSLContext:
        crt_path = self.root_path / self.config["daemon_ssl"]["private_crt"]
        key_path = self.root_path / self.config["daemon_ssl"]["private_key"]
        ca_cert_path = self.root_path / self.config["private_ssl_ca"]["crt"]
        ca_key_path = self.root_path / self.config["private_ssl_ca"]["key"]
        return ssl_context_for_client(ca_cert_path, ca_key_path, crt_path, key_path)

    def get_plot_signature(self, m: bytes32, plot_pk: G1Element) -> G2Element:
        """
        Returns the plot signature of the header data.
        """
        farmer_sk = master_sk_to_farmer_sk(self.all_sks[0])
        for plot_info in self.plot_manager.plots.values():
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
                agg_pk = generate_plot_public_key(local_sk.get_g1(), farmer_sk.get_g1(), include_taproot)
                assert agg_pk == plot_pk
                harv_share = AugSchemeMPL.sign(local_sk, m, agg_pk)
                farm_share = AugSchemeMPL.sign(farmer_sk, m, agg_pk)
                if include_taproot:
                    taproot_sk: PrivateKey = generate_taproot_sk(local_sk.get_g1(), farmer_sk.get_g1())
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
        block_list_input: Optional[List[FullBlock]] = None,
        *,
        farmer_reward_puzzle_hash: Optional[bytes32] = None,
        pool_reward_puzzle_hash: Optional[bytes32] = None,
        transaction_data: Optional[SpendBundle] = None,
        seed: bytes = b"",
        time_per_block: Optional[float] = None,
        force_overflow: bool = False,
        skip_slots: int = 0,  # Force at least this number of empty slots before the first SB
        guarantee_transaction_block: bool = False,  # Force that this block must be a tx block
        keep_going_until_tx_block: bool = False,  # keep making new blocks until we find a tx block
        normalized_to_identity_cc_eos: bool = False,
        normalized_to_identity_icc_eos: bool = False,
        normalized_to_identity_cc_sp: bool = False,
        normalized_to_identity_cc_ip: bool = False,
        current_time: bool = False,
        previous_generator: Optional[Union[CompressorArg, List[uint32]]] = None,
        genesis_timestamp: Optional[uint64] = None,
        force_plot_id: Optional[bytes32] = None,
        dummy_block_references: bool = False,
        include_transactions: bool = False,
    ) -> List[FullBlock]:
        assert num_blocks > 0
        if block_list_input is not None:
            block_list = block_list_input.copy()
        else:
            block_list = []

        tx_block_heights: List[uint32] = []
        if dummy_block_references:
            # block references can only point to transaction blocks, so we need
            # to record which ones are
            for b in block_list:
                if b.transactions_generator is not None:
                    tx_block_heights.append(b.height)

        constants = self.constants
        transaction_data_included = False
        if time_per_block is None:
            time_per_block = float(constants.SUB_SLOT_TIME_TARGET) / float(constants.SLOT_BLOCKS_TARGET)

        available_coins: List[Coin] = []
        pending_rewards: List[Coin] = []
        wallet: Optional[WalletTool] = None
        rng: Optional[Random] = None
        if include_transactions:
            # when we generate transactions in the chain, the caller cannot also
            # have ownership of the rewards and control the transactions
            assert farmer_reward_puzzle_hash is None
            assert pool_reward_puzzle_hash is None
            assert transaction_data is None

            for b in block_list:
                for coin in b.get_included_reward_coins():
                    if coin.puzzle_hash == self.farmer_ph:
                        available_coins.append(coin)
            print(
                f"found {len(available_coins)} reward coins in existing chain."
                "for simplicity, we assume the rewards are all unspent in the original chain"
            )
            wallet = self.get_farmer_wallet_tool()
            rng = Random()
            rng.seed(seed)

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
            self.log.info(f"Created block 0 iters: {genesis.total_iters}")
            num_empty_slots_added = skip_slots
            block_list = [genesis]
            num_blocks -= 1
        else:
            initial_block_list_len = len(block_list)
            num_empty_slots_added = uint32(0)  # Allows forcing empty slots in the beginning, for testing purposes

        if num_blocks == 0:
            return block_list

        blocks: Dict[bytes32, BlockRecord]
        if block_list[-1].header_hash == self._block_cache_header:
            height_to_hash = self._block_cache_height_to_hash
            difficulty = self._block_cache_difficulty
            blocks = self._block_cache
        else:
            height_to_hash, difficulty, blocks = load_block_list(block_list, constants)

        latest_block: BlockRecord = blocks[block_list[-1].header_hash]
        curr = latest_block
        while not curr.is_transaction_block:
            curr = blocks[curr.prev_hash]
        assert curr.timestamp is not None
        last_timestamp = float(curr.timestamp)
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
        # this variable is true whenever there is a pending sub-epoch or epoch that needs to be added in the next block.
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
                        curr.height,
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
                            previous_generator = None
                        if transaction_data is not None:
                            additions = compute_additions_unchecked(transaction_data)
                            removals = transaction_data.removals()
                        elif include_transactions:
                            assert wallet is not None
                            assert rng is not None
                            transaction_data, additions = make_spend_bundle(available_coins, wallet, rng)
                            removals = transaction_data.removals()
                            transaction_data_included = False

                        assert last_timestamp is not None
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

                        block_generator: Optional[BlockGenerator]
                        if transaction_data is not None:
                            if start_height >= constants.HARD_FORK_HEIGHT:
                                block_generator = simple_solution_generator_backrefs(transaction_data)
                                previous_generator = None
                            else:
                                if type(previous_generator) is CompressorArg:
                                    block_generator = best_solution_generator_from_template(
                                        previous_generator, transaction_data
                                    )
                                else:
                                    block_generator = simple_solution_generator(transaction_data)
                                    if type(previous_generator) is list:
                                        block_generator = BlockGenerator(
                                            block_generator.program, [], previous_generator
                                        )

                            aggregate_signature = transaction_data.aggregated_signature
                        else:
                            block_generator = None
                            aggregate_signature = G2Element()

                        if dummy_block_references:
                            if block_generator is None:
                                program = SerializedProgram.from_bytes(solution_generator([]))
                                block_generator = BlockGenerator(program, [], [])

                            if len(tx_block_heights) > 4:
                                block_refs = [
                                    tx_block_heights[1],
                                    tx_block_heights[len(tx_block_heights) // 2],
                                    tx_block_heights[-2],
                                ]
                            else:
                                block_refs = []
                            block_generator = dataclasses.replace(
                                block_generator, block_height_list=block_generator.block_height_list + block_refs
                            )

                        (
                            full_block,
                            block_record,
                            new_timestamp,
                        ) = get_full_block_and_block_record(
                            constants,
                            blocks,
                            sub_slot_start_total_iters,
                            uint8(signage_point_index),
                            proof_of_space,
                            slot_cc_challenge,
                            slot_rc_challenge,
                            farmer_reward_puzzle_hash,
                            pool_target,
                            last_timestamp,
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
                            normalized_to_identity_cc_ip=normalized_to_identity_cc_ip,
                            current_time=current_time,
                        )
                        if block_record.is_transaction_block:
                            transaction_data_included = True
                            previous_generator = None
                            keep_going_until_tx_block = False
                            assert full_block.foliage_transaction_block is not None
                        elif guarantee_transaction_block:
                            continue
                        # print(f"{full_block.height:4}: difficulty {difficulty} "
                        #     f"time: {new_timestamp - last_timestamp:0.2f} "
                        #     f"additions: {len(additions) if block_record.is_transaction_block else 0:2} "
                        #     f"removals: {len(removals) if block_record.is_transaction_block else 0:2} "
                        #     f"refs: {len(full_block.transactions_generator_ref_list):3} "
                        #     f"tx: {block_record.is_transaction_block}")
                        last_timestamp = new_timestamp
                        block_list.append(full_block)

                        if include_transactions:
                            for coin in full_block.get_included_reward_coins():
                                if coin.puzzle_hash == self.farmer_ph:
                                    pending_rewards.append(coin)
                            if full_block.is_transaction_block():
                                available_coins.extend(pending_rewards)
                                pending_rewards = []

                        if full_block.transactions_generator is not None:
                            tx_block_heights.append(full_block.height)
                            compressor_arg = detect_potential_template_generator(
                                full_block.height, full_block.transactions_generator
                            )
                            if compressor_arg is not None:
                                previous_generator = compressor_arg

                        blocks_added_this_sub_slot += 1

                        blocks[full_block.header_hash] = block_record
                        self.log.info(
                            f"Created block {block_record.height} ove=False, iters {block_record.total_iters}"
                        )
                        height_to_hash[uint32(full_block.height)] = full_block.header_hash
                        latest_block = blocks[full_block.header_hash]
                        finished_sub_slots_at_ip = []
                        num_blocks -= 1
                        if num_blocks <= 0 and not keep_going_until_tx_block:
                            self._block_cache_header = block_list[-1].header_hash
                            self._block_cache_height_to_hash = height_to_hash
                            self._block_cache_difficulty = difficulty
                            self._block_cache = blocks
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
            # generate sub_epoch_summary, and if the last block was the last block of the sub-epoch or epoch
            # include the hash in the next sub-slot
            sub_epoch_summary: Optional[SubEpochSummary] = None
            if not pending_ses:  # if we just created a sub-epoch summary, we can at least skip another sub-slot
                sub_epoch_summary = next_sub_epoch_summary(
                    constants,
                    BlockCache(blocks, height_to_hash=height_to_hash),
                    latest_block.required_iters,
                    block_list[-1],
                    False,
                )
            if sub_epoch_summary is not None:  # the previous block is the last block of the sub-epoch or epoch
                pending_ses = True
                ses_hash: Optional[bytes32] = sub_epoch_summary.get_hash()
                # if the last block is the last block of the epoch, we set the new sub-slot iters and difficulty
                new_sub_slot_iters: Optional[uint64] = sub_epoch_summary.new_sub_slot_iters
                new_difficulty: Optional[uint64] = sub_epoch_summary.new_difficulty

                self.log.info(f"Sub epoch summary: {sub_epoch_summary} for block {latest_block.height+1}")
            else:  # the previous block is not the last block of the sub-epoch or epoch
                pending_ses = False
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
            if transaction_data is not None:
                additions = compute_additions_unchecked(transaction_data)
                removals = transaction_data.removals()
            elif include_transactions:
                assert wallet is not None
                assert rng is not None
                transaction_data, additions = make_spend_bundle(available_coins, wallet, rng)
                removals = transaction_data.removals()
                transaction_data_included = False
            sub_slots_finished += 1
            self.log.info(
                f"Sub slot finished. blocks included: {blocks_added_this_sub_slot} blocks_per_slot: "
                f"{(len(block_list) - initial_block_list_len)/sub_slots_finished}"
                f"Sub Epoch Summary Included: {sub_epoch_summary is not None} "
            )
            blocks_added_this_sub_slot = 0  # Sub slot ended, overflows are in next sub slot

            # Handle overflows: No overflows on new epoch or sub-epoch
            if new_sub_slot_iters is None and num_empty_slots_added >= skip_slots and not pending_ses:
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
                        curr.height,
                        force_plot_id=force_plot_id,
                    )
                    for required_iters, proof_of_space in sorted(qualified_proofs, key=lambda t: t[0]):
                        if blocks_added_this_sub_slot == constants.MAX_SUB_SLOT_BLOCKS:
                            break
                        assert last_timestamp is not None
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
                            if start_height >= constants.HARD_FORK_HEIGHT:
                                block_generator = simple_solution_generator_backrefs(transaction_data)
                                previous_generator = None
                            else:
                                if previous_generator is not None and type(previous_generator) is CompressorArg:
                                    block_generator = best_solution_generator_from_template(
                                        previous_generator, transaction_data
                                    )
                                else:
                                    block_generator = simple_solution_generator(transaction_data)
                                    if type(previous_generator) is list:
                                        block_generator = BlockGenerator(
                                            block_generator.program, [], previous_generator
                                        )
                            aggregate_signature = transaction_data.aggregated_signature
                        else:
                            block_generator = None
                            aggregate_signature = G2Element()

                        if dummy_block_references:
                            if block_generator is None:
                                program = SerializedProgram.from_bytes(solution_generator([]))
                                block_generator = BlockGenerator(program, [], [])

                            if len(tx_block_heights) > 4:
                                block_refs = [
                                    tx_block_heights[1],
                                    tx_block_heights[len(tx_block_heights) // 2],
                                    tx_block_heights[-2],
                                ]
                            else:
                                block_refs = []
                            block_generator = dataclasses.replace(
                                block_generator, block_height_list=block_generator.block_height_list + block_refs
                            )

                        (
                            full_block,
                            block_record,
                            new_timestamp,
                        ) = get_full_block_and_block_record(
                            constants,
                            blocks,
                            sub_slot_start_total_iters,
                            uint8(signage_point_index),
                            proof_of_space,
                            slot_cc_challenge,
                            slot_rc_challenge,
                            farmer_reward_puzzle_hash,
                            pool_target,
                            last_timestamp,
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
                            previous_generator = None
                            keep_going_until_tx_block = False
                            assert full_block.foliage_transaction_block is not None
                        elif guarantee_transaction_block:
                            continue
                        # print(f"{full_block.height:4}: difficulty {difficulty} "
                        #     f"time: {new_timestamp - last_timestamp:0.2f} "
                        #     f"additions: {len(additions) if block_record.is_transaction_block else 0:2} "
                        #     f"removals: {len(removals) if block_record.is_transaction_block else 0:2} "
                        #     f"refs: {len(full_block.transactions_generator_ref_list):3} "
                        #     f"tx: {block_record.is_transaction_block}")
                        last_timestamp = new_timestamp

                        block_list.append(full_block)

                        if include_transactions:
                            for coin in full_block.get_included_reward_coins():
                                if coin.puzzle_hash == self.farmer_ph:
                                    pending_rewards.append(coin)
                            if full_block.is_transaction_block():
                                available_coins.extend(pending_rewards)
                                pending_rewards = []

                        if full_block.transactions_generator is not None:
                            tx_block_heights.append(full_block.height)
                            compressor_arg = detect_potential_template_generator(
                                full_block.height, full_block.transactions_generator
                            )
                            if compressor_arg is not None:
                                previous_generator = compressor_arg

                        blocks_added_this_sub_slot += 1
                        self.log.info(f"Created block {block_record.height } ov=True, iters {block_record.total_iters}")
                        num_blocks -= 1

                        blocks[full_block.header_hash] = block_record
                        height_to_hash[uint32(full_block.height)] = full_block.header_hash
                        latest_block = blocks[full_block.header_hash]
                        finished_sub_slots_at_ip = []

                        if num_blocks <= 0 and not keep_going_until_tx_block:
                            self._block_cache_header = block_list[-1].header_hash
                            self._block_cache_height_to_hash = height_to_hash
                            self._block_cache_difficulty = difficulty
                            self._block_cache = blocks
                            return block_list

            finished_sub_slots_at_sp = finished_sub_slots_eos.copy()
            same_slot_as_last = False
            sub_slot_start_total_iters = uint128(sub_slot_start_total_iters + sub_slot_iters)
            if num_blocks < prev_num_of_blocks:
                num_empty_slots_added += 1

            if new_sub_slot_iters is not None and new_difficulty is not None:  # new epoch
                sub_slot_iters = new_sub_slot_iters
                difficulty = new_difficulty

    def create_genesis_block(
        self,
        constants: ConsensusConstants,
        seed: bytes = b"",
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
                # we're creating the genesis block, its height is always 0
                qualified_proofs: List[Tuple[uint64, ProofOfSpace]] = self.get_pospaces_for_challenge(
                    constants,
                    cc_challenge,
                    cc_sp_output_hash,
                    seed,
                    constants.DIFFICULTY_STARTING,
                    constants.SUB_SLOT_ITERS_STARTING,
                    uint32(0),
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
                        compute_cost=compute_cost_test,
                        compute_fees=compute_fee_test,
                    )
                    assert unfinished_block is not None
                    if not is_overflow:
                        cc_ip_vdf, cc_ip_proof = get_vdf_info_and_proof(
                            constants,
                            ClassgroupElement.get_default_element(),
                            cc_challenge,
                            ip_iters,
                        )
                        cc_ip_vdf = cc_ip_vdf.replace(number_of_iterations=ip_iters)
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
                            uint8(unfinished_block.reward_chain_block.signage_point_index),
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
        height: uint32,
        force_plot_id: Optional[bytes32] = None,
    ) -> List[Tuple[uint64, ProofOfSpace]]:
        found_proofs: List[Tuple[uint64, ProofOfSpace]] = []
        rng = random.Random()
        rng.seed(seed)
        for plot_info in self.plot_manager.plots.values():
            plot_id: bytes32 = plot_info.prover.get_id()
            if force_plot_id is not None and plot_id != force_plot_id:
                continue
            prefix_bits = calculate_prefix_bits(constants, height)
            if passes_plot_filter(prefix_bits, plot_id, challenge_hash, signage_point):
                new_challenge: bytes32 = calculate_pos_challenge(plot_id, challenge_hash, signage_point)
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
                        plot_pk = generate_plot_public_key(local_sk.get_g1(), farmer_public_key, include_taproot)
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
            if rng.random() < 0.1:
                # Removes some proofs of space to create "random" chains, based on the seed
                random_sample = rng.sample(found_proofs, len(found_proofs) - 1)
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
    cc_sp_vdf = cc_sp_vdf.replace(number_of_iterations=sp_iters)
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
        new_ip_iters = uint64(unfinished_block.total_iters - latest_block.total_iters)
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
    cc_ip_vdf = cc_ip_vdf.replace(number_of_iterations=ip_iters)
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
    blocks: Dict[bytes32, BlockRecord],
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


def get_plot_dir(plot_dir_name: str = "test-plots", automated_testing: bool = True) -> Path:
    root_dir = DEFAULT_ROOT_PATH.parent
    if not automated_testing:  # make sure we don't accidentally stack directories.
        root_dir = (
            root_dir.parent
            if root_dir.parts[-1] == plot_dir_name.split("/")[0] or root_dir.parts[-1] == plot_dir_name.split("\\")[0]
            else root_dir
        )
    cache_path = root_dir.joinpath(plot_dir_name)

    ci = os.environ.get("CI")
    if ci is not None and not cache_path.exists() and automated_testing:
        raise Exception(f"Running in CI and expected path not found: {cache_path!r}")

    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path


def get_plot_tmp_dir(plot_dir_name: str = "test-plots", automated_testing: bool = True) -> Path:
    return get_plot_dir(plot_dir_name, automated_testing) / "tmp"


def load_block_list(
    block_list: List[FullBlock], constants: ConsensusConstants
) -> Tuple[Dict[uint32, bytes32], uint64, Dict[bytes32, BlockRecord]]:
    difficulty = 0
    height_to_hash: Dict[uint32, bytes32] = {}
    blocks: Dict[bytes32, BlockRecord] = {}
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
        quality_str = verify_and_get_quality_string(
            full_block.reward_chain_block.proof_of_space, constants, challenge, sp_hash, height=full_block.height
        )
        assert quality_str is not None
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
    blocks: Dict[bytes32, BlockRecord],
    sub_slot_start_total_iters: uint128,
    signage_point_index: uint8,
    proof_of_space: ProofOfSpace,
    slot_cc_challenge: bytes32,
    slot_rc_challenge: bytes32,
    farmer_reward_puzzle_hash: bytes32,
    pool_target: PoolTarget,
    last_timestamp: float,
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
    *,
    overflow_cc_challenge: Optional[bytes32] = None,
    overflow_rc_challenge: Optional[bytes32] = None,
    normalized_to_identity_cc_ip: bool = False,
    current_time: bool = False,
) -> Tuple[FullBlock, BlockRecord, float]:
    # we're simulating time between blocks here. The more VDF iterations the
    # blocks advances, the longer it should have taken (and vice versa). This
    # formula is meant to converge at 1024 iters per the specified
    # time_per_block (which defaults to 18.75 seconds)
    time_per_block *= (((sub_slot_iters / 1024) - 1) * 0.2) + 1
    if current_time is True:
        timestamp = max(int(time.time()), last_timestamp + time_per_block)
    else:
        timestamp = last_timestamp + time_per_block
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
        uint64(timestamp),
        BlockCache(blocks),
        seed,
        block_generator,
        aggregate_signature,
        additions,
        removals,
        prev_block,
        finished_sub_slots,
        compute_cost=compute_cost_test,
        compute_fees=compute_fee_test,
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

    return full_block, block_record, timestamp


# these are the costs of unknown conditions, as defined chia_rs here:
# https://github.com/Chia-Network/chia_rs/pull/181
def compute_cost_table() -> List[int]:
    A = 17
    B = 16
    s = []
    NUM = 100
    DEN = 1
    MAX = 1 << 59
    for i in range(256):
        v = str(NUM // DEN)
        v1 = v[:3] + ("0" * (len(v) - 3))
        s.append(int(v1))
        NUM *= A
        DEN *= B
        assert NUM < 1 << 64
        assert DEN < 1 << 64
        if NUM > MAX:
            NUM >>= 5
            DEN >>= 5
    return s


CONDITION_COSTS = compute_cost_table()


def conditions_cost(conds: Program, hard_fork: bool) -> uint64:
    condition_cost = 0
    for cond in conds.as_iter():
        condition = cond.first().as_atom()
        if condition in [ConditionOpcode.AGG_SIG_UNSAFE, ConditionOpcode.AGG_SIG_ME]:
            condition_cost += ConditionCost.AGG_SIG.value
        elif condition == ConditionOpcode.CREATE_COIN:
            condition_cost += ConditionCost.CREATE_COIN.value
        # after the 2.0 hard fork, two byte conditions (with no leading 0)
        # have costs. Account for that.
        elif hard_fork and len(condition) == 2 and condition[0] != 0:
            condition_cost += CONDITION_COSTS[condition[1]]
        elif hard_fork and condition == ConditionOpcode.SOFTFORK.value:
            arg = cond.rest().first().as_int()
            condition_cost += arg * 10000
        elif hard_fork and condition in [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
        ]:
            condition_cost += ConditionCost.AGG_SIG.value
    return uint64(condition_cost)


def compute_fee_test(additions: Sequence[Coin], removals: Sequence[Coin]) -> uint64:
    removal_amount = 0
    addition_amount = 0
    for coin in removals:
        removal_amount += coin.amount
    for coin in additions:
        addition_amount += coin.amount

    ret = removal_amount - addition_amount
    # in order to allow creating blocks that mint coins, clamp the fee
    # to 0, if it ends up being negative
    if ret < 0:
        ret = 0
    return uint64(ret)


def compute_cost_test(generator: BlockGenerator, constants: ConsensusConstants, height: uint32) -> uint64:
    # this function cannot *validate* the block or any of the transactions. We
    # deliberately create invalid blocks as parts of the tests, and we still
    # need to be able to compute the cost of it

    condition_cost = 0
    clvm_cost = 0

    if height >= constants.HARD_FORK_FIX_HEIGHT:
        blocks = [bytes(g) for g in generator.generator_refs]
        cost, result = generator.program._run(INFINITE_COST, MEMPOOL_MODE | ALLOW_BACKREFS, [DESERIALIZE_MOD, blocks])
        clvm_cost += cost

        for spend in result.first().as_iter():
            # each spend is a list of:
            # (parent-coin-id puzzle amount solution)
            puzzle = spend.at("rf")
            solution = spend.at("rrrf")

            cost, result = puzzle._run(INFINITE_COST, MEMPOOL_MODE, solution)
            clvm_cost += cost
            condition_cost += conditions_cost(result, height >= constants.HARD_FORK_HEIGHT)

    else:
        block_program_args = SerializedProgram.to([[bytes(g) for g in generator.generator_refs]])
        clvm_cost, result = GENERATOR_MOD._run(INFINITE_COST, MEMPOOL_MODE, [generator.program, block_program_args])

        for res in result.first().as_iter():
            # each condition item is:
            # (parent-coin-id puzzle-hash amount conditions)
            conditions = res.at("rrrf")
            condition_cost += conditions_cost(conditions, height >= constants.HARD_FORK_HEIGHT)

    size_cost = len(bytes(generator.program)) * constants.COST_PER_BYTE

    return uint64(clvm_cost + size_cost + condition_cost)


@dataclass
class BlockToolsNewPlotResult:
    plot_id: bytes32
    new_plot: bool


# Remove these counters when `create_block_tools` and `create_block_tools_async` are removed
create_block_tools_async_count = 0
create_block_tools_count = 0

# Note: tests that still use `create_block_tools` and `create_block_tools_async` should probably be
# moved to the bt fixture in conftest.py. Take special care to find out if the users of these functions
# need different BlockTools instances

# All tests need different root directories containing different config.yaml files.
# The daemon's listen port is configured in the config.yaml, and the only way a test can control which
# listen port it uses is to write it to the config file.


async def create_block_tools_async(
    constants: ConsensusConstants = test_constants,
    root_path: Optional[Path] = None,
    keychain: Optional[Keychain] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> BlockTools:
    global create_block_tools_async_count
    create_block_tools_async_count += 1
    print(f"  create_block_tools_async called {create_block_tools_async_count} times")
    bt = BlockTools(constants, root_path, keychain, config_overrides=config_overrides)
    await bt.setup_keys()
    await bt.setup_plots()

    return bt


def create_block_tools(
    constants: ConsensusConstants = test_constants,
    root_path: Optional[Path] = None,
    keychain: Optional[Keychain] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> BlockTools:
    global create_block_tools_count
    create_block_tools_count += 1
    print(f"  create_block_tools called {create_block_tools_count} times")
    bt = BlockTools(constants, root_path, keychain, config_overrides=config_overrides)

    asyncio.get_event_loop().run_until_complete(bt.setup_keys())
    asyncio.get_event_loop().run_until_complete(bt.setup_plots())
    return bt


def make_unfinished_block(block: FullBlock, constants: ConsensusConstants) -> UnfinishedBlock:
    if is_overflow_block(constants, uint8(block.reward_chain_block.signage_point_index)):
        finished_ss = block.finished_sub_slots[:-1]
    else:
        finished_ss = block.finished_sub_slots

    return UnfinishedBlock(
        finished_ss,
        block.reward_chain_block.get_unfinished(),
        block.challenge_chain_sp_proof,
        block.reward_chain_sp_proof,
        block.foliage,
        block.foliage_transaction_block,
        block.transactions_info,
        block.transactions_generator,
        block.transactions_generator_ref_list,
    )
