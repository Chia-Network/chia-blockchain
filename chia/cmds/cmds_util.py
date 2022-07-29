from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_submission_status import MempoolSubmissionStatus
from chia.wallet.transaction_record import TransactionRecord


def transaction_submitted_msg(tx: TransactionRecord) -> str:
    sent_to = [MempoolSubmissionStatus(s[0], s[1], s[2]).to_json_dict_convenience() for s in tx.sent_to]
    return f"Transaction submitted to nodes: {sent_to}"


def transaction_status_msg(fingerprint: int, tx_id: bytes32) -> str:
    return f"Run 'chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}' to get status"
