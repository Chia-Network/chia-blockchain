from src.consensus.pot_iterations import (
    calculate_iterations_quality,
    is_overflow_sub_block,
    calculate_sub_slot_iters,
    calculate_sp_iters,
    calculate_ip_iters,
)
from src.consensus.pos_quality import _expected_plot_size
from src.util.ints import uint8, uint64
from src.util.hash import std_hash
from src.consensus.default_constants import DEFAULT_CONSTANTS
from pytest import raises

test_constants = DEFAULT_CONSTANTS.replace(
    **{
        "NUM_SPS_SUB_SLOT": 32,
        "SLOT_TIME_TARGET": 300,
    }
)


class TestPotIterations:
    def test_calculate_sub_slot_iters(self):
        ips: uint64 = uint64(100001)
        assert calculate_sub_slot_iters(test_constants, ips) == test_constants.SLOT_TIME_TARGET * ips

    def test_is_overflow_sub_block(self):
        assert not is_overflow_sub_block(test_constants, uint8(27))
        assert not is_overflow_sub_block(test_constants, uint8(28))
        assert is_overflow_sub_block(test_constants, uint8(29))
        assert is_overflow_sub_block(test_constants, uint8(30))
        assert is_overflow_sub_block(test_constants, uint8(31))
        with raises(ValueError):
            assert is_overflow_sub_block(test_constants, uint8(32))

    def test_calculate_sp_iters(self):
        ips: uint64 = uint64(100001)
        with raises(ValueError):
            calculate_sp_iters(test_constants, ips, uint8(32))
        calculate_sp_iters(test_constants, ips, uint8(31))

    def test_calculate_ip_iters(self):
        ips: uint64 = uint64(100001)
        sp_interval_iters = test_constants.SLOT_TIME_TARGET * ips // test_constants.NUM_SPS_SUB_SLOT

        with raises(ValueError):
            # Invalid signage point index
            calculate_ip_iters(test_constants, ips, uint8(123), uint64(100000))

        sp_iters = sp_interval_iters * 13

        with raises(ValueError):
            # required_iters too high
            calculate_ip_iters(test_constants, ips, sp_interval_iters, sp_interval_iters)

        with raises(ValueError):
            # required_iters too high
            calculate_ip_iters(test_constants, ips, sp_interval_iters, sp_interval_iters * 12)

        with raises(ValueError):
            # required_iters too low (0)
            calculate_ip_iters(test_constants, ips, sp_interval_iters, uint64(0))

        required_iters = sp_interval_iters - 1
        ip_iters = calculate_ip_iters(test_constants, ips, uint8(13), required_iters)
        print(sp_iters, sp_interval_iters, required_iters)
        assert ip_iters == sp_iters + test_constants.NUM_SP_INTERVALS_EXTRA * sp_interval_iters + required_iters

        required_iters = uint64(1)
        ip_iters = calculate_ip_iters(test_constants, ips, uint8(13), required_iters)
        assert ip_iters == sp_iters + test_constants.NUM_SP_INTERVALS_EXTRA * sp_interval_iters + required_iters

        required_iters = ips * 4
        ip_iters = calculate_ip_iters(test_constants, ips, uint8(13), required_iters)
        assert ip_iters == sp_iters + test_constants.NUM_SP_INTERVALS_EXTRA * sp_interval_iters + required_iters
        assert sp_iters < ip_iters

        # Overflow
        sp_iters = sp_interval_iters * (test_constants.NUM_SPS_SUB_SLOT - 1)
        ip_iters = calculate_ip_iters(test_constants, ips, uint8(test_constants.NUM_SPS_SUB_SLOT - 1), required_iters)
        assert ip_iters == (
            sp_iters + test_constants.NUM_SP_INTERVALS_EXTRA * sp_interval_iters + required_iters
        ) % calculate_sub_slot_iters(test_constants, ips)
        assert sp_iters > ip_iters

    def test_win_percentage(self):
        """
        Tests that the percentage of blocks won is proportional to the space of each farmer,
        with the assumption that all farmers have access to the same VDF speed.
        """
        farmer_ks = {
            uint8(32): 200,
            uint8(33): 200,
            uint8(34): 100,
            uint8(35): 100,
            uint8(36): 100,
        }
        farmer_space = {k: _expected_plot_size(uint8(k)) * count for k, count in farmer_ks.items()}
        total_space = sum(farmer_space.values())
        percentage_space = {k: float(sp / total_space) for k, sp in farmer_space.items()}
        wins = {k: 0 for k in farmer_ks.keys()}
        total_slots = 400
        num_sps = 16
        sp_interval_iters = uint64(100000000 // 32)
        difficulty = uint64(500000000000)

        for slot_index in range(total_slots):
            total_wins_in_slot = 0
            for sp_index in range(num_sps):
                sp_hash = std_hash(slot_index.to_bytes(4, "big") + sp_index.to_bytes(4, "big"))
                for k, count in farmer_ks.items():
                    for farmer_index in range(count):
                        quality = std_hash(slot_index.to_bytes(4, "big") + k.to_bytes(1, "big") + bytes(farmer_index))
                        required_iters = calculate_iterations_quality(quality, k, difficulty, sp_hash)
                        if required_iters < sp_interval_iters:
                            wins[k] += 1
                            total_wins_in_slot += 1
            print(total_wins_in_slot)

        win_percentage = {k: wins[k] / sum(wins.values()) for k in farmer_ks.keys()}
        print(win_percentage)
        print(percentage_space)
        for k in farmer_ks.keys():
            # Win rate is proportional to percentage of space
            assert abs(win_percentage[k] - percentage_space[k]) < 0.01
