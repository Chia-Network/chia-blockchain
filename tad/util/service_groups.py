from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "tad_harvester tad_timelord_launcher tad_timelord tad_farmer tad_full_node tad_wallet".split(),
    "node": "tad_full_node".split(),
    "harvester": "tad_harvester".split(),
    "farmer": "tad_harvester tad_farmer tad_full_node tad_wallet".split(),
    "farmer-no-wallet": "tad_harvester tad_farmer tad_full_node".split(),
    "farmer-only": "tad_farmer".split(),
    "timelord": "tad_timelord_launcher tad_timelord tad_full_node".split(),
    "timelord-only": "tad_timelord".split(),
    "timelord-launcher-only": "tad_timelord_launcher".split(),
    "wallet": "tad_wallet tad_full_node".split(),
    "wallet-only": "tad_wallet".split(),
    "introducer": "tad_introducer".split(),
    "simulator": "tad_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
