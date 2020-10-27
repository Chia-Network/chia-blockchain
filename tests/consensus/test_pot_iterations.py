from src.consensus.pot_iterations import (
    calculate_iterations_quality,
    is_overflow_sub_block,
    calculate_slot_iters,
    calculate_icp_iters,
    calculate_ip_iters,
)
from src.consensus.pos_quality import _expected_plot_size
from src.util.ints import uint8, uint64
from src.util.hash import std_hash
from src.consensus.constants import constants
from pytest import raises

test_constants = constants.replace(
    **{"EXTRA_ITERS_TIME_TARGET": 37.5, "NUM_CHECKPOINTS_PER_SLOT": 32, "SLOT_TIME_TARGET": 300}
)


class TestPotIterations:
    def test_calculate_slot_iters(self):
        ips: uint64 = uint64(100001)
        assert calculate_slot_iters(constants, ips) == test_constants.SLOT_TIME_TARGET * ips

    def test_is_overflow_sub_block(self):
        ips: uint64 = uint64(100001)
        with raises(ValueError):
            assert is_overflow_sub_block(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips + 1))
        with raises(ValueError):
            assert is_overflow_sub_block(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips))

        assert is_overflow_sub_block(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips - 1))

        assert is_overflow_sub_block(
            constants,
            ips,
            uint64(test_constants.SLOT_TIME_TARGET * ips - int(test_constants.EXTRA_ITERS_TIME_TARGET * ips)),
        )
        assert not is_overflow_sub_block(
            constants,
            ips,
            uint64(test_constants.SLOT_TIME_TARGET * ips - int(test_constants.EXTRA_ITERS_TIME_TARGET * ips) - 1),
        )
        assert not is_overflow_sub_block(constants, ips, uint64(0))

    def test_calculate_icp_iters(self):
        ips: uint64 = uint64(100001)
        with raises(ValueError):
            calculate_icp_iters(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips + 1))
        with raises(ValueError):
            calculate_icp_iters(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips))
        one_checkpoint_iters = test_constants.SLOT_TIME_TARGET * ips // 32
        assert (
            calculate_icp_iters(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips - 1))
            == 31 * one_checkpoint_iters
        )
        assert calculate_icp_iters(constants, ips, uint64(20 * one_checkpoint_iters)) == 20 * one_checkpoint_iters
        assert calculate_icp_iters(constants, ips, uint64(20 * one_checkpoint_iters) - 1) == 19 * one_checkpoint_iters
        assert calculate_icp_iters(constants, ips, uint64(20 * one_checkpoint_iters) + 1) == 20 * one_checkpoint_iters
        assert calculate_icp_iters(constants, ips, uint64(1)) == 0 * one_checkpoint_iters
        assert calculate_icp_iters(constants, ips, uint64(0)) == 0 * one_checkpoint_iters

    def test_calculate_ip_iters(self):
        ips: uint64 = uint64(100001)
        extra_iters = int(test_constants.EXTRA_ITERS_TIME_TARGET * int(ips))
        one_checkpoint_iters = test_constants.SLOT_TIME_TARGET * ips // test_constants.NUM_CHECKPOINTS_PER_SLOT
        with raises(ValueError):
            calculate_ip_iters(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips + 1))
        with raises(ValueError):
            calculate_ip_iters(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips))

        assert calculate_ip_iters(constants, ips, uint64(test_constants.SLOT_TIME_TARGET * ips - 1)) == (
            (test_constants.SLOT_TIME_TARGET * ips - 1) + extra_iters
        ) - (test_constants.SLOT_TIME_TARGET * ips)
        assert (
            calculate_ip_iters(constants, ips, uint64(5 * one_checkpoint_iters))
            == 5 * one_checkpoint_iters + extra_iters
        )
        assert (
            calculate_ip_iters(constants, ips, uint64(5 * one_checkpoint_iters + 678))
            == 5 * one_checkpoint_iters + extra_iters + 678
        )
        assert (
            calculate_ip_iters(constants, ips, uint64(5 * one_checkpoint_iters - 567))
            == 5 * one_checkpoint_iters + extra_iters - 567
        )
        assert calculate_ip_iters(constants, ips, uint64(0)) == extra_iters
        assert calculate_ip_iters(constants, ips, uint64(1)) == extra_iters + 1

    def test_win_percentage(self):
        """
        Tests that the percentage of blocks won is proportional to the space of each farmer,
        with the assumption that all farmers have access to the same VDF speed.
        """
        farmer_ks = {
            uint8(32): 300,
            uint8(33): 100,
            uint8(34): 100,
            uint8(35): 100,
            uint8(36): 50,
        }
        farmer_space = {k: _expected_plot_size(uint8(k)) * count for k, count in farmer_ks.items()}
        total_space = sum(farmer_space.values())
        percentage_space = {k: float(sp / total_space) for k, sp in farmer_space.items()}
        wins = {k: 0 for k in farmer_ks.keys()}
        total_slots = 500
        slot_iters = uint64(100000000)
        difficulty = uint64(500000000000)

        for slot_index in range(total_slots):
            total_wins_in_slot = 0
            for k, count in farmer_ks.items():
                for farmer_index in range(count):
                    quality = std_hash(slot_index.to_bytes(32, "big") + bytes(farmer_index))
                    required_iters = calculate_iterations_quality(
                        quality,
                        k,
                        difficulty,
                    )
                    if required_iters < slot_iters:
                        wins[k] += 1
                        total_wins_in_slot += 1

        win_percentage = {k: wins[k] / sum(wins.values()) for k in farmer_ks.keys()}
        for k in farmer_ks.keys():
            # Win rate is proportional to percentage of space
            assert abs(win_percentage[k] - percentage_space[k]) < 0.01
