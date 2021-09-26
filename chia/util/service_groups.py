from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "flora_harvester flora_timelord_launcher flora_timelord flora_farmer flora_full_node flora_wallet".split(),
    "node": "flora_full_node".split(),
    "harvester": "flora_harvester".split(),
    "farmer": "flora_harvester flora_farmer flora_full_node flora_wallet".split(),
    "farmer-no-wallet": "flora_harvester flora_farmer flora_full_node".split(),
    "farmer-only": "flora_farmer".split(),
    "timelord": "flora_timelord_launcher flora_timelord flora_full_node".split(),
    "timelord-only": "flora_timelord".split(),
    "timelord-launcher-only": "flora_timelord_launcher".split(),
    "wallet": "flora_wallet flora_full_node".split(),
    "wallet-only": "flora_wallet".split(),
    "introducer": "flora_introducer".split(),
    "simulator": "flora_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
