import random
from typing import Iterator

import pytest

from benchmarks.utils import rand_bytes, rand_g1, rand_g2, rand_hash, rand_vdf, rand_vdf_proof, rewards
from chia.types.blockchain_format.foliage import Foliage, FoliageBlockData, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.slots import (
    ChallengeChainSubSlot,
    InfusedChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.util.full_block_utils import generator_from_block
from chia.util.ints import uint8, uint32, uint64, uint128

test_g2s = [rand_g2() for _ in range(10)]
test_g1s = [rand_g1() for _ in range(10)]
test_hashes = [rand_hash() for _ in range(100)]
test_vdfs = [rand_vdf() for _ in range(100)]
test_vdf_proofs = [rand_vdf_proof() for _ in range(100)]


def g2():
    return random.sample(test_g2s, 1)[0]


def g1():
    return random.sample(test_g1s, 1)[0]


def hsh():
    return random.sample(test_hashes, 1)[0]


def vdf():
    return random.sample(test_vdfs, 1)[0]


def vdf_proof():
    return random.sample(test_vdf_proofs, 1)[0]


def get_proof_of_space():
    for pool_pk in [g1(), None]:
        for plot_hash in [hsh(), None]:
            yield ProofOfSpace(
                hsh(),  # challenge
                pool_pk,
                plot_hash,
                g1(),  # plot_public_key
                uint8(32),
                rand_bytes(8 * 32),
            )


def get_reward_chain_block(height):
    for has_transactions in [True, False]:
        for challenge_chain_sp_vdf in [vdf(), None]:
            for reward_chain_sp_vdf in [vdf(), None]:
                for infused_challenge_chain_ip_vdf in [vdf(), None]:
                    for proof_of_space in get_proof_of_space():
                        weight = uint128(random.randint(0, 1000000000))
                        iters = uint128(123456)
                        sp_index = uint8(0)
                        yield RewardChainBlock(
                            weight,
                            uint32(height),
                            iters,
                            sp_index,
                            hsh(),  # pos_ss_cc_challenge_hash
                            proof_of_space,
                            challenge_chain_sp_vdf,
                            g2(),  # challenge_chain_sp_signature
                            vdf(),  # challenge_chain_ip_vdf
                            reward_chain_sp_vdf,
                            g2(),  # reward_chain_sp_signature
                            vdf(),  # reward_chain_ip_vdf
                            infused_challenge_chain_ip_vdf,
                            has_transactions,
                        )


def get_foliage_block_data():
    for pool_signature in [g2(), None]:
        pool_target = PoolTarget(
            hsh(),  # puzzle_hash
            uint32(0),  # max_height
        )

        yield FoliageBlockData(
            hsh(),  # unfinished_reward_block_hash
            pool_target,
            pool_signature,  # pool_signature
            hsh(),  # farmer_reward_puzzle_hash
            hsh(),  # extension_data
        )


def get_foliage():
    for foliage_block_data in get_foliage_block_data():
        for foliage_transaction_block_hash in [hsh(), None]:
            for foliage_transaction_block_signature in [g2(), None]:
                yield Foliage(
                    hsh(),  # prev_block_hash
                    hsh(),  # reward_block_hash
                    foliage_block_data,
                    g2(),  # foliage_block_data_signature
                    foliage_transaction_block_hash,
                    foliage_transaction_block_signature,
                )


def get_foliage_transaction_block():
    yield None
    timestamp = uint64(1631794488)
    yield FoliageTransactionBlock(
        hsh(),  # prev_transaction_block
        timestamp,
        hsh(),  # filter_hash
        hsh(),  # additions_root
        hsh(),  # removals_root
        hsh(),  # transactions_info_hash
    )


def get_transactions_info(height):
    yield None
    farmer_coin, pool_coin = rewards(uint32(height))
    reward_claims_incorporated = [farmer_coin, pool_coin]
    fees = uint64(random.randint(0, 150000))

    yield TransactionsInfo(
        hsh(),  # generator_root
        hsh(),  # generator_refs_root
        g2(),  # aggregated_signature
        fees,
        uint64(random.randint(0, 12000000000)),  # cost
        reward_claims_incorporated,
    )


def get_challenge_chain_sub_slot():
    for infused_chain_sub_slot_hash in [hsh(), None]:
        for sub_epoch_summary_hash in [hsh(), None]:
            for new_sub_slot_iters in [uint64(random.randint(0, 4000000000)), None]:
                for new_difficulty in [uint64(random.randint(1, 30)), None]:
                    yield ChallengeChainSubSlot(
                        vdf(),  # challenge_chain_end_of_slot_vdf
                        infused_chain_sub_slot_hash,
                        sub_epoch_summary_hash,
                        new_sub_slot_iters,
                        new_difficulty,
                    )


def get_reward_chain_sub_slot():
    for infused_challenge_chain_sub_slot_hash in [hsh(), None]:
        yield RewardChainSubSlot(
            vdf(),  # end_of_slot_vdf
            hsh(),  # challenge_chain_sub_slot_hash
            infused_challenge_chain_sub_slot_hash,
            uint8(random.randint(0, 255)),  # deficit
        )


def get_sub_slot_proofs():
    for infused_challenge_chain_slot_proof in [vdf_proof(), None]:
        yield SubSlotProofs(
            vdf_proof(),  # challenge_chain_slot_proof
            infused_challenge_chain_slot_proof,
            vdf_proof(),  # reward_chain_slot_proof
        )


def get_end_of_sub_slot():
    for challenge_chain in get_challenge_chain_sub_slot():
        for infused_challenge_chain in [InfusedChallengeChainSubSlot(vdf()), None]:
            for reward_chain in get_reward_chain_sub_slot():
                for proofs in get_sub_slot_proofs():
                    yield EndOfSubSlotBundle(
                        challenge_chain,
                        infused_challenge_chain,
                        reward_chain,
                        proofs,
                    )


def get_finished_sub_slots():
    yield []
    yield [s for s in get_end_of_sub_slot()]


def get_full_blocks() -> Iterator[FullBlock]:

    random.seed(123456789)

    generator = SerializedProgram.from_bytes(bytes.fromhex("ff01820539"))

    for foliage in get_foliage():
        for foliage_transaction_block in get_foliage_transaction_block():
            height = random.randint(0, 1000000)
            for reward_chain_block in get_reward_chain_block(height):
                for transactions_info in get_transactions_info(height):
                    for challenge_chain_sp_proof in [vdf_proof(), None]:
                        for reward_chain_sp_proof in [vdf_proof(), None]:
                            for infused_challenge_chain_ip_proof in [vdf_proof(), None]:
                                for finished_sub_slots in get_finished_sub_slots():

                                    yield FullBlock(
                                        finished_sub_slots,
                                        reward_chain_block,
                                        challenge_chain_sp_proof,
                                        vdf_proof(),  # challenge_chain_ip_proof
                                        reward_chain_sp_proof,
                                        vdf_proof(),  # reward_chain_ip_proof
                                        infused_challenge_chain_ip_proof,
                                        foliage,
                                        foliage_transaction_block,
                                        transactions_info,
                                        generator,  # transactions_generator
                                        [],  # transactions_generator_ref_list
                                    )


class TestFullBlockParser:
    @pytest.mark.asyncio
    async def test_parser(self):

        # loop over every combination of Optionals being set and not set
        # along with random values for the FullBlock fields. Ensure
        # generator_from_block() successfully parses out the generator object
        # correctly
        for block in get_full_blocks():

            block_bytes = bytes(block)
            gen = generator_from_block(block_bytes)
            assert gen == block.transactions_generator
            # this doubles the run-time of this test, with questionable utility
            # assert gen == FullBlock.from_bytes(block_bytes).transactions_generator
