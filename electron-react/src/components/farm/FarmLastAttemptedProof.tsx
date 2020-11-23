import React from 'react';
import { Trans } from '@lingui/macro';
import { Table, Card } from '@chia/core';

const cols = [
  {
    field: 'height',
    title: <Trans id="FarmFullNodeConnections.height">Height</Trans>,
  },
  {
    field: 'date',
    title: <Trans id="FarmFullNodeConnections.date">Date</Trans>,
  },
  {
    field: 'time',
    title: <Trans id="FarmFullNodeConnections.time">Time</Trans>,
  },
];

export default function FarmLastAttemptedProof() {
  const lastAttemtedProof: Object[] = []; // TODO use real data when it is available
  const reducedLastAttemtedProof = lastAttemtedProof.slice(0, 3);

  return (
    <Card 
      title={(
        <Trans id="FarmLastAttemptedProof.title">
          Last Attempted Proof
        </Trans>
      )}
      tooltip={(
        <Trans id="FarmLastAttemptedProof.tooltip">
          This table shows you the last time your farm attempted to win a
          block a block challenge.
        </Trans>
      )}
    >
      <Table cols={cols} rows={reducedLastAttemtedProof} />
    </Card>
  );
}
