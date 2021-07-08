from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "silicoin_harvester silicoin_timelord_launcher silicoin_timelord silicoin_farmer silicoin_full_node silicoin_wallet".split(),
    "node": "silicoin_full_node".split(),
    "harvester": "silicoin_harvester".split(),
    "farmer": "silicoin_harvester silicoin_farmer silicoin_full_node silicoin_wallet".split(),
    "farmer-no-wallet": "silicoin_harvester silicoin_farmer silicoin_full_node".split(),
    "farmer-only": "silicoin_farmer".split(),
    "timelord": "silicoin_timelord_launcher silicoin_timelord silicoin_full_node".split(),
    "timelord-only": "silicoin_timelord".split(),
    "timelord-launcher-only": "silicoin_timelord_launcher".split(),
    "wallet": "silicoin_wallet silicoin_full_node".split(),
    "wallet-only": "silicoin_wallet".split(),
    "introducer": "silicoin_introducer".split(),
    "simulator": "silicoin_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
