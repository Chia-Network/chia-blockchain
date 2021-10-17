import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { Box, Tooltip, Typography } from '@material-ui/core';
import { Card, CopyToClipboard, Flex, Loading, Table } from '@chia/core';
import type { Row } from '../core/components/Table/Table';
import {
  mojo_to_chia_string,
  mojo_to_colouredcoin_string,
} from '../../util/chia';
import { unix_to_short_date } from '../../util/utils';
import TransactionType from '../../constants/TransactionType';
import WalletType from '../../constants/WalletType';
import useWallet from '../../hooks/useWallet';
import useWalletTransactions from '../../hooks/useWalletTransactions';

const getCols = (type: WalletType) => [
  {
    field(row: Row) {
      const isOutgoing = [
        TransactionType.OUTGOING,
        TransactionType.OUTGOING_TRADE,
      ].includes(row.type);

      return isOutgoing ? <Trans>Outgoing</Trans> : <Trans>Incoming</Trans>;
    },
    title: <Trans>Type</Trans>,
  },
  {
    minWidth: '150px',
    field: (row: Row) => (
      <Tooltip
        title={
          <Flex alignItems="center" gap={1}>
            <Box maxWidth={200}>{row.toAddress}</Box>
            <CopyToClipboard value={row.toAddress} fontSize="small" />
          </Flex>
        }
        interactive
      >
        <span>{row.toAddress}</span>
      </Tooltip>
    ),
    title: <Trans>To</Trans>,
  },
  {
    field: (row: Row) => unix_to_short_date(row.createdAtTime),
    title: <Trans>Date</Trans>,
  },
  {
    field: (row: Row) =>
      row.confirmed ? (
        <Trans>Confirmed at height {row.confirmedAtHeight}</Trans>
      ) : (
        <Trans>Pending</Trans>
      ),
    title: <Trans>Status</Trans>,
  },
  {
    field: (row: Row) =>
      type === WalletType.CAT
        ? mojo_to_colouredcoin_string(row.amount)
        : mojo_to_chia_string(row.amount),
    title: <Trans>Amount</Trans>,
  },
  {
    field: (row: Row) => mojo_to_chia_string(row.feeAmount),
    title: <Trans>Fee</Trans>,
  },
];

type Props = {
  walletId: number;
};

export default function WalletHistory(props: Props) {
  const { walletId } = props;

  const { wallet, loading: isWalletLoading } = useWallet(walletId);
  const { transactions, isLoading: isWalletTransactionsLoading } = useWalletTransactions(walletId);

  const isLoading = isWalletTransactionsLoading || isWalletLoading;

  const cols = useMemo(() => {
    if (!wallet) {
      return [];
    }

    return getCols(wallet.type);
  }, [wallet?.type]);


  return (
    <Card title={<Trans>History</Trans>}>
      {isLoading ? (
        <Loading center />
      ) : transactions?.length ? (
        <Table
          cols={cols}
          rows={transactions}
          rowsPerPageOptions={[10, 25, 100]}
          rowsPerPage={10}
          pages
        />
      ) : (
        <Typography variant="body2">
          <Trans>No previous transactions</Trans>
        </Typography>
      )}
    </Card>
  );
}
