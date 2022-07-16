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

    for cls in [MakeOfferRequest, MakeOfferResponse, TakeOfferRequest, TakeOfferResponse]:
        schema = desert.schema_class(cls)
        spec.components.schema(component_id=cls.__name__, schema=schema)

    print(json.dumps(spec.to_dict(), indent=4))

    return 0


sys.exit(main())
