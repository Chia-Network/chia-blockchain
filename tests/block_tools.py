import time
import os
import sys
from hashlib import sha256
from chiapos import DiskPlotter, DiskProver
from typing import List
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
k = 19
# Uses many plots for testing, in order to guarantee proofs of space at every height
num_plots = 80
# Use the empty string as the seed for the private key
pool_sk: PrivateKey = PrivateKey.from_seed(b'')
pool_pk: PublicKey = pool_sk.get_public_key()
plot_sks: List[PrivateKey] = [PrivateKey.from_seed(pn.to_bytes(4, "big")) for pn in range(num_plots)]
plot_pks: List[PublicKey] = [sk.get_public_key() for sk in plot_sks]

farmer_sk: PrivateKey = PrivateKey.from_seed(b'coinbase')
coinbase_target = sha256(farmer_sk.get_public_key().serialize()).digest()
fee_target = sha256(farmer_sk.get_public_key().serialize()).digest()
n_wesolowski = 3


class BlockTools:
    """
    Tools to generate blocks for testing.
    """

    def __init__(self):
        plot_seeds: List[bytes32] = [ProofOfSpace.calculate_plot_seed(pool_pk, plot_pk) for plot_pk in plot_pks]
        self.filenames: List[str] = [os.path.join("tests", "plots", "genesis-plots-" + str(k) +
                                                           sha256(int.to_bytes(i, 4, "big")).digest().hex() + ".dat")
                                     for i in range(num_plots)]

        try:
            for pn, filename in enumerate(self.filenames):
                if not os.path.exists(filename):
                    plotter = DiskPlotter()
                    plotter.create_plot_disk(filename, k, b"genesis", plot_seeds[pn])
        except KeyboardInterrupt:
            for filename in self.filenames:
                if os.path.exists(filename):
                    os.remove(filename)
            sys.exit(1)

    def get_consecutive_blocks(self,
                               num_blocks: int,
                               difficulty=constants["DIFFICULTY_STARTING"],
                               discriminant_size=constants["DISCRIMINANT_SIZE_BITS"],
                               seconds_per_block=constants["BLOCK_TIME_TARGET"],
                               block_list: List[FullBlock] = [],
                               seed: int = 0) -> List[FullBlock]:
        if len(block_list) == 0:
            block_list.append(self.create_genesis_block(bytes([(seed) % 256]*32),
                                                        difficulty,
                                                        discriminant_size,
                                                        seed))
            prev_difficulty = difficulty
            curr_difficulty = difficulty
            curr_ips = constants["VDF_IPS_STARTING"]
        elif len(block_list) < (constants["DIFFICULTY_EPOCH"] + constants["DIFFICULTY_DELAY"]):
            # First epoch (+delay), so just get first difficulty
            prev_difficulty = block_list[0].weight
            curr_difficulty = block_list[0].weight
            assert difficulty == prev_difficulty
            curr_ips = constants["VDF_IPS_STARTING"]
        else:
            curr_difficulty = block_list[-1].weight - block_list[-2].weight
            prev_difficulty = (block_list[-1 - constants["DIFFICULTY_EPOCH"]].weight -
                               block_list[-2 - constants["DIFFICULTY_EPOCH"]].weight)
            curr_ips = calculate_ips_from_iterations(block_list[-1].trunk_block.proof_of_space,
                                                     block_list[-1].trunk_block.proof_of_time.output.challenge_hash,
                                                     curr_difficulty,
                                                     block_list[-1].trunk_block.proof_of_time.output
                                                     .number_of_iterations)

        starting_height = block_list[-1].height + 1
        timestamp = block_list[-1].trunk_block.header.data.timestamp
        for next_height in range(starting_height, starting_height + num_blocks):
            if (next_height > constants["DIFFICULTY_EPOCH"] and
                    next_height % constants["DIFFICULTY_EPOCH"] == constants["DIFFICULTY_DELAY"]):
                # Calculates new difficulty
                height1 = uint64(next_height - (constants["DIFFICULTY_EPOCH"] +
                                 constants["DIFFICULTY_DELAY"]) - 1)
                height2 = uint64(next_height - (constants["DIFFICULTY_EPOCH"]) - 1)
                height3 = uint64(next_height - (constants["DIFFICULTY_DELAY"]) - 1)
                if height1 >= 0:
                    timestamp1 = block_list[height1].trunk_block.header.data.timestamp
                    iters1 = block_list[height1].trunk_block.challenge.total_iters
                else:
                    timestamp1 = (block_list[0].trunk_block.header.data.timestamp -
                                  constants["BLOCK_TIME_TARGET"])
                    iters1 = block_list[0].trunk_block.challenge.total_iters
                timestamp2 = block_list[height2].trunk_block.header.data.timestamp
                timestamp3 = block_list[height3].trunk_block.header.data.timestamp
                iters3 = block_list[height3].trunk_block.challenge.total_iters
                term1 = (constants["DIFFICULTY_DELAY"] * prev_difficulty *
                         (timestamp3 - timestamp2) * constants["BLOCK_TIME_TARGET"])

                term2 = ((constants["DIFFICULTY_WARP_FACTOR"] - 1) *
                         (constants["DIFFICULTY_EPOCH"] - constants["DIFFICULTY_DELAY"]) * curr_difficulty
                         * (timestamp2 - timestamp1) * constants["BLOCK_TIME_TARGET"])

                # Round down after the division
                new_difficulty: uint64 = uint64((term1 + term2) //
                                                (constants["DIFFICULTY_WARP_FACTOR"] *
                                                (timestamp3 - timestamp2) *
                                                (timestamp2 - timestamp1)))

                if new_difficulty >= curr_difficulty:
                    new_difficulty = min(new_difficulty, uint64(constants["DIFFICULTY_FACTOR"] *
                                                                curr_difficulty))
                else:
                    new_difficulty = max([uint64(1), new_difficulty,
                                          uint64(curr_difficulty // constants["DIFFICULTY_FACTOR"])])

                prev_difficulty = curr_difficulty
                curr_difficulty = new_difficulty
                curr_ips = uint64((iters3 - iters1)//(timestamp3 - timestamp1))
                print(f"Changing IPS {next_height} to {curr_ips} and diff {new_difficulty}")
            print(f"Curr ips: {curr_ips}")
            time_taken = seconds_per_block
            timestamp += time_taken
            block_list.append(self.create_next_block(block_list[-1], timestamp, curr_difficulty,
                                                     curr_ips, discriminant_size, seed))
        return block_list

    def create_genesis_block(self, challenge_hash=bytes([0]*32), difficulty=constants["DIFFICULTY_STARTING"],
                             discriminant_size=constants["DISCRIMINANT_SIZE_BITS"], seed: int = 0) -> FullBlock:
        """
        Creates the genesis block with the specified details.
        """
        return self._create_block(
            challenge_hash,
            uint32(0),
            bytes([0]*32),
            uint64(0),
            uint64(0),
            uint64(time.time()),
            uint64(difficulty),
            constants["VDF_IPS_STARTING"],
            discriminant_size,
            seed
        )

    def create_next_block(self, prev_block: FullBlock, timestamp: uint64,
                          difficulty=constants["DIFFICULTY_STARTING"],
                          ips=constants["VDF_IPS_STARTING"],
                          discriminant_size=constants["DISCRIMINANT_SIZE_BITS"],
                          seed: int = 0) -> FullBlock:
        """
        Creates the next block with the specified details.
        """
        return self._create_block(
            prev_block.trunk_block.challenge.get_hash(),
            prev_block.height + 1,
            prev_block.header_hash,
            prev_block.trunk_block.challenge.total_iters,
            prev_block.weight,
            timestamp,
            uint64(difficulty),
            ips,
            discriminant_size,
            seed
        )

    def _create_block(self, challenge_hash: bytes32, height: uint32, prev_header_hash: bytes32,
                      prev_iters: uint64, prev_weight: uint64, timestamp: uint64, difficulty: uint64,
                      ips: uint64, discriminant_size: uint64, seed: int = 0) -> FullBlock:
        """
        Creates a block with the specified details. Uses the stored plots to create a proof of space,
        and also evaluates the VDF for the proof of time.
        """
        prover = None
        plot_pk = None
        plot_sk = None
        qualities = []
        for pn in range(num_plots):
            seeded_pn = (pn + 17 * seed) % num_plots  # Allow passing in seed, to create reorgs and different chains
            filename = self.filenames[seeded_pn]
            plot_pk = plot_pks[seeded_pn]
            plot_sk = plot_sks[seeded_pn]
            prover = DiskProver(filename)
            qualities = prover.get_qualities_for_challenge(challenge_hash)
            if len(qualities) > 0:
                break

        if len(qualities) == 0:
            raise NoProofsOfSpaceFound("No proofs for this challenge")

        proof_xs: bytes = prover.get_full_proof(challenge_hash, 0)
        proof_of_space: ProofOfSpace = ProofOfSpace(pool_pk, plot_pk, k, list(proof_xs))

        number_iters: uint64 = pot_iterations.calculate_iterations(proof_of_space, challenge_hash,
                                                                   difficulty, ips)
        disc: int = create_discriminant(challenge_hash, discriminant_size)
        start_x: ClassGroup = ClassGroup.from_ab_discriminant(2, 1, disc)
        y_cl, proof_bytes = create_proof_of_time_nwesolowski(
            disc, start_x, number_iters, disc, n_wesolowski)

        output = ProofOfTimeOutput(challenge_hash, number_iters,
                                   ClassgroupElement(y_cl[0], y_cl[1]))

        proof_of_time = ProofOfTime(output, n_wesolowski, [uint8(b) for b in proof_bytes])

        coinbase: CoinbaseInfo = CoinbaseInfo(height, block_rewards.calculate_block_reward(uint32(height)),
                                              coinbase_target)
        coinbase_sig: PrependSignature = pool_sk.sign_prepend(coinbase.serialize())

        fees_target: FeesTarget = FeesTarget(fee_target, 0)

        body: BlockBody = BlockBody(coinbase, coinbase_sig, fees_target, None, bytes([0]*32))

        header_data: BlockHeaderData = BlockHeaderData(prev_header_hash, timestamp, bytes([0]*32),
                                                       proof_of_space.get_hash(), body.get_hash(),
                                                       bytes([0]*32))

        header_hash_sig: PrependSignature = plot_sk.sign_prepend(header_data.get_hash())

        header: BlockHeader = BlockHeader(header_data, header_hash_sig)

        challenge = Challenge(proof_of_space.get_hash(), proof_of_time.get_hash(), height,
                              prev_weight + difficulty, prev_iters + number_iters)
        trunk_block = TrunkBlock(proof_of_space, proof_of_time, challenge, header)

        full_block: FullBlock = FullBlock(trunk_block, body)

        return full_block


# This code generates a genesis block, uncomment to output genesis block to terminal
# bt = BlockTools()
# print(bt.create_genesis_block(bytes([4]*32)).serialize())
