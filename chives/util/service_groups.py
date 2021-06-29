from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "chives_harvester chives_timelord_launcher chives_timelord chives_farmer chives_full_node chives_wallet".split(),
    "node": "chives_full_node".split(),
    "harvester": "chives_harvester".split(),
    "farmer": "chives_harvester chives_farmer chives_full_node chives_wallet".split(),
    "farmer-no-wallet": "chives_harvester chives_farmer chives_full_node".split(),
    "farmer-only": "chives_farmer".split(),
    "timelord": "chives_timelord_launcher chives_timelord chives_full_node".split(),
    "timelord-only": "chives_timelord".split(),
    "timelord-launcher-only": "chives_timelord_launcher".split(),
    "wallet": "chives_wallet chives_full_node".split(),
    "wallet-only": "chives_wallet".split(),
    "introducer": "chives_introducer".split(),
    "simulator": "chives_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
