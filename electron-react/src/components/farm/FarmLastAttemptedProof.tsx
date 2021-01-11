import React from 'react';
import { useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import moment from 'moment';
import { Table, Card, FormatBytes } from '@chia/core';
import { Typography } from '@material-ui/core';
import type { Row } from '../core/Table/Table';
import usePlots from '../../hooks/usePlots';
import { RootState } from '../../modules/rootReducer';

const cols = [
  {
    field: 'height',
    title: <Trans id="FarmFullNodeConnections.height">Height</Trans>,
  },
  {
    field(row: Row) {
      return moment(row.timestamp).format('L');
    },
    title: <Trans id="FarmFullNodeConnections.date">Date</Trans>,
  },
  {
    field(row: Row) {
      return moment(row.timestamp).format('LTS');
    },
    title: <Trans id="FarmFullNodeConnections.time">Time</Trans>,
  },
];

export default function FarmLastAttemptedProof() {
  const { size } = usePlots();

  const lastAttemtedProof = useSelector((state: RootState) => state.local_storage.lastAttepmtedProof ?? []);
  const reducedLastAttemtedProof = lastAttemtedProof.slice(0, 3);
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
