from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "sector_harvester sector_timelord_launcher sector_timelord sector_farmer sector_full_node sector_wallet".split(),
    "node": "sector_full_node".split(),
    "harvester": "sector_harvester".split(),
    "farmer": "sector_harvester sector_farmer sector_full_node sector_wallet".split(),
    "farmer-no-wallet": "sector_harvester sector_farmer sector_full_node".split(),
    "farmer-only": "sector_farmer".split(),
    "timelord": "sector_timelord_launcher sector_timelord sector_full_node".split(),
    "timelord-only": "sector_timelord".split(),
    "timelord-launcher-only": "sector_timelord_launcher".split(),
    "wallet": "sector_wallet sector_full_node".split(),
    "wallet-only": "sector_wallet".split(),
    "introducer": "sector_introducer".split(),
    "simulator": "sector_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
