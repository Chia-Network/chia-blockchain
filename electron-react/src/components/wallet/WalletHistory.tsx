import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { Typography } from '@material-ui/core';
import { useSelector } from 'react-redux';
import { Card, Table } from '@chia/core';
import type { RootState } from '../../modules/rootReducer';
import type { Row } from '../core/components/Table/Table';
import { mojo_to_chia_string, mojo_to_colouredcoin_string } from '../../util/chia';
import { unix_to_short_date } from '../../util/utils';
import TransactionType from '../../constants/TransactionType';
import WalletType from '../../constants/WalletType';

const getCols = (type: WalletType) => [
  {
    width: '120px',
    field(row: Row) {
      const isOutgoing = [
        TransactionType.OUTGOING, 
        TransactionType.OUTGOING_TRADE,
      ].includes(row.type);
  
      return isOutgoing
        ? <Trans id="TransactionTable.outgoing">Outgoing</Trans>
        : <Trans id="TransactionTable.incoming">Incoming</Trans>;
    },
    title: <Trans id="WalletHistory.type">Type</Trans>,
  },
  {
    minWidth: '150px',
    field: (row: Row) => row.to_address,
    tooltip: true,
    title: <Trans id="TransactionTable.to">To</Trans>,
  },
  {
    width: '180px',
    field: (row: Row) => unix_to_short_date(row.created_at_time),
    title: <Trans id="TransactionTable.date">Date</Trans>,
  },
  {
    minWidth: '180px',
    field: (row: Row) => {
      return row.confirmed 
        ? (
          <Trans id="TransactionTable.confirmedAtHeight">
            Confirmed at height {row.confirmed_at_height}
          </Trans>
        ) : <Trans id="TransactionTable.pending">Pending</Trans>;
    },
    title: <Trans id="TransactionTable.status">Status</Trans>,
  },
  {
    minWidth: '130px',
    field: (row: Row) => type === WalletType.COLOURED_COIN
      ? mojo_to_colouredcoin_string(row.amount)
      : mojo_to_chia_string(row.amount),
    title: <Trans id="TransactionTable.amount">Amount</Trans>,
  },
  {
    minWidth: '130px',
    field: (row: Row) => mojo_to_chia_string(row.fee_amount),
    title: <Trans id="TransactionTable.fee">Fee</Trans>,
  },
];

type Props = {
  walletId: number;
};

export default function WalletHistory(props: Props) {
  const { walletId } = props;
  const type = useSelector(
    (state: RootState) => state.wallet_state.wallets[walletId].type,
  );
  const transactions = useSelector(
    (state: RootState) => state.wallet_state.wallets[walletId].transactions,
  );

  const cols = useMemo(() => getCols(type), [type]);

  return (
    <Card
      title={<Trans id="WalletHistory.title">History</Trans>}
    >
      {transactions?.length ? (
        <Table
          cols={cols}
          rows={transactions}
          rowsPerPageOptions={[10, 25, 100]}
          rowsPerPage={10}
          pages
        />
      ) : (
        <Typography id="WalletHistory.noPreviousTransactions" variant="body2">
          No previous transactions
        </Typography>
      )}
    </Card>
  );
}
