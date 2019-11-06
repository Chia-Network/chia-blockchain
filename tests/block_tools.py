import time
import os
import sys
from hashlib import sha256
from chiapos import DiskPlotter, DiskProver
from typing import List, Dict, Any
from blspy import PublicKey, PrivateKey, PrependSignature
from src.types.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.types.trunk_block import TrunkBlock
from src.types.block_body import BlockBody
from src.types.challenge import Challenge
from src.types.block_header import BlockHeader, BlockHeaderData
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime, ProofOfTimeOutput
from src.types.classgroup import ClassgroupElement
from src.consensus import pot_iterations, block_rewards
from src.util.ints import uint64, uint32, uint8
from src.util.errors import NoProofsOfSpaceFound
from src.types.coinbase import CoinbaseInfo
from src.types.fees_target import FeesTarget
from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from lib.chiavdf.inkfish.classgroup import ClassGroup
from lib.chiavdf.inkfish.proof_of_time import create_proof_of_time_nwesolowski
from src.consensus.constants import constants
from src.consensus.pot_iterations import calculate_ips_from_iterations


# Can't go much lower than 19, since plots start having no solutions
k: uint8 = uint8(19)
# Uses many plots for testing, in order to guarantee proofs of space at every height
num_plots = 80
# Use the empty string as the seed for the private key
pool_sk: PrivateKey = PrivateKey.from_seed(b'')
pool_pk: PublicKey = pool_sk.get_public_key()
plot_sks: List[PrivateKey] = [PrivateKey.from_seed(pn.to_bytes(4, "big")) for pn in range(num_plots)]
plot_pks: List[PublicKey] = [sk.get_public_key() for sk in plot_sks]

farmer_sk: PrivateKey = PrivateKey.from_seed(b'coinbase')
coinbase_target = sha256(bytes(farmer_sk.get_public_key())).digest()
fee_target = sha256(bytes(farmer_sk.get_public_key())).digest()
n_wesolowski = uint8(3)


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    def __init__(self):
        plot_seeds: List[bytes32] = [ProofOfSpace.calculate_plot_seed(pool_pk, plot_pk) for plot_pk in plot_pks]
        self.filenames: List[str] = [os.path.join("tests", "plots", "genesis-plots-" + str(k) +
                                                           sha256(int.to_bytes(i, 4, "big")).digest().hex() + ".dat")
                                     for i in range(num_plots)]
        done_filenames = set()
        try:
            for pn, filename in enumerate(self.filenames):
                if not os.path.exists(filename):
                    plotter = DiskPlotter()
                    plotter.create_plot_disk(filename, k, b"genesis", plot_seeds[pn])
                    done_filenames.add(filename)
        except KeyboardInterrupt:
            for filename in self.filenames:
                if filename not in done_filenames and os.path.exists(filename):
                    os.remove(filename)
            sys.exit(1)

    def get_consecutive_blocks(self,
                               input_constants: Dict,
                               num_blocks: int,
                               block_list: List[FullBlock] = [],
                               seconds_per_block=constants["BLOCK_TIME_TARGET"],
                               seed: bytes = b'') -> List[FullBlock]:
        test_constants: Dict[str, Any] = constants.copy()
        for key, value in input_constants.items():
            test_constants[key] = value

        if len(block_list) == 0:
            if "GENESIS_BLOCK" in test_constants:
                block_list.append(FullBlock.from_bytes(test_constants["GENESIS_BLOCK"]))
            else:
                block_list.append(self.create_genesis_block(test_constants, sha256(seed).digest(), seed))
            prev_difficulty = test_constants["DIFFICULTY_STARTING"]
            curr_difficulty = prev_difficulty
            curr_ips = test_constants["VDF_IPS_STARTING"]
        elif len(block_list) < (test_constants["DIFFICULTY_EPOCH"] + test_constants["DIFFICULTY_DELAY"]):
            # First epoch (+delay), so just get first difficulty
            prev_difficulty = block_list[0].weight
            curr_difficulty = block_list[0].weight
            assert test_constants["DIFFICULTY_STARTING"] == prev_difficulty
            curr_ips = test_constants["VDF_IPS_STARTING"]
        else:
            curr_difficulty = block_list[-1].weight - block_list[-2].weight
            prev_difficulty = (block_list[-1 - test_constants["DIFFICULTY_EPOCH"]].weight -
                               block_list[-2 - test_constants["DIFFICULTY_EPOCH"]].weight)
            assert block_list[-1].trunk_block.proof_of_time
            curr_ips = calculate_ips_from_iterations(block_list[-1].trunk_block.proof_of_space,
                                                     block_list[-1].trunk_block.proof_of_time.output.challenge_hash,
                                                     curr_difficulty,
                                                     block_list[-1].trunk_block.proof_of_time.output
                                                     .number_of_iterations,
                                                     test_constants["MIN_BLOCK_TIME"])

        starting_height = block_list[-1].height + 1
        timestamp = block_list[-1].trunk_block.header.data.timestamp
        for next_height in range(starting_height, starting_height + num_blocks):
            if (next_height > test_constants["DIFFICULTY_EPOCH"] and
                    next_height % test_constants["DIFFICULTY_EPOCH"] == test_constants["DIFFICULTY_DELAY"]):
                # Calculates new difficulty
                height1 = uint64(next_height - (test_constants["DIFFICULTY_EPOCH"] +
                                 test_constants["DIFFICULTY_DELAY"]) - 1)
                height2 = uint64(next_height - (test_constants["DIFFICULTY_EPOCH"]) - 1)
                height3 = uint64(next_height - (test_constants["DIFFICULTY_DELAY"]) - 1)
                if height1 >= 0:
                    block1 = block_list[height1]
                    assert block1.trunk_block.challenge
                    iters1 = block1.trunk_block.challenge.total_iters
                    timestamp1 = block1.trunk_block.header.data.timestamp
                else:
                    block1 = block_list[0]
                    assert block1.trunk_block.challenge
                    timestamp1 = (block1.trunk_block.header.data.timestamp -
                                  test_constants["BLOCK_TIME_TARGET"])
                    iters1 = block1.trunk_block.challenge.total_iters
                timestamp2 = block_list[height2].trunk_block.header.data.timestamp
                timestamp3 = block_list[height3].trunk_block.header.data.timestamp

                block3 = block_list[height3]
                assert block3.trunk_block.challenge
                iters3 = block3.trunk_block.challenge.total_iters
                term1 = (test_constants["DIFFICULTY_DELAY"] * prev_difficulty *
                         (timestamp3 - timestamp2) * test_constants["BLOCK_TIME_TARGET"])

                term2 = ((test_constants["DIFFICULTY_WARP_FACTOR"] - 1) *
                         (test_constants["DIFFICULTY_EPOCH"] - test_constants["DIFFICULTY_DELAY"]) * curr_difficulty
                         * (timestamp2 - timestamp1) * test_constants["BLOCK_TIME_TARGET"])

                # Round down after the division
                new_difficulty: uint64 = uint64((term1 + term2) //
                                                (test_constants["DIFFICULTY_WARP_FACTOR"] *
                                                (timestamp3 - timestamp2) *
                                                (timestamp2 - timestamp1)))

                if new_difficulty >= curr_difficulty:
                    new_difficulty = min(new_difficulty, uint64(test_constants["DIFFICULTY_FACTOR"] *
                                                                curr_difficulty))
                else:
                    new_difficulty = max([uint64(1), new_difficulty,
                                          uint64(curr_difficulty // test_constants["DIFFICULTY_FACTOR"])])

                new_ips = uint64((iters3 - iters1)//(timestamp3 - timestamp1))
                if new_ips >= curr_ips:
                    curr_ips = min(new_ips, uint64(test_constants["IPS_FACTOR"] * new_ips))
                else:
                    curr_ips = max([uint64(1), new_ips, uint64(curr_ips // test_constants["IPS_FACTOR"])])

                prev_difficulty = curr_difficulty
                curr_difficulty = new_difficulty
            time_taken = seconds_per_block
            timestamp += time_taken
            block_list.append(self.create_next_block(test_constants, block_list[-1], timestamp, curr_difficulty,
                                                     curr_ips, seed))
        return block_list

    def create_genesis_block(self, input_constants: Dict, challenge_hash=bytes([0]*32),
                             seed: bytes = b'') -> FullBlock:
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
            bytes([0]*32),
            uint64(0),
            uint64(0),
            uint64(int(time.time())),
            uint64(test_constants["DIFFICULTY_STARTING"]),
            uint64(test_constants["VDF_IPS_STARTING"]),
            seed
        )

    def create_next_block(self, input_constants: Dict, prev_block: FullBlock, timestamp: uint64,
                          difficulty: uint64, ips: uint64,
                          seed: bytes = b'') -> FullBlock:
        """
        Creates the next block with the specified details.
        """
        test_constants: Dict[str, Any] = constants.copy()
        for key, value in input_constants.items():
            test_constants[key] = value

        assert prev_block.trunk_block.challenge

        return self._create_block(
            test_constants,
            prev_block.trunk_block.challenge.get_hash(),
            uint32(prev_block.height + 1),
            prev_block.header_hash,
            prev_block.trunk_block.challenge.total_iters,
            prev_block.weight,
            timestamp,
            uint64(difficulty),
            ips,
            seed
        )

    def _create_block(self, test_constants: Dict, challenge_hash: bytes32, height: uint32, prev_header_hash: bytes32,
                      prev_iters: uint64, prev_weight: uint64, timestamp: uint64, difficulty: uint64,
                      ips: uint64, seed: bytes) -> FullBlock:
        """
        Creates a block with the specified details. Uses the stored plots to create a proof of space,
        and also evaluates the VDF for the proof of time.
        """
        prover = None
        plot_pk = None
        plot_sk = None
        qualities: List[bytes] = []
        for pn in range(num_plots):
            # Allow passing in seed, to create reorgs and different chains
            seeded_pn = (pn + 17 * int.from_bytes(seed, "big")) % num_plots
            filename = self.filenames[seeded_pn]
            plot_pk = plot_pks[seeded_pn]
            plot_sk = plot_sks[seeded_pn]
            prover = DiskProver(filename)
            qualities = prover.get_qualities_for_challenge(challenge_hash)
            if len(qualities) > 0:
                break

        assert prover
        assert plot_pk
        assert plot_sk
        if len(qualities) == 0:
            raise NoProofsOfSpaceFound("No proofs for this challenge")

        proof_xs: bytes = prover.get_full_proof(challenge_hash, 0)
        proof_of_space: ProofOfSpace = ProofOfSpace(pool_pk, plot_pk, k, [uint8(b) for b in proof_xs])
        number_iters: uint64 = pot_iterations.calculate_iterations(proof_of_space, challenge_hash,
                                                                   difficulty, ips,
                                                                   test_constants["MIN_BLOCK_TIME"])

        disc: int = create_discriminant(challenge_hash, test_constants["DISCRIMINANT_SIZE_BITS"])
        start_x: ClassGroup = ClassGroup.from_ab_discriminant(2, 1, disc)
        y_cl, proof_bytes = create_proof_of_time_nwesolowski(
            disc, start_x, number_iters, disc, n_wesolowski)

        output = ProofOfTimeOutput(challenge_hash, number_iters,
                                   ClassgroupElement(y_cl[0], y_cl[1]))

        proof_of_time = ProofOfTime(output, n_wesolowski, [uint8(b) for b in proof_bytes])

        coinbase: CoinbaseInfo = CoinbaseInfo(height, block_rewards.calculate_block_reward(uint32(height)),
                                              coinbase_target)
        coinbase_sig: PrependSignature = pool_sk.sign_prepend(bytes(coinbase))

        fees_target: FeesTarget = FeesTarget(fee_target, uint64(0))

        solutions_generator: bytes32 = sha256(seed).digest()
        body: BlockBody = BlockBody(coinbase, coinbase_sig, fees_target, None, solutions_generator)

        header_data: BlockHeaderData = BlockHeaderData(prev_header_hash, timestamp, bytes([0]*32),
                                                       proof_of_space.get_hash(), body.get_hash(),
                                                       bytes([0]*32), challenge_hash)

        header_hash_sig: PrependSignature = plot_sk.sign_prepend(header_data.get_hash())

        header: BlockHeader = BlockHeader(header_data, header_hash_sig)

        challenge = Challenge(proof_of_space.get_hash(), proof_of_time.get_hash(), height,
                              uint64(prev_weight + difficulty), uint64(prev_iters + number_iters))
        trunk_block = TrunkBlock(proof_of_space, proof_of_time, challenge, header)

        full_block: FullBlock = FullBlock(trunk_block, body)

        return full_block


# This code generates a genesis block, uncomment to output genesis block to terminal
# This might take a while, using the python VDF implementation.
# Run by doing python -m tests.block_tools
bt = BlockTools()
# print(bytes(bt.create_genesis_block({}, bytes([1]*32), b'0')))
print(bt.create_genesis_block({"DIFFICULTY_STARTING": 10}, bytes([1]*32), b'0'))
