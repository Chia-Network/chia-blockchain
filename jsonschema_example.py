import dataclasses
import json
import sys
from typing import Dict

import desert
from marshmallow_jsonschema import JSONSchema

from chia.rpc.data_layer_rpc_api import MakeOfferRequest, MakeOfferResponse, TakeOfferRequest, TakeOfferResponse

# TODO: this file belongs elsewhere etc...

sentinel = desert._make._DESERT_SENTINEL


def remove(removal_key: object, d: Dict[object, object]) -> None:
    if removal_key in d:
        del d[removal_key]

    for value in d.values():
        if isinstance(value, dict):
            remove(removal_key=removal_key, d=value)


def main() -> int:
    json_schema = JSONSchema()

    # TODO: CAMPid 09431987429870965098097127982098431879
    @dataclasses.dataclass
    class All:
        make_offer_request: MakeOfferRequest
        make_offer_response: MakeOfferResponse
        take_offer_request: TakeOfferRequest
        take_offer_response: TakeOfferResponse

    schema = desert.schema(All)
    s = json_schema.dump(schema)
    remove(removal_key=sentinel, d=s)
    print(json.dumps(s, indent=4))

    return 0


sys.exit(main())
