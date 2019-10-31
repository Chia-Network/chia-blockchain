from math import log
from decimal import Decimal
from hashlib import sha256
from src.util.ints import uint8, uint64
from src.consensus.pot_iterations import _quality_to_decimal, _expected_plot_size, calculate_iterations_quality


class TestPotIterations():
    def test_pade_approximation(self):
        def test_approximation(input_dec, threshold):
            bytes_input = int(Decimal(input_dec) * pow(2, 256)).to_bytes(32, "big")
            print(_quality_to_decimal(bytes_input))
            assert abs(1 - Decimal(-log(input_dec)) / _quality_to_decimal(bytes_input)) < threshold

        # The approximations become better the closer to 1 the input gets
        test_approximation(0.7, 0.01)
        test_approximation(0.9, 0.001)
        test_approximation(0.99, 0.00001)
        test_approximation(0.9999, 0.0000001)
        test_approximation(0.99999999, 0.0000000001)

    def test_win_percentage(self):
        """
        Tests that the percentage of blocks won is proportional to the space of each farmer,
        with the assumption that all farmers have access to the same VDF speed.
        """
        farmer_ks = [uint8(34), uint8(35), uint8(36), uint8(37), uint8(38), uint8(39), uint8(39),
                     uint8(39), uint8(39), uint8(39), uint8(40), uint8(41)]
        farmer_space = [_expected_plot_size(uint8(k)) for k in farmer_ks]
        total_space = sum(farmer_space)
        percentage_space = [float(sp / total_space) for sp in farmer_space]
        wins = [0 for _ in range(len(farmer_ks))]
        total_blocks = 5000

        for b_index in range(total_blocks):
            qualities = [sha256(b_index.to_bytes(32, "big") + bytes(farmer_index)).digest()
                         for farmer_index in range(len(farmer_ks))]
            iters = [calculate_iterations_quality(qualities[i], farmer_ks[i], uint64(50000000),
                                                  uint64(5000), uint64(10))
                     for i in range(len(qualities))]
            wins[iters.index(min(iters))] += 1

        win_percentage = [wins[w] / total_blocks for w in range(len(farmer_ks))]
        for i in range(len(percentage_space)):
            # Win rate is proportional to percentage of space
            assert abs(win_percentage[i] - percentage_space[i]) < 0.01
