import json

from src.wallet.util.wallet_types import WalletType


def get_backup_info(file_path):
    info_dict = {}
    wallets = []

    backup_text = file_path.read_text()
    json_dict = json.loads(backup_text)

    wallet_list_json = json_dict["wallet_list"]

    for wallet_info in wallet_list_json:
        wallet = {}
        wallet["name"] = wallet_info["name"]
        wallet["type"] = wallet_info["type"]
        wallet["type_name"] = WalletType(wallet_info["type"]).name
        wallet["id"] = wallet_info["id"]
        wallet["data"] = wallet_info["data"]
        wallets.append(wallet)

    info_dict["version"] = json_dict["version"]
    info_dict["fingerprint"] = json_dict["fingerprint"]
    info_dict["timestamp"] = json_dict["timestamp"]
    info_dict["wallets"] = wallets

    return info_dict
