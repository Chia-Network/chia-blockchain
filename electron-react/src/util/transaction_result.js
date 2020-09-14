export const mempool_inclusion_status = {
  SUCCESS: 1, // Transaction added to mempool
  PENDING: 2, // Transaction not yet added to mempool
  FAILED: 3 // Transaction was invalid and dropped
};

export const get_transaction_result = (transaction) => {
  let success = true;
  let message = "";
  if (!transaction) {
    return {
      message,
      success
    }
  }

    for (let full_node_response of transaction.transaction.sent_to) {
        console.log("full node response", full_node_response);
    }

//   if (send_transaction_result) {
//     if (send_transaction_result.status === "SUCCESS") {
//       result_message =
//         "Transaction has successfully been sent to a full node and included in the mempool.";
//     } else if (send_transaction_result.status === "PENDING") {
//       result_message =
//         "Transaction has sent to a full node and is pending inclusion into the mempool. " +
//         send_transaction_result.reason;
//     } else {
//       result_message = "Transaction failed. " + send_transaction_result.reason;
//       result_class = classes.resultFailure;
//     }
//   }
    return {
        message,
        success
    }
}
