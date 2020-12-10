import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import moment from 'moment';
import {
  Typography,
  Link,
  Tooltip,
} from '@material-ui/core';
import { Flex, Table, TooltipIcon, Card } from '@chia/core';
import type { RootState } from '../../modules/rootReducer';
import type { Row } from '../core/Table/Table';

const cols = [
  {
    minWidth: '200px',
    field(row: Row) {
      return (
        <Tooltip title={row.challenge}>
          <span>{row.challenge}</span>
        </Tooltip>
      );
    },
    title: (
      <Trans id="FarmLatestBlockChallenges.challengeHash">Challenge Hash</Trans>
    ),
  },
  {
    width: '150px',
    field: 'height',
    title: <Trans id="FarmLatestBlockChallenges.height">Height</Trans>,
  },
  {
    width: '200px',
    field(row: Row) {
      return row.estimates.length;
    },
    title: (
      <Trans id="FarmLatestBlockChallenges.challengeHash">Challenge Hash</Trans>
    ),
  },
  {
    width: '200px',
    field(row: Row) {
      if (row.estimates.length > 0) {
        const seconds = Math.min(...row.estimates);
        return moment.duration({ seconds }).humanize();
      }

      return null;
    },
    title: (
      <Flex alignItems="center" gap={1}>
        <span>
          <Trans id="FarmLatestBlockChallenges.bestEstimate">
            Best Estimate
          </Trans>
        </span>
        <TooltipIcon>
          <Trans id="FarmLatestBlockChallenges.bestEstimateTooltip">
            Best Estimate is how many seconds of time must be proved for your
            proofs.
          </Trans>
        </TooltipIcon>
      </Flex>
    ),
  },
];

export default function FarmLatestBlockChallenges() {
  const latestChallenges = useSelector(
    (state: RootState) => state.farming_state.farmer.latest_challenges ?? [],
  );

  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );

  const hasPlots = !!plots && plots.length > 0;
  const reducedLatestChallenges = latestChallenges.slice(0, 5);

  return (
    <Card
      title={(
        <Trans id="FarmLatestBlockChallenges.title">
          Latest Block Challenges
        </Trans>
      )}
      tooltip={hasPlots ? (
        <Trans id="FarmLatestBlockChallenges.description">
          Below are the current block challenges. You may or may not have
          a proof of space for these challenges. These blocks do not
          currently contain a proof of time.
        </Trans>
      ): undefined}
    >
      {!hasPlots && (
        <Typography variant="body2">
          <Trans id="FarmLatestBlockChallenges.description">
            Below are the current block challenges. You may or may not have a
            proof of space for these challenges. These blocks do not currently
            contain a proof of time.
          </Trans>
        </Typography>
      )}
      <Table cols={cols} rows={reducedLatestChallenges} />
      <Typography variant="caption">
        <Trans id="FarmLatestBlockChallenges.subDescription">
          *Want to explore Chia’s blocks further? Check out{' '}
          <Link
            color="primary"
            href="https://www.chiaexplorer.com/"
            target="_blank"
          >
            Chia Explorer
          </Link>{' '}
          built by an open source developer.
        </Trans>
      </Typography>
    </Card>
  );
}
