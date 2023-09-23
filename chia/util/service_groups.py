from __future__ import annotations

from typing import Generator, KeysView

SERVICES_FOR_GROUP = {
    "all": [
        "chia_harvester",
        "chia_timelord_launcher",
        "chia_timelord",
        "chia_farmer",
        "chia_full_node",
        "chia_wallet",
        "chia_data_layer",
        "chia_data_layer_http",
    ],
    # TODO: should this be `data_layer`?
    "data": ["chia_wallet", "chia_data_layer"],
    "data_layer_http": ["chia_data_layer_http"],
    "node": ["chia_full_node"],
    "harvester": ["chia_harvester"],
    "farmer": ["chia_harvester", "chia_farmer", "chia_full_node", "chia_wallet"],
    "farmer-no-wallet": ["chia_harvester", "chia_farmer", "chia_full_node"],
    "farmer-only": ["chia_farmer"],
    "timelord": ["chia_timelord_launcher", "chia_timelord", "chia_full_node"],
    "timelord-only": ["chia_timelord"],
    "timelord-launcher-only": ["chia_timelord_launcher"],
    "wallet": ["chia_wallet"],
    "introducer": ["chia_introducer"],
    "simulator": ["chia_full_node_simulator"],
    "crawler": ["chia_crawler"],
    "seeder": ["chia_crawler", "chia_seeder"],
    "seeder-only": ["chia_seeder"],
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
