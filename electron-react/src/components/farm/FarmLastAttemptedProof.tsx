import React from 'react';
import { useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Table, Card, FormatBytes } from '@chia/core';
import { Typography } from '@material-ui/core';
import type { Row } from '../core/components/Table/Table';
import usePlots from '../../hooks/usePlots';
import { RootState } from '../../modules/rootReducer';

const cols = [
  {
    field(row: Row) {
      return row.signage_point_index;
    },
    title: <Trans id="FarmFullNodeConnections.height">Signage Point Index</Trans>,
  },
  {
    field(row: Row) {
      return row.challenge_hash;
    },
    title: <Trans id="FarmFullNodeConnections.date">Challenge Hash</Trans>,
  },
  {
    field(row: Row) {
      return row.plot_identifier;
    },
    title: <Trans id="FarmFullNodeConnections.time">Plot ID</Trans>,
  },
];

export default function FarmLastAttemptedProof() {
  const { size } = usePlots();

  const lastAttemtedProof = useSelector((state: RootState) => state.farming_state.farmer.last_attempted_proofs ?? []);
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
