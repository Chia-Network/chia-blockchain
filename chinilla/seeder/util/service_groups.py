from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "chinilla_seeder_crawler chinilla_seeder_server".split(),
    "crawler": "chinilla_seeder_crawler".split(),
    "server": "chinilla_seeder_server".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service
