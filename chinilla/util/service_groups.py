from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "chinilla_harvester chinilla_timelord_launcher chinilla_timelord chinilla_farmer chinilla_full_node chinilla_wallet".split(),
    "node": "chinilla_full_node".split(),
    "harvester": "chinilla_harvester".split(),
    "farmer": "chinilla_harvester chinilla_farmer chinilla_full_node chinilla_wallet".split(),
    "farmer-no-wallet": "chinilla_harvester chinilla_farmer chinilla_full_node".split(),
    "farmer-only": "chinilla_farmer".split(),
    "timelord": "chinilla_timelord_launcher chinilla_timelord chinilla_full_node".split(),
    "timelord-only": "chinilla_timelord".split(),
    "timelord-launcher-only": "chinilla_timelord_launcher".split(),
    "wallet": "chinilla_wallet chinilla_full_node".split(),
    "wallet-only": "chinilla_wallet".split(),
    "introducer": "chinilla_introducer".split(),
    "simulator": "chinilla_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
