import React from 'react';
import { useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Link, Table, Card, FormatBytes } from '@chia/core';
import { Typography } from '@material-ui/core';
import moment from 'moment';
import type { Row } from '../core/components/Table/Table';
import usePlots from '../../hooks/usePlots';
import { RootState } from '../../modules/rootReducer';

const cols = [
  {
    minWidth: '200px',
    field: 'challenge_hash',
    tooltip: true,
    title: <Trans>Challenge</Trans>,
  },
  {
    field(row: Row) {
      return `${row.passed_filter} / ${row.total_plots}`;
    },
    title: <Trans>Plots Passed Filter</Trans>,
  },
  {
    field: 'proofs',
    title: <Trans>Proofs Found</Trans>,
  },
  {
    field(row: Row) {
      return moment(row.timestamp * 1000).format('MMM D, h:mm:ss A');
    },
    title: <Trans>Date</Trans>,
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
        <Trans>
          Last Attempted Proof
        </Trans>
      )}
      tooltip={(
        <Trans>
          This table shows you the last time your farm attempted to win a block challenge.{' '}
          <Link target="_blank" href="https://github.com/Chia-Network/chia-blockchain/wiki/FAQ#what-is-the-plot-filter-and-why-didnt-my-plot-pass-it">Learn more</Link>
        </Trans>
      )}
      interactive
    >
      <Table
        cols={cols}
        rows={reducedLastAttemtedProof}
        caption={isEmpty && (
          <Typography>
            <Trans>
              None of your plots have passed the plot filter yet.
            </Trans>

            {!!size && (
              <>
                {' '}
                <Trans>
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
