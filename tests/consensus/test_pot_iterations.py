from src.consensus.pot_iterations import calculate_iterations_quality
from src.consensus.pos_quality import _expected_plot_size
from src.util.ints import uint8, uint64
from src.util.hash import std_hash


class TestPotIterations:
    def test_win_percentage(self):
        """
        Tests that the percentage of blocks won is proportional to the space of each farmer,
        with the assumption that all farmers have access to the same VDF speed.
        """
        farmer_ks = [
            uint8(34),
            uint8(35),
            uint8(36),
            uint8(37),
            uint8(38),
            uint8(39),
            uint8(39),
            uint8(39),
            uint8(39),
            uint8(39),
            uint8(40),
            uint8(41),
        ]
        farmer_space = [_expected_plot_size(uint8(k)) for k in farmer_ks]
        total_space = sum(farmer_space)
        percentage_space = [float(sp / total_space) for sp in farmer_space]
        wins = [0 for _ in range(len(farmer_ks))]
        total_blocks = 5000

        for b_index in range(total_blocks):
            qualities = [
                std_hash(b_index.to_bytes(32, "big") + bytes(farmer_index))
                for farmer_index in range(len(farmer_ks))
            ]
            iters = [
                calculate_iterations_quality(
                    qualities[i], farmer_ks[i], uint64(50000000), uint64(5000 * 30),
                )
                for i in range(len(qualities))
            ]
            wins[iters.index(min(iters))] += 1

        win_percentage = [wins[w] / total_blocks for w in range(len(farmer_ks))]
        for i in range(len(percentage_space)):
            # Win rate is proportional to percentage of space
            assert abs(win_percentage[i] - percentage_space[i]) < 0.01
