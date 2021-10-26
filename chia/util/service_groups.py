from typing import Generator, KeysView

SERVICES_FOR_GROUP = {
    "all": "sit_harvester sit_timelord_launcher sit_timelord sit_farmer sit_full_node sit_wallet".split(),
    "node": "sit_full_node".split(),
    "harvester": "sit_harvester".split(),
    "farmer": "sit_harvester sit_farmer sit_full_node sit_wallet".split(),
    "farmer-no-wallet": "sit_harvester sit_farmer sit_full_node".split(),
    "farmer-only": "sit_farmer".split(),
    "timelord": "sit_timelord_launcher sit_timelord sit_full_node".split(),
    "timelord-only": "sit_timelord".split(),
    "timelord-launcher-only": "sit_timelord_launcher".split(),
    "wallet": "sit_wallet sit_full_node".split(),
    "wallet-only": "sit_wallet".split(),
    "introducer": "sit_introducer".split(),
    "simulator": "sit_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
