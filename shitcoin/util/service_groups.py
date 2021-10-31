from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "shitcoin_harvester shitcoin_timelord_launcher shitcoin_timelord shitcoin_farmer shitcoin_full_node shitcoin_wallet".split(),
    "node": "shitcoin_full_node".split(),
    "harvester": "shitcoin_harvester".split(),
    "farmer": "shitcoin_harvester shitcoin_farmer shitcoin_full_node shitcoin_wallet".split(),
    "farmer-no-wallet": "shitcoin_harvester shitcoin_farmer shitcoin_full_node".split(),
    "farmer-only": "shitcoin_farmer".split(),
    "timelord": "shitcoin_timelord_launcher shitcoin_timelord shitcoin_full_node".split(),
    "timelord-only": "shitcoin_timelord".split(),
    "timelord-launcher-only": "shitcoin_timelord_launcher".split(),
    "wallet": "shitcoin_wallet shitcoin_full_node".split(),
    "wallet-only": "shitcoin_wallet".split(),
    "introducer": "shitcoin_introducer".split(),
    "simulator": "shitcoin_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
