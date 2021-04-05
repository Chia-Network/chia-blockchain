# Based on this specification from Pieter Wuille:
# https://github.com/sipa/bips/blob/bip-bech32m/bip-bech32m.mediawiki

from chia.util.bech32m import bech32_decode


def test_valid_imports():
    test_strings = [
        "A1LQFN3A",
        "a1lqfn3a",
        "an83characterlonghumanreadablepartthatcontainsthetheexcludedcharactersbioandnumber11sg7hg6",
        "abcdef1l7aum6echk45nj3s0wdvt2fg8x9yrzpqzd3ryx",
        "11llllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllludsr8",
        "split1checkupstagehandshakeupstreamerranterredcaperredlc445v",
        "?1v759aa",
    ]
    for test_str in test_strings:
        hrp, data = bech32_decode(test_str)
        assert data is not None


def test_invalid_imports():
    test_strings = [
        f"{0x20}1xj0phk",
        f"{0x7F}1g6xzxy",
        f"{0x80}1vctc34",
        "an84characterslonghumanreadablepartthatcontainsthetheexcludedcharactersbioandnumber11d6pts4",
        "qyrz8wqd2c9m",
        "1qyrz8wqd2c9m",
        "y1b0jsk6g",
        "lt1igcx5c0",
        "in1muywd",
        "mm1crxm3i",
        "au1s5cgom",
        "M1VUXWEZ",
        "16plkw9",
        "1p2gdwpf",
    ]
    for test_str in test_strings:
        hrp, data = bech32_decode(test_str)
        assert data is None
