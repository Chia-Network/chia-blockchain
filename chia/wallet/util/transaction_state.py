from __future__ import annotations

from enum import IntEnum

from chia.wallet.transaction_record import TransactionRecord

# TODO: move to chia.wallet.types
# TODO investigate TestPendingTxCache


class TransactionState(IntEnum):
    """
    TransactionState tracks the life cycle of a transaction from the wallet's point of view,
      from its creation until either block inclusion or failure / cancellation.
    We use this state to know whether we need to resend the transaction,
      if it has been seen in the mempool, or if it is confirmed in a block.
    Transactions with state TX_PENDING will be resent by the mechanism in wallet_node.py
    `TX_IN_MEMPOOL` means that we saw the transaction in AT LEAST ONE peer's mempool,
      at the time of the last check. Note that it is possible for the state to transition
      TX_IN_MEMPOOL -> TX_PENDING again, for example if there was a network partition, or
      the transaction is evicted because of fee pressure.
    `TX_CONFIRMED` means we have seen this tx included in a block. If a reorg evicts the transaction
      from the blockchain, no action is performed, and no warning is given to the user at
      the time of this commit.

    tx_ids of transactions with state [TX_PENDING, TX_IN_MEMPOOL] are kept in
    `WalletTransactionStore._active_transaction_ids`

    How this feature works from the GUI side:
      * The list of active (want to submit, non-cancelled, non-confirmed) transactions is updated periodically
      * When there is a change to the list, `self.wallet_state_manager.state_changed("active_transactions")` is called
      * The list of active transaction IDs is available at: WALLET_API/get_active_transaction_ids

    """

    TX_PENDING = 0  # Awaiting (re-)send to Mempool
    TX_IN_MEMPOOL = 1  # No need to re-submit now, but we may have to later
    TX_CONFIRMED = 2  # We can remove the Transaction from the active list


def tx_state(tx: TransactionRecord) -> TransactionState:
    if tx.confirmed:
        return TransactionState.TX_CONFIRMED
    if tx.is_in_mempool():
        return TransactionState.TX_IN_MEMPOOL
    return TransactionState.TX_PENDING
