from __future__ import annotations

from typing import List

import pytest

from chia.types.blockchain_format.proof_of_space import get_plot_id, passes_plot_filter
from chia.types.full_block import FullBlock
from chia.util.ints import uint8


@pytest.mark.parametrize("filter_prefix_bits, should_pass", [(9, 33), (8, 66), (7, 138), (6, 265), (5, 607)])
def test_filter_prefix_bits_on_blocks(
    default_10000_blocks: List[FullBlock], filter_prefix_bits: uint8, should_pass: int
) -> None:
    passed = 0
    for block in default_10000_blocks:
        plot_id = get_plot_id(block.reward_chain_block.proof_of_space)
        original_challenge_hash = block.reward_chain_block.pos_ss_cc_challenge_hash
        if block.reward_chain_block.challenge_chain_sp_vdf is None:
            assert block.reward_chain_block.signage_point_index == 0
            signage_point = original_challenge_hash
        else:
            signage_point = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
        if passes_plot_filter(filter_prefix_bits, plot_id, original_challenge_hash, signage_point):
            passed += 1
    assert passed == should_pass
