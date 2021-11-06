from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "chiadns_crawler chiadns_server".split(),
    "crawler": "chiadns_crawler".split(),
    "server": "chiadns_server".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service
