SERVICES_FOR_GROUP = {
    "all": "chia_harvester chia_timelord chia_timelord_launcher chia_farmer chia_full_node".split(),
    "node": "chia_full_node".split(),
    "harvester": "chia_harvester".split(),
    "farmer": "chia_harvester chia_farmer chia_full_node".split(),
    "timelord": "chia_timelord chia_timelord_launcher chia_full_node".split(),
    "wallet": ["npm run --prefix ./electron-ui start"],
    "wallet-server": "chia-wallet".split(),
    "introducer": "chia_introducer".split(),
}


def all_groups():
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups):
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service
