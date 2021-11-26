import { t } from '@lingui/macro';

export const mempoolInclusionStatus = {
  SUCCESS: 1, // Transaction added to mempool
  PENDING: 2, // Transaction not yet added to mempool
  FAILED: 3, // Transaction was invalid and dropped
};

export default function getTransactionResult(transaction): {
  message: string;
  success: boolean;
} {
  if (!transaction || !transaction.sentTo || !transaction.sentTo.length) {
    return {
      message: t`Transaction has not been sent to node yet`,
      success: true,
    };
  }

  // At least one node has accepted our transaction
  const hasSuccess = !!transaction.sentTo.find((item) => item[1] === mempoolInclusionStatus.SUCCESS);
  if (hasSuccess) {
    return {
      message: t`Transaction has successfully been sent to a full node and included in the mempool.`,
      success: true,
    };
  }

  // At least one node has accepted our transaction as pending
  const pendingNodeResponse = transaction.sentTo.find((item) => item[1] === mempoolInclusionStatus.PENDING);
  if (pendingNodeResponse) {
    return {
      message: t`Transaction has sent to a full node and is pending inclusion into the mempool. ${pendingNodeResponse[2]}`,
      success: true,
    };
  }

  // No nodes have accepted our transaction, so display the error message of the first
  return {
    message: transaction.sentTo[0][2],
    success: false,
  };
}
