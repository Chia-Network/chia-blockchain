from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "flange_harvester flange_timelord_launcher flange_timelord flange_farmer flange_full_node flange_wallet".split(),
    "node": "flange_full_node".split(),
    "harvester": "flange_harvester".split(),
    "farmer": "flange_harvester flange_farmer flange_full_node flange_wallet".split(),
    "farmer-no-wallet": "flange_harvester flange_farmer flange_full_node".split(),
    "farmer-only": "flange_farmer".split(),
    "timelord": "flange_timelord_launcher flange_timelord flange_full_node".split(),
    "timelord-only": "flange_timelord".split(),
    "timelord-launcher-only": "flange_timelord_launcher".split(),
    "wallet": "flange_wallet flange_full_node".split(),
    "wallet-only": "flange_wallet".split(),
    "introducer": "flange_introducer".split(),
    "simulator": "flange_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
