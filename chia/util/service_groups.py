from __future__ import annotations

from typing import Generator, KeysView

SERVICES_FOR_GROUP = {
    "all": (
        "chia_harvester chia_timelord_launcher chia_timelord chia_farmer "
        "chia_full_node chia_wallet chia_data_layer chia_data_layer_http"
    ).split(),
    # TODO: should this be `data_layer`?
    "data": "chia_wallet chia_data_layer".split(),
    "data_layer_http": "chia_data_layer_http".split(),
    "node": "chia_full_node".split(),
    "harvester": "chia_harvester".split(),
    "farmer": "chia_harvester chia_farmer chia_full_node chia_wallet".split(),
    "farmer-no-wallet": "chia_harvester chia_farmer chia_full_node".split(),
    "farmer-only": "chia_farmer".split(),
    "timelord": "chia_timelord_launcher chia_timelord chia_full_node".split(),
    "timelord-only": "chia_timelord".split(),
    "timelord-launcher-only": "chia_timelord_launcher".split(),
    "wallet": "chia_wallet".split(),
    "introducer": "chia_introducer".split(),
    "simulator": "chia_full_node_simulator".split(),
    "crawler": "chia_crawler".split(),
    "seeder": "chia_crawler chia_seeder".split(),
    "seeder-only": "chia_seeder".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
