SERVICES_FOR_GROUP = {
    "all": "chia_harvester chia_timelord_launcher chia_timelord chia_farmer chia_full_node chia_wallet".split(),
    "node": "chia_full_node".split(),
    "harvester": "chia_harvester".split(),
    "farmer": "chia_harvester chia_farmer chia_full_node chia_wallet".split(),
    "farmer-no-wallet": "chia_harvester chia_farmer chia_full_node".split(),
    "farmer-only": "chia_farmer".split(),
    "timelord": "chia_timelord_launcher chia_timelord chia_full_node".split(),
    "timelord-only": "chia_timelord".split(),
    "timelord-launcher-only": "chia_timelord_launcher".split(),
    "wallet": "chia_wallet chia_full_node".split(),
    "wallet-only": "chia_wallet".split(),
    "introducer": "chia_introducer".split(),
    "simulator": "chia_full_node_simulator".split(),
}


def all_groups():
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups):
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service):
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())
