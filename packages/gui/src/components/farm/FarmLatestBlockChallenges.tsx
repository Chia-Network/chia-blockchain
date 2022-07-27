import React from 'react';
import { Trans } from '@lingui/macro';
import { Table, Card } from '@chia/core';
import {
  useGetSignagePointsQuery,
  useGetTotalHarvestersSummaryQuery,
} from '@chia/api-react';
import type { Row } from '../core/components/Table/Table';

const cols = [
  {
    minWidth: '200px',
    tooltip: true,
    field: 'signagePoint.challengeHash',
    title: <Trans>Challenge Hash</Trans>,
  },
  {
    field: (row: Row) => row.signagePoint.signagePointIndex,
    title: <Trans>Index</Trans>,
  },
];

export default function FarmLatestBlockChallenges() {
  const { data: signagePoints = [], isLoading: isLoadingSignagePoints } =
    useGetSignagePointsQuery();
  const { hasPlots, isLoading: isLoadingTotalHarvestersSummary } =
    useGetTotalHarvestersSummaryQuery();

  const isLoading = isLoadingSignagePoints || isLoadingTotalHarvestersSummary;
  const reducedSignagePoints = signagePoints;

  return (
    <Card
      gap={1}
      title={<Trans>Latest Block Challenges</Trans>}
      titleVariant="h6"
      tooltip={
        hasPlots ? (
          <Trans>
            Below are the current block challenges. You may or may not have a
            proof of space for these challenges. These blocks do not currently
            contain a proof of time.
          </Trans>
        ) : undefined
      }
      transparent
    >
      <Table
        cols={cols}
        rows={reducedSignagePoints}
        rowsPerPageOptions={[5, 10, 25, 100]}
        rowsPerPage={5}
        isLoading={isLoading}
        caption={
          !hasPlots && (
            <Trans>
              Here are the current block challenges. You may or may not have a
              proof of space for these challenges. These blocks do not currently
              contain a proof of time.
            </Trans>
          )
        }
        pages
      />
    </Card>
  );
}
