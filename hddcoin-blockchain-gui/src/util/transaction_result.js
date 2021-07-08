export const mempool_inclusion_status = {
  SUCCESS: 1, // Transaction added to mempool
  PENDING: 2, // Transaction not yet added to mempool
  FAILED: 3, // Transaction was invalid and dropped
};

export const get_transaction_result = (transaction) => {
  const success = true;
  const message = '';
  if (!transaction || transaction.transaction.sent_to.length === 0) {
    return {
      message,
      success,
    };
  }

  // At least one node has accepted our transaction
  for (const full_node_response of transaction.transaction.sent_to) {
    if (full_node_response[1] === mempool_inclusion_status.SUCCESS) {
      return {
        message:
          'Transaction has successfully been sent to a full node and included in the mempool.',
        success: true,
      };
    }
  }
  // At least one node has accepted our transaction as pending
  for (const full_node_response of transaction.transaction.sent_to) {
    if (full_node_response[1] === mempool_inclusion_status.PENDING) {
      return {
        message: `Transaction has sent to a full node and is pending inclusion into the mempool. ${full_node_response[2]}`,
        success: true,
      };
    }
  }

  // No nodes have accepted our transaction, so display the error message of the first
  return {
    message: transaction.transaction.sent_to[0][2],
    success: false,
  };
};
