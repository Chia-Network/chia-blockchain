from __future__ import annotations

import cProfile
from contextlib import contextmanager
from typing import Iterator

import pytest

from chia.wallet.trading.offer import Offer
from tests.util.misc import assert_runtime

with_profile = False

# gprof2dot -f pstats offer-parsing.profile >p.dot && dot -Tpng p.dot >offer-parsing.png
# gprof2dot -f pstats offered-coins.profile >c.dot && dot -Tpng c.dot >offered-coins.png


@contextmanager
def enable_profiler(name: str) -> Iterator[None]:
    if not with_profile:
        yield
        return

    with cProfile.Profile() as pr:
        yield

    pr.create_stats()
    pr.dump_stats(f"{name}.profile")


@pytest.mark.benchmark
def test_offer_parsing_performance() -> None:

    offer_bytes = bytes.fromhex(test_offer)
    with assert_runtime(seconds=2, label="Offer.from_bytes()"):
        with enable_profiler("offer-parsing"):
            for _ in range(100):
                o = Offer.from_bytes(offer_bytes)
                assert o is not None


@pytest.mark.benchmark
def test_offered_coins_performance() -> None:

    offer_bytes = bytes.fromhex(test_offer)
    o = Offer.from_bytes(offer_bytes)
    with assert_runtime(seconds=2.5, label="Offer.from_bytes()"):
        with enable_profiler("offered-coins"):
            for _ in range(100):
                c = o.get_offered_coins()
                assert len(c.items()) > 0


test_offer = str(
    "0000000200000000000000000000000000000000000000000000000000000000"
    "00000000bae24162efbd568f89bc7a340798a6118df0189eb9e3f8697bcea27a"
    "f99f8f790000000000000000ff02ffff01ff02ff0affff04ff02ffff04ff03ff"
    "80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0c"
    "ffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16"
    "ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff808080"
    "80ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff04ffff04ff08"
    "ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff"
    "010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1eff"
    "ff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080"
    "808080ffff01ff0bffff0101ff058080ff0180ff018080ffffa0113e4b68cb75"
    "5a6e4347f4d93e3d942ad1d89aadef6536dad229fe5fbe6ab232ffffa0e13f56"
    "72075e5ac9a50bcf080fca54762b2a59e22f37951f56802603ec2fe6e1ff64ff"
    "80808080ee2b6845e1c317976b002adc4d1dc48d2b752b9f47a3c1ecad4df36a"
    "2905d5add1ee4d5798f94b10f9487e314a9561a7a757d2fcf29d8d461106f04b"
    "8e303b790000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2f"
    "ff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff"
    "04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02"
    "ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff"
    "02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff01"
    "80ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080"
    "ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff"
    "02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ff"
    "ff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01"
    "ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff"
    "0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff"
    "8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ff"
    "ff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080"
    "ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01"
    "ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff"
    "03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02"
    "ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01"
    "ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff"
    "04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080"
    "ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080"
    "8080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02"
    "ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02"
    "ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff"
    "09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff"
    "0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff"
    "0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04"
    "ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ff"
    "ff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff8080"
    "8080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101"
    "ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff"
    "30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa0"
    "7faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9f"
    "ffa02268aba6ee7b6a26b6f8abc2c00938e413a8aa128d1ba1bdc4a9bfb84e62"
    "aa2da0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cd"
    "c13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff"
    "05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff"
    "17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffff"
    "ff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff"
    "04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0b"
    "ff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080"
    "ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ff"
    "ff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff"
    "04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03"
    "ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80"
    "808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff01"
    "01ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ff"
    "ff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff"
    "01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff"
    "04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02"
    "ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5f"
    "ff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e8"
    "80ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff"
    "ff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff"
    "82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fff"
    "ff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080"
    "808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff"
    "04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ff"
    "ff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27"
    "ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818f"
    "ff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af"
    "8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d8002"
    "6e870519aaa66334aef8304f5d0393c2ffff04ffff01ffff75ff9d6874747073"
    "3a2f2f70696373756d2e70686f746f732f3337372f38313180ffff68a0452062"
    "a44018653e22198e70a0e756641361b8ec3bc466c1924a38d372e1a945ffff82"
    "6d75ff9668747470733a2f2f7777772e6d656a69612e636f6d2f80ffff826c75"
    "ff93687474703a2f2f616775697272652e6e65742f80ffff82736e01ffff8273"
    "7401ffff826d68a01f462ea72e639eca6ebe792caeb296491177454fe2c763cb"
    "9b08e52e85c02712ffff826c68a0b794d0dfa36ac60ff17b0b3649adbc44a703"
    "8713bf8acfeaf4bb57dd276dd7ec80ffff04ffff01a0fe8a4b4e27a2e29a4d3f"
    "c7ce9d527adbcaccbab6ada3903ccf3ba9a769d2d78bffff04ffff01ff02ffff"
    "01ff02ffff01ff02ff26ffff04ff02ffff04ff05ffff04ff17ffff04ff0bffff"
    "04ffff02ff2fff5f80ff80808080808080ffff04ffff01ffffff82ad4cff0233"
    "ffff3e04ff81f601ffffff0102ffff02ffff03ff05ffff01ff02ff2affff04ff"
    "02ffff04ff0dffff04ffff0bff32ffff0bff3cff3480ffff0bff32ffff0bff32"
    "ffff0bff3cff2280ff0980ffff0bff32ff0bffff0bff3cff8080808080ff8080"
    "808080ffff010b80ff0180ff04ffff04ff38ffff04ffff02ff36ffff04ff02ff"
    "ff04ff05ffff04ff27ffff04ffff02ff2effff04ff02ffff04ffff02ffff03ff"
    "81afffff0181afffff010b80ff0180ff80808080ffff04ffff0bff3cff4f80ff"
    "ff04ffff0bff3cff0580ff8080808080808080ff378080ff82016f80ffffff02"
    "ff3effff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff2fffff04ff2f"
    "ffff01ff80ff808080808080808080ff0bff32ffff0bff3cff2880ffff0bff32"
    "ffff0bff32ffff0bff3cff2280ff0580ffff0bff32ffff02ff2affff04ff02ff"
    "ff04ff07ffff04ffff0bff3cff3c80ff8080808080ffff0bff3cff8080808080"
    "ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ff"
    "ff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff"
    "01ff0bffff0101ff058080ff0180ff02ffff03ff5fffff01ff02ffff03ffff09"
    "ff82011fff3880ffff01ff02ffff03ffff09ffff18ff82059f80ff3c80ffff01"
    "ff02ffff03ffff20ff81bf80ffff01ff02ff3effff04ff02ffff04ff05ffff04"
    "ff0bffff04ff17ffff04ff2fffff04ff81dfffff04ff82019fffff04ff82017f"
    "ff80808080808080808080ffff01ff088080ff0180ffff01ff04ff819fffff02"
    "ff3effff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff2fffff04ff81"
    "dfffff04ff81bfffff04ff82017fff808080808080808080808080ff0180ffff"
    "01ff02ffff03ffff09ff82011fff2c80ffff01ff02ffff03ffff20ff82017f80"
    "ffff01ff04ffff04ff24ffff04ffff0eff10ffff02ff2effff04ff02ffff04ff"
    "82019fff8080808080ff808080ffff02ff3effff04ff02ffff04ff05ffff04ff"
    "0bffff04ff17ffff04ff2fffff04ff81dfffff04ff81bfffff04ffff02ff0bff"
    "ff04ff17ffff04ff2fffff04ff82019fff8080808080ff808080808080808080"
    "8080ffff01ff088080ff0180ffff01ff02ffff03ffff09ff82011fff2480ffff"
    "01ff02ffff03ffff20ffff02ffff03ffff09ffff0122ffff0dff82029f8080ff"
    "ff01ff02ffff03ffff09ffff0cff82029fff80ffff010280ff1080ffff01ff01"
    "01ff8080ff0180ff8080ff018080ffff01ff04ff819fffff02ff3effff04ff02"
    "ffff04ff05ffff04ff0bffff04ff17ffff04ff2fffff04ff81dfffff04ff81bf"
    "ffff04ff82017fff8080808080808080808080ffff01ff088080ff0180ffff01"
    "ff04ff819fffff02ff3effff04ff02ffff04ff05ffff04ff0bffff04ff17ffff"
    "04ff2fffff04ff81dfffff04ff81bfffff04ff82017fff808080808080808080"
    "808080ff018080ff018080ff0180ffff01ff02ff3affff04ff02ffff04ff05ff"
    "ff04ff0bffff04ff81bfffff04ffff02ffff03ff82017fffff0182017fffff01"
    "ff02ff0bffff04ff17ffff04ff2fffff01ff808080808080ff0180ff80808080"
    "80808080ff0180ff018080ffff04ffff01a0c5abea79afaa001b5427dfa0c8cf"
    "42ca6f38f5841b78f9b3c252733eb2de2726ffff04ffff0180ffff04ffff01ff"
    "02ffff01ff02ffff01ff02ffff03ff81bfffff01ff04ff82013fffff04ff80ff"
    "ff04ffff02ffff03ffff22ff82013fffff20ffff09ff82013fff2f808080ffff"
    "01ff04ffff04ff10ffff04ffff0bffff02ff2effff04ff02ffff04ff09ffff04"
    "ff8205bfffff04ffff02ff3effff04ff02ffff04ffff04ff09ffff04ff82013f"
    "ff1d8080ff80808080ff808080808080ff1580ff808080ffff02ff16ffff04ff"
    "02ffff04ff0bffff04ff17ffff04ff8202bfffff04ff15ff8080808080808080"
    "ffff01ff02ff16ffff04ff02ffff04ff0bffff04ff17ffff04ff8202bfffff04"
    "ff15ff8080808080808080ff0180ff80808080ffff01ff04ff2fffff01ff80ff"
    "80808080ff0180ffff04ffff01ffffff3f02ff04ff0101ffff822710ff02ff02"
    "ffff03ff05ffff01ff02ff3affff04ff02ffff04ff0dffff04ffff0bff2affff"
    "0bff2cff1480ffff0bff2affff0bff2affff0bff2cff3c80ff0980ffff0bff2a"
    "ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff02ffff"
    "03ff17ffff01ff04ffff04ff10ffff04ffff0bff81a7ffff02ff3effff04ff02"
    "ffff04ffff04ff2fffff04ffff04ff05ffff04ffff05ffff14ffff12ff47ff0b"
    "80ff128080ffff04ffff04ff05ff8080ff80808080ff808080ff8080808080ff"
    "808080ffff02ff16ffff04ff02ffff04ff05ffff04ff0bffff04ff37ffff04ff"
    "2fff8080808080808080ff8080ff0180ffff0bff2affff0bff2cff1880ffff0b"
    "ff2affff0bff2affff0bff2cff3c80ff0580ffff0bff2affff02ff3affff04ff"
    "02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff808080"
    "8080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff3effff04ff02"
    "ffff04ff09ff80808080ffff02ff3effff04ff02ffff04ff0dff8080808080ff"
    "ff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01ffa07faa3253bf"
    "ddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa02268ab"
    "a6ee7b6a26b6f8abc2c00938e413a8aa128d1ba1bdc4a9bfb84e62aa2da0eff0"
    "7522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff"
    "04ffff01a003d5d19244dfe1fffc3de5f9e1ded13bd5fb47340e798c9d042d7c"
    "d9a101ca09ffff04ffff0182012cff0180808080ffff04ffff01ff02ffff01ff"
    "02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1e"
    "ffff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01"
    "ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05"
    "ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff"
    "17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff"
    "0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff"
    "04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff01"
    "8080ffff04ffff01b0b4652a5c069d8498cd4b0dd1bd5198176078b466264651"
    "7d51e28344b2e714d8cefb781e4dbb5d4cc7e0cba7b4b50d77ff018080ff0180"
    "80808080ff018080808080ff01808080ffffa02268aba6ee7b6a26b6f8abc2c0"
    "0938e413a8aa128d1ba1bdc4a9bfb84e62aa2dffa012b92f169ae6991c481b3f"
    "43e17b821cd8aec6bb1614bbe9042e6f9c734979aeff0180ff01ffffffff80ff"
    "ff01ffff81f6ff80ffffff64ffa0bae24162efbd568f89bc7a340798a6118df0"
    "189eb9e3f8697bcea27af99f8f798080ff8080ffff33ffa0bae24162efbd568f"
    "89bc7a340798a6118df0189eb9e3f8697bcea27af99f8f79ff01ffffa0bae241"
    "62efbd568f89bc7a340798a6118df0189eb9e3f8697bcea27af99f8f798080ff"
    "ff3fffa01791f8e6d86d66bca42867c0be163909c07c46dfb3bb6660f1fe8b6b"
    "0cb952e48080ff808080808096a0c4136217c2c2cc4eb525ba7aa14d166d0353"
    "9e5d1ce733a28592fc4adf52a92f873e96ac8a3dfc02964f102dca750768cade"
    "7acbf0055da31d080b9894768971906509062e2255634f14e4e6f7acd68b7c40"
    "d1526e5ca0b489b7afd60762",
)
