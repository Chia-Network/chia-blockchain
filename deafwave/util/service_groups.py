from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "deafwave_harvester deafwave_timelord_launcher deafwave_timelord deafwave_farmer deafwave_full_node deafwave_wallet".split(),
    "node": "deafwave_full_node".split(),
    "harvester": "deafwave_harvester".split(),
    "farmer": "deafwave_harvester deafwave_farmer deafwave_full_node deafwave_wallet".split(),
    "farmer-no-wallet": "deafwave_harvester deafwave_farmer deafwave_full_node".split(),
    "farmer-only": "deafwave_farmer".split(),
    "timelord": "deafwave_timelord_launcher deafwave_timelord deafwave_full_node".split(),
    "timelord-only": "deafwave_timelord".split(),
    "timelord-launcher-only": "deafwave_timelord_launcher".split(),
    "wallet": "deafwave_wallet deafwave_full_node".split(),
    "wallet-only": "deafwave_wallet".split(),
    "introducer": "deafwave_introducer".split(),
    "simulator": "deafwave_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
