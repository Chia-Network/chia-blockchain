import React from 'react';
import { useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Table, Card, FormatBytes } from '@chia/core';
import { Typography } from '@material-ui/core';
import moment from 'moment';
import type { Row } from '../core/components/Table/Table';
import usePlots from '../../hooks/usePlots';
import { RootState } from '../../modules/rootReducer';

const cols = [
  {
    field(row: Row) {
      return row.challenge_hash;
    },
    title: <Trans id="FarmFullNodeConnections.challenge">Challenge</Trans>,
  },
  {
    field(row: Row) {
      return `${row.passed_filter} / ${row.total_plots}`;
    },
    title: <Trans id="FarmFullNodeConnections.passed_filter">Plots Passed Filter</Trans>,
  },
  {
    field(row: Row) {
      return row.proofs;
    },
    title: <Trans id="FarmFullNodeConnections.proofs_found">Proofs Found</Trans>,
  },
  {
    field(row: Row) {
      return moment(row.timestamp * 1000).format('MMM D, H:mm:ss A');
    },
    title: <Trans id="FarmFullNodeConnections.date">Date</Trans>,
  },
];

export default function FarmLastAttemptedProof() {
  const { size } = usePlots();

  const lastAttemtedProof = useSelector((state: RootState) => state.farming_state.farmer.last_farming_info ?? []);
  const reducedLastAttemtedProof = lastAttemtedProof.slice(0, 5);
  const isEmpty = !reducedLastAttemtedProof.length;

  return (
    <Card
      title={(
        <Trans id="FarmLastAttemptedProof.title">
          Last Attempted Proof
        </Trans>
      )}
      tooltip={(
        <Trans id="FarmLastAttemptedProof.tooltip">
          This table shows you the last time your farm attempted to win a block challenge.
        </Trans>
      )}
    >
      <Table
        cols={cols}
        rows={reducedLastAttemtedProof}
        caption={isEmpty && (
          <Typography>
            <Trans id="FarmLastAttemptedProof.emptyDescription">
              None of your plots have passed the plot filter yet.
            </Trans>

            {!!size && (
              <>
                {' '}
                <Trans id="FarmLastAttemptedProof.emptySubDescription">
                  But you are currently farming <FormatBytes value={size} precision={3} />
                </Trans>
              </>
            )}
          </Typography>
        )}
      />
    </Card>
  );
}
