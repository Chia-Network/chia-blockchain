import os
import sys
import time
import random
import tempfile

from pathlib import Path
from typing import Dict, List, Tuple, Optional

from blspy import (
    PrependSignature,
    PrivateKey,
    PublicKey,
    InsecureSignature,
    Util,
)
from chiavdf import prove
from chiabip158 import PyBIP158

from chiapos import DiskPlotter
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.consensus.constants import ConsensusConstants
from src.cmds.init import create_default_chia_config, initialize_ssl
from src.types.BLSSignature import BLSPublicKey
from src.consensus import block_rewards, pot_iterations
from src.consensus.pot_iterations import calculate_min_iters_from_iterations
from src.consensus.block_rewards import calculate_block_reward
from src.consensus.coinbase import create_coinbase_coin, create_fees_coin
from src.types.challenge import Challenge
from src.types.classgroup import ClassgroupElement
from src.types.full_block import FullBlock, additions_for_npc
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin, hash_coin_list
from src.types.program import Program
from src.types.header import Header, HeaderData
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime
from src.types.pool_target import PoolTarget
from src.types.sized_bytes import bytes32
from src.util.keychain import Keychain
from src.util.merkle_set import MerkleSet
from src.util.ints import uint8, uint32, uint64, uint128, int512
from src.util.hash import std_hash
from src.util.path import mkdir
from src.util.significant_bits import truncate_to_significant_bits
from src.util.mempool_check_conditions import get_name_puzzle_conditions
from src.util.config import load_config, save_config
from src.util.plot_tools import load_plots, stream_plot_info
from src.util.logging import initialize_logging

from tests.wallet_tools import WalletTool


def get_plot_dir():
    cache_path = (
        Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/"))) / "test-plots"
    )
    mkdir(cache_path)
    return cache_path


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    def __init__(
        self, root_path: Optional[Path] = None, real_plots: bool = False,
    ):
        self._tempdir = None
        if root_path is None:
            self._tempdir = tempfile.TemporaryDirectory()
            root_path = Path(self._tempdir.name)
        self.root_path = root_path
        self.n_wesolowski = uint8(0)
        self.real_plots = real_plots

        if not real_plots:
            create_default_chia_config(root_path)
            initialize_ssl(root_path)
            # No real plots supplied, so we will use the small test plots
            self.use_any_pos = True
            # Can't go much lower than 18, since plots start having no solutions
            k: uint8 = uint8(18)
            # Uses many plots for testing, in order to guarantee proofs of space at every height
            num_plots = 35
            # Use the empty string as the seed for the private key

            self.keychain = Keychain("testing-1.8", True)
            self.keychain.delete_all_keys()
            self.farmer_pk = (
                self.keychain.add_private_key(b"block_tools farmer key", "")
                .public_child(0)
                .get_public_key()
            )
            self.pool_pk = (
                self.keychain.add_private_key(b"block_tools pool key", "")
                .public_child(0)
                .get_public_key()
            )

            plot_dir = get_plot_dir()
            mkdir(plot_dir)
            filenames: List[Path] = [
                Path(
                    plot_dir
                    / f"genesis-plots-1.8-{k}{std_hash(int.to_bytes(i, 4, 'big')).hex()}.plot"
                )
                for i in range(num_plots)
            ]
            done_filenames = set()
            temp_dir = plot_dir / "plot.tmp"
            mkdir(temp_dir)
            try:
                for pn, filename in enumerate(filenames):
                    sk: PrivateKey = PrivateKey.from_seed(pn.to_bytes(4, "big"))
                    plot_public_key = ProofOfSpace.generate_plot_public_key(
                        sk.get_public_key(), self.farmer_pk
                    )
                    plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(
                        self.pool_pk, plot_public_key
                    )
                    self.farmer_ph = create_puzzlehash_for_pk(
                        BLSPublicKey(bytes(self.farmer_pk))
                    )
                    self.pool_ph = create_puzzlehash_for_pk(
                        BLSPublicKey(bytes(self.pool_pk))
                    )
                    if not (plot_dir / filename).exists():
                        plotter = DiskPlotter()
                        plotter.create_plot_disk(
                            str(plot_dir),
                            str(plot_dir),
                            str(plot_dir),
                            str(filename),
                            k,
                            stream_plot_info(self.pool_pk, self.farmer_pk, sk),
                            plot_seed,
                            128,
                        )
                        done_filenames.add(filename)
                self.config = load_config(self.root_path, "config.yaml")
                self.config["harvester"]["plot_directories"].append(str(plot_dir))
                save_config(self.root_path, "config.yaml", self.config)

            except KeyboardInterrupt:
                for filename in filenames:
                    if (
                        filename not in done_filenames
                        and (plot_dir / filename).exists()
                    ):
                        (plot_dir / filename).unlink()
                sys.exit(1)
        else:
            initialize_ssl(root_path)
            self.keychain = Keychain()
            self.use_any_pos = False
            pk = self.keychain.get_all_public_keys()[0].public_child(0).get_public_key()
            self.farmer_ph = create_puzzlehash_for_pk(BLSPublicKey(bytes(pk)))
            self.pool_ph = create_puzzlehash_for_pk(BLSPublicKey(bytes(pk)))

        self.all_pubkeys: List[PublicKey] = [
            epk.public_child(0).get_public_key()
            for epk in self.keychain.get_all_public_keys()
        ]
        if len(self.all_pubkeys) == 0:
            raise RuntimeError("Keys not generated. Run `chia generate keys`")
        _, self.plots, _, _ = load_plots(
            {}, self.all_pubkeys, self.all_pubkeys, root_path
        )

    def get_plot_signature(
        self, header_data: HeaderData, plot_pk: PublicKey
    ) -> Optional[PrependSignature]:
        """
        Returns the plot signature of the header data.
        """
        esks = self.keychain.get_all_private_keys()
        farmer_sk = esks[0][0].private_child(0).get_private_key()
        for _, plot_info in self.plots.items():
            agg_pk = ProofOfSpace.generate_plot_public_key(
                plot_info.harvester_sk.get_public_key(), plot_info.farmer_public_key
            )
            if agg_pk == plot_pk:
                m = bytes(agg_pk) + Util.hash256(header_data.get_hash())
                harv_share = plot_info.harvester_sk.sign_insecure(m)
                farm_share = farmer_sk.sign_insecure(m)
                return PrependSignature.from_insecure_sig(
                    InsecureSignature.aggregate([harv_share, farm_share])
                )
        return None

    def get_pool_key_signature(
        self, pool_target: PoolTarget, pool_pk: PublicKey
    ) -> Optional[PrependSignature]:
        for esk, _ in self.keychain.get_all_private_keys():
            sk = esk.private_child(0).get_private_key()
            if sk.get_public_key() == pool_pk:
                return sk.sign_prepend(bytes(pool_target))
        return None

    def get_farmer_wallet_tool(self):
        esks = self.keychain.get_all_private_keys()
        return WalletTool(esks[0][0])

    def get_pool_wallet_tool(self):
        esks = self.keychain.get_all_private_keys()
        return WalletTool(esks[1][0])

    def get_consecutive_blocks(
        self,
        test_constants: ConsensusConstants,
        num_blocks: int,
        block_list: List[FullBlock] = [],
        seconds_per_block=None,
        seed: bytes = b"",
        reward_puzzlehash: bytes32 = None,
        transaction_data_at_height: Dict[int, Tuple[Program, BLSSignature]] = None,
        fees: uint64 = uint64(0),
    ) -> List[FullBlock]:
        if transaction_data_at_height is None:
            transaction_data_at_height = {}
        if seconds_per_block is None:
            seconds_per_block = test_constants["BLOCK_TIME_TARGET"]

        if len(block_list) == 0:
            block_list.append(FullBlock.from_bytes(test_constants["GENESIS_BLOCK"]))
            prev_difficulty = test_constants["DIFFICULTY_STARTING"]
            curr_difficulty = prev_difficulty
            curr_min_iters = test_constants["MIN_ITERS_STARTING"]
        elif len(block_list) < (
            test_constants["DIFFICULTY_EPOCH"] + test_constants["DIFFICULTY_DELAY"]
        ):
            # First epoch (+delay), so just get first difficulty
            prev_difficulty = block_list[0].weight
            curr_difficulty = block_list[0].weight
            assert test_constants["DIFFICULTY_STARTING"] == prev_difficulty
            curr_min_iters = test_constants["MIN_ITERS_STARTING"]
        else:
            curr_difficulty = block_list[-1].weight - block_list[-2].weight
            prev_difficulty = (
                block_list[-1 - test_constants["DIFFICULTY_EPOCH"]].weight
                - block_list[-2 - test_constants["DIFFICULTY_EPOCH"]].weight
            )
            assert block_list[-1].proof_of_time is not None
            curr_min_iters = calculate_min_iters_from_iterations(
                block_list[-1].proof_of_space,
                curr_difficulty,
                block_list[-1].proof_of_time.number_of_iterations,
                test_constants["NUMBER_ZERO_BITS_CHALLENGE_SIG"],
            )

        starting_height = block_list[-1].height + 1
        timestamp = block_list[-1].header.data.timestamp
        for next_height in range(starting_height, starting_height + num_blocks):
            if (
                next_height > test_constants["DIFFICULTY_EPOCH"]
                and next_height % test_constants["DIFFICULTY_EPOCH"]
                == test_constants["DIFFICULTY_DELAY"]
            ):
                # Calculates new difficulty
                height1 = uint64(
                    next_height
                    - (
                        test_constants["DIFFICULTY_EPOCH"]
                        + test_constants["DIFFICULTY_DELAY"]
                    )
                    - 1
                )
                height2 = uint64(next_height - (test_constants["DIFFICULTY_EPOCH"]) - 1)
                height3 = uint64(next_height - (test_constants["DIFFICULTY_DELAY"]) - 1)
                if height1 >= 0:
                    block1 = block_list[height1]
                    iters1 = block1.header.data.total_iters
                    timestamp1 = block1.header.data.timestamp
                else:
                    block1 = block_list[0]
                    timestamp1 = (
                        block1.header.data.timestamp
                        - test_constants["BLOCK_TIME_TARGET"]
                    )
                    iters1 = uint64(0)
                timestamp2 = block_list[height2].header.data.timestamp
                timestamp3 = block_list[height3].header.data.timestamp

                block3 = block_list[height3]
                iters3 = block3.header.data.total_iters
                term1 = (
                    test_constants["DIFFICULTY_DELAY"]
                    * prev_difficulty
                    * (timestamp3 - timestamp2)
                    * test_constants["BLOCK_TIME_TARGET"]
                )

                term2 = (
                    (test_constants["DIFFICULTY_WARP_FACTOR"] - 1)
                    * (
                        test_constants["DIFFICULTY_EPOCH"]
                        - test_constants["DIFFICULTY_DELAY"]
                    )
                    * curr_difficulty
                    * (timestamp2 - timestamp1)
                    * test_constants["BLOCK_TIME_TARGET"]
                )

                # Round down after the division
                new_difficulty_precise: uint64 = uint64(
                    (term1 + term2)
                    // (
                        test_constants["DIFFICULTY_WARP_FACTOR"]
                        * (timestamp3 - timestamp2)
                        * (timestamp2 - timestamp1)
                    )
                )
                new_difficulty = uint64(
                    truncate_to_significant_bits(
                        new_difficulty_precise, test_constants["SIGNIFICANT_BITS"]
                    )
                )
                max_diff = uint64(
                    truncate_to_significant_bits(
                        test_constants["DIFFICULTY_FACTOR"] * curr_difficulty,
                        test_constants["SIGNIFICANT_BITS"],
                    )
                )
                min_diff = uint64(
                    truncate_to_significant_bits(
                        curr_difficulty // test_constants["DIFFICULTY_FACTOR"],
                        test_constants["SIGNIFICANT_BITS"],
                    )
                )
                if new_difficulty >= curr_difficulty:
                    new_difficulty = min(new_difficulty, max_diff,)
                else:
                    new_difficulty = max([uint64(1), new_difficulty, min_diff])

                min_iters_precise = uint64(
                    (iters3 - iters1)
                    // (
                        test_constants["DIFFICULTY_EPOCH"]
                        * test_constants["MIN_ITERS_PROPORTION"]
                    )
                )
                curr_min_iters = uint64(
                    truncate_to_significant_bits(
                        min_iters_precise, test_constants["SIGNIFICANT_BITS"]
                    )
                )
                prev_difficulty = curr_difficulty
                curr_difficulty = new_difficulty
            time_taken = seconds_per_block
            timestamp += time_taken

            transactions: Optional[Program] = None
            aggsig: Optional[BLSSignature] = None
            if next_height in transaction_data_at_height:
                transactions, aggsig = transaction_data_at_height[next_height]

            update_difficulty = (
                next_height % test_constants["DIFFICULTY_EPOCH"]
                == test_constants["DIFFICULTY_DELAY"]
            )
            block_list.append(
                self.create_next_block(
                    test_constants,
                    block_list[-1],
                    timestamp,
                    update_difficulty,
                    curr_difficulty,
                    curr_min_iters,
                    seed,
                    reward_puzzlehash,
                    transactions,
                    aggsig,
                    fees,
                )
            )
        return block_list

    def create_genesis_block(
        self,
        test_constants: ConsensusConstants,
        challenge_hash=bytes([0] * 32),
        seed: bytes = b"",
        reward_puzzlehash: Optional[bytes32] = None,
    ) -> FullBlock:
        """
        Creates the genesis block with the specified details.
        """
        return self._create_block(
            test_constants,
            challenge_hash,
            uint32(0),
            bytes([0] * 32),
            uint64(0),
            uint128(0),
            uint64(int(time.time())),
            uint64(test_constants["DIFFICULTY_STARTING"]),
            uint64(test_constants["MIN_ITERS_STARTING"]),
            seed,
            True,
            reward_puzzlehash,
        )

    def create_next_block(
        self,
        test_constants: ConsensusConstants,
        prev_block: FullBlock,
        timestamp: uint64,
        update_difficulty: bool,
        difficulty: uint64,
        min_iters: uint64,
        seed: bytes = b"",
        reward_puzzlehash: bytes32 = None,
        transactions: Program = None,
        aggsig: BLSSignature = None,
        fees: uint64 = uint64(0),
    ) -> FullBlock:
        """
        Creates the next block with the specified details.
        """
        assert prev_block.proof_of_time is not None
        if update_difficulty:
            challenge = Challenge(
                prev_block.proof_of_space.challenge_hash,
                std_hash(
                    prev_block.proof_of_space.get_hash()
                    + prev_block.proof_of_time.output.get_hash()
                ),
                difficulty,
            )
        else:
            challenge = Challenge(
                prev_block.proof_of_space.challenge_hash,
                std_hash(
                    prev_block.proof_of_space.get_hash()
                    + prev_block.proof_of_time.output.get_hash()
                ),
                None,
            )

        return self._create_block(
            test_constants,
            challenge.get_hash(),
            uint32(prev_block.height + 1),
            prev_block.header_hash,
            prev_block.header.data.total_iters,
            prev_block.weight,
            timestamp,
            uint64(difficulty),
            min_iters,
            seed,
            False,
            reward_puzzlehash,
            transactions,
            aggsig,
            fees,
        )

    def _create_block(
        self,
        test_constants: ConsensusConstants,
        challenge_hash: bytes32,
        height: uint32,
        prev_header_hash: bytes32,
        prev_iters: uint64,
        prev_weight: uint128,
        timestamp: uint64,
        difficulty: uint64,
        min_iters: uint64,
        seed: bytes,
        genesis: bool = False,
        reward_puzzlehash: bytes32 = None,
        transactions: Program = None,
        aggsig: BLSSignature = None,
        fees: uint64 = uint64(0),
    ) -> FullBlock:
        """
        Creates a block with the specified details. Uses the stored plots to create a proof of space,
        and also evaluates the VDF for the proof of time.
        """
        selected_plot_info = None
        selected_proof_index = 0
        selected_quality: Optional[bytes] = None
        best_quality = 0
        plots = list(self.plots.values())
        if self.use_any_pos:
            for i in range(len(plots) * 3):
                # Allow passing in seed, to create reorgs and different chains
                random.seed(seed + i.to_bytes(4, "big"))
                seeded_pn = random.randint(0, len(plots) - 1)
                plot_info = plots[seeded_pn]
                plot_seed = plot_info.prover.get_id()
                ccp = ProofOfSpace.can_create_proof(
                    plot_seed,
                    challenge_hash,
                    test_constants["NUMBER_ZERO_BITS_CHALLENGE_SIG"],
                )
                if not ccp:
                    continue
                qualities = plot_info.prover.get_qualities_for_challenge(challenge_hash)
                if len(qualities) > 0:
                    selected_plot_info = plot_info
                    selected_quality = qualities[0]
                    break
        else:
            for i in range(len(plots)):
                plot_info = plots[i]
                j = 0
                plot_seed = plot_info.prover.get_id()
                ccp = ProofOfSpace.can_create_proof(
                    plot_seed,
                    challenge_hash,
                    test_constants["NUMBER_ZERO_BITS_CHALLENGE_SIG"],
                )
                if not ccp:
                    continue
                qualities = plot_info.prover.get_qualities_for_challenge(challenge_hash)
                for quality in qualities:
                    qual_int = int.from_bytes(quality, "big", signed=False)
                    if qual_int > best_quality:
                        best_quality = qual_int
                        selected_quality = quality
                        selected_plot_info = plot_info
                        selected_proof_index = j
                    j += 1

        assert selected_plot_info is not None
        if selected_quality is None:
            raise RuntimeError("No proofs for this challenge")

        proof_xs: bytes = selected_plot_info.prover.get_full_proof(
            challenge_hash, selected_proof_index
        )

        plot_pk = ProofOfSpace.generate_plot_public_key(
            selected_plot_info.harvester_sk.get_public_key(),
            selected_plot_info.farmer_public_key,
        )
        proof_of_space: ProofOfSpace = ProofOfSpace(
            challenge_hash,
            selected_plot_info.pool_public_key,
            plot_pk,
            selected_plot_info.prover.get_size(),
            proof_xs,
        )
        number_iters: uint64 = pot_iterations.calculate_iterations(
            proof_of_space,
            difficulty,
            min_iters,
            test_constants["NUMBER_ZERO_BITS_CHALLENGE_SIG"],
        )
        if self.real_plots:
            print(f"Performing {number_iters} VDF iterations")

        int_size = (test_constants["DISCRIMINANT_SIZE_BITS"] + 16) >> 4

        result = prove(
            challenge_hash, test_constants["DISCRIMINANT_SIZE_BITS"], number_iters
        )

        output = ClassgroupElement(
            int512(int.from_bytes(result[0:int_size], "big", signed=True,)),
            int512(
                int.from_bytes(result[int_size : 2 * int_size], "big", signed=True,)
            ),
        )
        proof_bytes = result[2 * int_size : 4 * int_size]

        proof_of_time = ProofOfTime(
            challenge_hash, number_iters, output, self.n_wesolowski, proof_bytes,
        )

        # Use the extension data to create different blocks based on header hash
        extension_data: bytes32 = bytes32([random.randint(0, 255) for _ in range(32)])
        cost = uint64(0)

        fee_reward = uint64(block_rewards.calculate_base_fee(height) + fees)

        std_hash(std_hash(height))

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
        cb_reward = calculate_block_reward(height)
        cb_coin = create_coinbase_coin(height, pool_ph, cb_reward)
        fees_coin = create_fees_coin(height, farmer_ph, fee_reward)
        for coin in tx_additions + [cb_coin, fees_coin]:
            if coin.puzzle_hash in puzzlehash_coin_map:
                puzzlehash_coin_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coin_map[coin.puzzle_hash] = [coin]

        # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
        for puzzle, coins in puzzlehash_coin_map.items():
            addition_merkle_set.add_already_hashed(puzzle)
            addition_merkle_set.add_already_hashed(hash_coin_list(coins))

        additions_root = addition_merkle_set.get_root()
        removal_root = removal_merkle_set.get_root()

        generator_hash = (
            transactions.get_tree_hash()
            if transactions is not None
            else bytes32([0] * 32)
        )
        filter_hash = std_hash(encoded)

        pool_target = PoolTarget(pool_ph, uint32(height))
        pool_target_signature = self.get_pool_key_signature(
            pool_target, proof_of_space.pool_public_key
        )
        assert pool_target_signature is not None
        final_aggsig: BLSSignature = BLSSignature(bytes(pool_target_signature))
        if aggsig is not None:
            final_aggsig = BLSSignature.aggregate([final_aggsig, aggsig])

        header_data: HeaderData = HeaderData(
            height,
            prev_header_hash,
            timestamp,
            filter_hash,
            proof_of_space.get_hash(),
            uint128(prev_weight + difficulty),
            uint64(prev_iters + number_iters),
            additions_root,
            removal_root,
            farmer_ph,
            fee_reward,
            pool_target,
            final_aggsig,
            cost,
            extension_data,
            generator_hash,
        )

        header_hash_sig: PrependSignature = self.get_plot_signature(
            header_data, plot_pk
        )

        header: Header = Header(header_data, header_hash_sig)

        full_block: FullBlock = FullBlock(
            proof_of_space, proof_of_time, header, transactions, encoded
        )

        return full_block


# This code generates a genesis block, call as main to output genesis block to terminal
# This might take a while, using the python VDF implementation.
# Run by doing python -m tests.block_tools
if __name__ == "__main__":
    from src.util.default_root import DEFAULT_ROOT_PATH
    from src.consensus.constants import constants as consensus_constants

    initialize_logging("block_tools", {"log_stdout": True}, DEFAULT_ROOT_PATH)
    bt = BlockTools(root_path=DEFAULT_ROOT_PATH, real_plots=True)
    print(
        bytes(
            bt.create_genesis_block(
                consensus_constants,
                bytes((20758).to_bytes(4, "big") + bytes([20758 % 256] * 28)),
                b"0",
                bytes32(
                    bytes.fromhex(
                        "30944219616695e48f7a9b54b38877104a1f5fbe85c61da2fbe35275418a64bc"
                    )
                ),
            )
        )
    )
