import os
import sys
import time
import random

from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from blspy import PrependSignature, PrivateKey, PublicKey
from chiavdf import prove
from chiabip158 import PyBIP158

from chiapos import DiskPlotter, DiskProver
from src import __version__
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.cmds.init import create_default_chia_config, initialize_ssl
from src.types.BLSSignature import BLSPublicKey
from src.consensus import block_rewards, pot_iterations
from src.consensus.constants import constants
from src.consensus.pot_iterations import calculate_min_iters_from_iterations
from src.consensus.coinbase import create_coinbase_coin_and_signature
from src.types.challenge import Challenge
from src.types.classgroup import ClassgroupElement
from src.types.full_block import FullBlock, additions_for_npc
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin, hash_coin_list
from src.types.program import Program
from src.types.header import Header, HeaderData
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime
from src.types.sized_bytes import bytes32
from src.util.keychain import Keychain
from src.util.merkle_set import MerkleSet
from src.util.ints import uint8, uint32, uint64, uint128, int512
from src.util.hash import std_hash
from src.util.path import mkdir
from src.util.significant_bits import truncate_to_significant_bits
from src.util.mempool_check_conditions import get_name_puzzle_conditions
from src.util.config import load_config, load_config_cli, save_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.harvester import load_plots


TEST_ROOT_PATH = Path(
    os.path.expanduser(
        os.getenv("CHIA_TEST_ROOT", "~/.chia/beta-{version}-test").format(
            version=__version__
        )
    )
).resolve()


def get_plot_dir(root_path):
    CHIA_TEST_PLOT_ROOT = os.getenv("CHIA_TEST_PLOT_ROOT")
    if CHIA_TEST_PLOT_ROOT:
        return Path(
            os.path.expanduser(CHIA_TEST_PLOT_ROOT.format(version=__version__))
        ).resolve()
    return root_path / "plots"


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    def __init__(
        self, root_path: Path = TEST_ROOT_PATH, real_plots: bool = False,
    ):
        create_default_chia_config(root_path)
        initialize_ssl(root_path)
        self.root_path = root_path
        self.n_wesolowski = uint8(0)
        self.real_plots = real_plots

        if not real_plots:
            # No real plots supplied, so we will use the small test plots
            self.use_any_pos = True
            self.plot_config: Dict = {"plots": {}}
            # Can't go much lower than 19, since plots start having no solutions
            k: uint8 = uint8(19)
            # Uses many plots for testing, in order to guarantee proofs of space at every height
            num_plots = 40
            # Use the empty string as the seed for the private key

            self.keychain = Keychain("testing", True)
            self.keychain.delete_all_keys()
            self.keychain.add_private_key_seed(b"block_tools")
            pool_sk: PrivateKey = self.keychain.get_all_private_keys()[0][
                0
            ].get_private_key()
            pool_pk: PublicKey = pool_sk.get_public_key()

            plot_sks: List[PrivateKey] = [
                PrivateKey.from_seed(pn.to_bytes(4, "big")) for pn in range(num_plots)
            ]
            plot_pks: List[PublicKey] = [sk.get_public_key() for sk in plot_sks]

            plot_seeds: List[bytes32] = [
                ProofOfSpace.calculate_plot_seed(pool_pk, plot_pk)
                for plot_pk in plot_pks
            ]
            plot_dir = get_plot_dir(root_path)
            mkdir(plot_dir)
            filenames: List[str] = [
                f"genesis-plots-{k}{std_hash(int.to_bytes(i, 4, 'big')).hex()}.dat"
                for i in range(num_plots)
            ]
            done_filenames = set()
            temp_dir = plot_dir / "plot.tmp"
            mkdir(temp_dir)
            try:
                for pn, filename in enumerate(filenames):
                    if not (plot_dir / filename).exists():
                        plotter = DiskPlotter()
                        plotter.create_plot_disk(
                            str(plot_dir),
                            str(plot_dir),
                            str(plot_dir),
                            filename,
                            k,
                            b"genesis",
                            plot_seeds[pn],
                        )
                        done_filenames.add(filename)
                    self.plot_config["plots"][str(plot_dir / filename)] = {
                        "pool_pk": bytes(pool_pk).hex(),
                        "sk": bytes(plot_sks[pn]).hex(),
                        "pool_sk": bytes(pool_sk).hex(),
                    }
                save_config(self.root_path, "plots.yaml", self.plot_config)

            except KeyboardInterrupt:
                for filename in filenames:
                    if (
                        filename not in done_filenames
                        and (plot_dir / filename).exists()
                    ):
                        (plot_dir / filename).unlink()
                sys.exit(1)
        else:
            try:
                plot_config = load_config(DEFAULT_ROOT_PATH, "plots.yaml")
                normal_config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
            except FileNotFoundError:
                raise RuntimeError("Plots not generated. Run chia-create-plots")
            self.keychain = Keychain(testing=False)
            private_keys: List[PrivateKey] = [
                k.get_private_key() for (k, _) in self.keychain.get_all_private_keys()
            ]
            pool_pubkeys: List[PublicKey] = [sk.get_public_key() for sk in private_keys]
            if len(private_keys) == 0:
                raise RuntimeError("Keys not generated. Run `chia generate keys`")

            self.prover_dict, _, _ = load_plots(
                normal_config["harvester"], plot_config, pool_pubkeys, DEFAULT_ROOT_PATH
            )

            new_plot_config: Dict = {"plots": {}}
            for key, value in plot_config["plots"].items():
                for sk in private_keys:
                    if (
                        bytes(sk.get_public_key()).hex() == value["pool_pk"]
                        and key in self.prover_dict
                    ):
                        new_plot_config["plots"][key] = value
                        new_plot_config["plots"][key]["pool_sk"] = bytes(sk).hex()

            self.plot_config = new_plot_config
            self.use_any_pos = False
            a = self.plot_config["plots"]
            print(f"Using {len(a)} reals plots to initialize block_tools")

        private_key = self.keychain.get_all_private_keys()[0][0]
        self.fee_target = create_puzzlehash_for_pk(
            BLSPublicKey(bytes(private_key.public_child(1).get_public_key()))
        )

    def get_harvester_signature(self, header_data: HeaderData, plot_pk: PublicKey):
        for value_dict in self.plot_config["plots"].values():
            if (
                PrivateKey.from_bytes(bytes.fromhex(value_dict["sk"])).get_public_key()
                == plot_pk
            ):
                return PrivateKey.from_bytes(
                    bytes.fromhex(value_dict["sk"])
                ).sign_prepend(header_data.get_hash())

    def get_consecutive_blocks(
        self,
        input_constants: Dict,
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
        test_constants: Dict[str, Any] = constants.copy()
        for key, value in input_constants.items():
            test_constants[key] = value
        if seconds_per_block is None:
            seconds_per_block = test_constants["BLOCK_TIME_TARGET"]

        if len(block_list) == 0:
            if "GENESIS_BLOCK" in test_constants:
                block_list.append(FullBlock.from_bytes(test_constants["GENESIS_BLOCK"]))
            else:
                block_list.append(
                    self.create_genesis_block(test_constants, std_hash(seed), seed)
                )
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
        input_constants: Dict,
        challenge_hash=bytes([0] * 32),
        seed: bytes = b"",
        reward_puzzlehash: Optional[bytes32] = None,
    ) -> FullBlock:
        """
        Creates the genesis block with the specified details.
        """
        test_constants: Dict[str, Any] = constants.copy()
        for key, value in input_constants.items():
            test_constants[key] = value

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
        input_constants: Dict,
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
        test_constants: Dict[str, Any] = constants.copy()
        for key, value in input_constants.items():
            test_constants[key] = value
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
        test_constants: Dict,
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
        selected_prover = None
        selected_plot_sk = None
        selected_pool_sk = None
        selected_proof_index = 0
        plots = list(self.plot_config["plots"].items())
        selected_quality: Optional[bytes] = None
        best_quality = 0
        if self.use_any_pos:
            for i in range(len(plots) * 3):
                # Allow passing in seed, to create reorgs and different chains
                random.seed(seed + i.to_bytes(4, "big"))
                seeded_pn = random.randint(0, len(plots) - 1)
                pool_sk = PrivateKey.from_bytes(
                    bytes.fromhex(plots[seeded_pn][1]["pool_sk"])
                )
                plot_sk = PrivateKey.from_bytes(
                    bytes.fromhex(plots[seeded_pn][1]["sk"])
                )
                prover = DiskProver(plots[seeded_pn][0])
                qualities = prover.get_qualities_for_challenge(challenge_hash)
                if len(qualities) > 0:
                    if self.use_any_pos:
                        selected_quality = qualities[0]
                        selected_prover = prover
                        selected_pool_sk = pool_sk
                        selected_plot_sk = plot_sk
                        break
        else:
            for i in range(len(plots)):
                pool_sk = PrivateKey.from_bytes(bytes.fromhex(plots[i][1]["pool_sk"]))
                plot_sk = PrivateKey.from_bytes(bytes.fromhex(plots[i][1]["sk"]))
                try:
                    if self.real_plots:
                        prover = self.prover_dict[plots[i][0]]
                    else:
                        prover = DiskProver(plots[i][0])
                except (ValueError, KeyError) as e:
                    continue
                qualities = prover.get_qualities_for_challenge(challenge_hash)
                j = 0
                for quality in qualities:
                    qual_int = int.from_bytes(quality, "big", signed=False)
                    if qual_int > best_quality:
                        best_quality = qual_int
                        selected_quality = quality
                        selected_prover = prover
                        selected_pool_sk = pool_sk
                        selected_plot_sk = plot_sk
                        selected_proof_index = j
                    j += 1

        assert selected_prover
        assert selected_pool_sk
        assert selected_plot_sk
        pool_pk = selected_pool_sk.get_public_key()
        plot_pk = selected_plot_sk.get_public_key()
        if selected_quality is None:
            raise RuntimeError("No proofs for this challenge")

        proof_xs: bytes = selected_prover.get_full_proof(
            challenge_hash, selected_proof_index
        )
        proof_of_space: ProofOfSpace = ProofOfSpace(
            challenge_hash, pool_pk, plot_pk, selected_prover.get_size(), proof_xs
        )
        number_iters: uint64 = pot_iterations.calculate_iterations(
            proof_of_space, difficulty, min_iters
        )
        # print("Doing iters", number_iters)
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

        if not reward_puzzlehash:
            reward_puzzlehash = self.fee_target

        # Use the extension data to create different blocks based on header hash
        extension_data: bytes32 = bytes32([random.randint(0, 255) for _ in range(32)])
        cost = uint64(0)

        coinbase_reward = block_rewards.calculate_block_reward(height)
        fee_reward = uint64(block_rewards.calculate_base_fee(height) + fees)

        coinbase_coin, coinbase_signature = create_coinbase_coin_and_signature(
            height, reward_puzzlehash, coinbase_reward, selected_pool_sk
        )

        parent_coin_name = std_hash(std_hash(height))
        fees_coin = Coin(parent_coin_name, reward_puzzlehash, uint64(fee_reward))

        # Create filter
        byte_array_tx: List[bytes32] = []
        tx_additions: List[Coin] = []
        tx_removals: List[bytes32] = []
        encoded = None
        if transactions:
            error, npc_list, _ = get_name_puzzle_conditions(transactions)
            additions: List[Coin] = additions_for_npc(npc_list)
            for coin in additions:
                tx_additions.append(coin)
                byte_array_tx.append(bytearray(coin.puzzle_hash))
            for npc in npc_list:
                tx_removals.append(npc.coin_name)
                byte_array_tx.append(bytearray(npc.coin_name))

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
        removal_root = removal_merkle_set.get_root()

        generator_hash = (
            transactions.get_tree_hash()
            if transactions is not None
            else bytes32([0] * 32)
        )
        filter_hash = std_hash(encoded) if encoded is not None else bytes32([0] * 32)

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
            coinbase_coin,
            coinbase_signature,
            fees_coin,
            aggsig,
            cost,
            extension_data,
            generator_hash,
        )

        header_hash_sig: PrependSignature = selected_plot_sk.sign_prepend(
            header_data.get_hash()
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
    bt = BlockTools(real_plots=True)
    print(
        bytes(
            bt.create_genesis_block(
                {},
                bytes([2] * 32),
                b"0",
                bytes.fromhex(
                    "a4259182b4d8e0af21331fc5be2681f953400b6726fa4095e3b91ae8f005a836"
                ),
            )
        )
    )
