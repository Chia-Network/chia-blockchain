import React from 'react';
import { Trans } from '@lingui/macro';
import { Link, Loading, Table, Card, FormatBytes } from '@chia/core';
import { useGetFarmingInfoQuery } from '@chia/api-react';
import { Typography } from '@material-ui/core';
import moment from 'moment';
import type { Row } from '../core/components/Table/Table';
import usePlots from '../../hooks/usePlots';

const cols = [
  {
    minWidth: '200px',
    field: 'challengeHash',
    tooltip: true,
    title: <Trans>Challenge</Trans>,
  },
  {
    field(row: Row) {
      return `${row.passedFilter} / ${row.totalPlots}`;
    },
    title: <Trans>Plots Passed Filter</Trans>,
  },
  {
    field: 'proofs',
    title: <Trans>Proofs Found</Trans>,
  },
  {
    field(row: Row) {
      return moment(row.timestamp * 1000).format('LLL');
    },
    title: <Trans>Date</Trans>,
  },
];

export default function FarmLastAttemptedProof() {
  const { size } = usePlots();

  const { data: lastAttemptedProof, isLoading } = useGetFarmingInfoQuery();

  const reducedLastAttemptedProof = lastAttemptedProof?.slice(0, 5);
  const isEmpty = !reducedLastAttemptedProof?.length;

  return (
    <Card
      title={<Trans>Last Attempted Proof</Trans>}
      tooltip={
        <Trans>
          This table shows you the last time your farm attempted to win a block
          challenge.{' '}
          <Link
            target="_blank"
            href="https://github.com/Chia-Network/chia-blockchain/wiki/FAQ#what-is-the-plot-filter-and-why-didnt-my-plot-pass-it"
          >
            Learn more
          </Link>
        </Trans>
      }
      interactive
    >
      {isLoading ? (
        <Loading center />
      ) : (
        <Table
          cols={cols}
          rows={reducedLastAttemptedProof}
          caption={
            isEmpty && (
              <Typography>
                <Trans>None of your plots have passed the plot filter yet.</Trans>

                {!!size && (
                  <>
                    {' '}
                    <Trans>
                      But you are currently farming{' '}
                      <FormatBytes value={size} precision={3} />
                    </Trans>
                  </>
                )}
              </Typography>
            )
          }
        />
      )}
    </Card>
  );
}
