import dataclasses
import json
import sys

import desert
from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin

from chia.rpc.data_layer_rpc_api import MakeOfferRequest, MakeOfferResponse, TakeOfferRequest, TakeOfferResponse

# TODO: this file belongs elsewhere etc...


def main() -> int:
    spec = APISpec(
        title="Chia Example",
        version="1.0.0",
        openapi_version="3.0.2",
        plugins=[MarshmallowPlugin()],
    )

    # TODO: CAMPid 09431987429870965098097127982098431879
    @dataclasses.dataclass
    class All:
        make_offer_request: MakeOfferRequest
        make_offer_response: MakeOfferResponse
        take_offer_request: TakeOfferRequest
        take_offer_response: TakeOfferResponse

    schema = desert.schema_class(All)
    spec.components.schema(component_id="All", schema=schema)

    print(json.dumps(spec.to_dict(), indent=4))

    return 0


sys.exit(main())
