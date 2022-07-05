import json
import unittest

from blspy import G2Element

from chia.types.spend_bundle import SpendBundle


BLANK_SPEND_BUNDLE = SpendBundle(coin_spends=[], aggregated_signature=G2Element())
NULL_SIGNATURE = "0xc" + "0" * 191


class TestStructStream(unittest.TestCase):
    def test_from_json_legacy(self):
        JSON = (
            """
        {
          "coin_solutions": [],
          "aggregated_signature": "%s"
        }
        """
            % NULL_SIGNATURE
        )
        spend_bundle = SpendBundle.from_json_dict(json.loads(JSON))
        json_1 = json.loads(JSON)
        json_2 = spend_bundle.to_json_dict(include_legacy_keys=True, exclude_modern_keys=True)
        assert json_1 == json_2

    def test_from_json_new(self):
        JSON = (
            """
        {
          "coin_spends": [],
          "aggregated_signature": "%s"
        }
        """
            % NULL_SIGNATURE
        )
        spend_bundle = SpendBundle.from_json_dict(json.loads(JSON))
        json_1 = json.loads(JSON)
        json_2 = spend_bundle.to_json_dict(include_legacy_keys=False, exclude_modern_keys=False)
        assert json_1 == json_2

    def test_round_trip(self):
        spend_bundle = BLANK_SPEND_BUNDLE
        round_trip(spend_bundle, include_legacy_keys=True, exclude_modern_keys=True)
        round_trip(spend_bundle, include_legacy_keys=True, exclude_modern_keys=False)
        round_trip(spend_bundle, include_legacy_keys=False, exclude_modern_keys=False)

    def test_dont_use_both_legacy_and_modern(self):
        json_1 = BLANK_SPEND_BUNDLE.to_json_dict(include_legacy_keys=True, exclude_modern_keys=False)
        with self.assertRaises(ValueError):
            SpendBundle.from_json_dict(json_1)


def round_trip(spend_bundle: SpendBundle, **kwargs):
    json_dict = spend_bundle.to_json_dict(**kwargs)

    if kwargs.get("include_legacy_keys", True):
        assert "coin_solutions" in json_dict
    else:
        assert "coin_solutions" not in json_dict

    if kwargs.get("exclude_modern_keys", True):
        assert "coin_spends" not in json_dict
    else:
        assert "coin_spends" in json_dict

    if "coin_spends" in json_dict and "coin_solutions" in json_dict:
        del json_dict["coin_solutions"]

    sb = SpendBundle.from_json_dict(json_dict)
    json_dict_2 = sb.to_json_dict()
    sb = SpendBundle.from_json_dict(json_dict_2)
    json_dict_3 = sb.to_json_dict()
    assert json_dict_2 == json_dict_3
