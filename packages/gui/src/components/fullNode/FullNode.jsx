import React from 'react';
import { Trans } from '@lingui/macro';
import { get } from 'lodash';
import {
  FormatLargeNumber,
  Flex,
  Card,
  Loading,
  StateColor,
  Table,
  DashboardTitle,
} from '@chia/core';
import { Status } from '@chia/icons';
import { useGetLatestBlocksQuery, useGetUnfinishedBlockHeadersQuery } from '@chia/api-react';
import { useNavigate } from 'react-router-dom';
import { Box, Tooltip, Typography } from '@material-ui/core';
// import HelpIcon from '@material-ui/icons/Help';
import { unix_to_short_date } from '../../util/utils';
import FullNodeConnections from './FullNodeConnections';
import FullNodeBlockSearch from './FullNodeBlockSearch';
import FullNodeCards from './card/FullNodeCards';

/* global BigInt */

const cols = [
  {
    minWidth: '250px',
    field(row) {
      const { isFinished = false, headerHash, foliage } = row;

      const { foliageTransactionBlockHash } = foliage || {};

      const value = isFinished ? (
        headerHash
      ) : (
        <span>{foliageTransactionBlockHash}</span>
      );

      const color = isFinished ? StateColor.SUCCESS : StateColor.WARNING;

      const tooltip = isFinished ? (
        <Trans>Finished</Trans>
      ) : (
        <Trans>In Progress</Trans>
      );

      return (
        <Flex gap={1} alignItems="center">
          <Tooltip title={<span>{tooltip}</span>}>
            <Status color={color} />
          </Tooltip>
          <Tooltip title={<span>{value}</span>}>
            <Box textOverflow="ellipsis" overflow="hidden">
              {value}
            </Box>
          </Tooltip>
        </Flex>
      );
    },
    title: <Trans>Header Hash</Trans>,
  },
  {
    field(row) {
      const { isFinished, foliage, height } = row;

      const { height: foliageHeight } = foliage || {};

      if (!isFinished) {
        return (
          <i>
            <FormatLargeNumber value={foliageHeight} />
          </i>
        );
      }

      return <FormatLargeNumber value={height} />;
    },
    title: <Trans>Height</Trans>,
  },
  {
    field(row) {
      const { isFinished } = row;

      const timestamp = isFinished 
        ? row.timestamp
        : get(row, 'foliageTransactionBlock.timestamp', row.timestamp);

      return timestamp ? unix_to_short_date(Number.parseInt(timestamp)) : '';
    },
    title: <Trans>Time Created</Trans>,
  },
  {
    field(row) {
      const { isFinished = false } = row;

      return isFinished ? <Trans>Finished</Trans> : <Trans>Unfinished</Trans>;
    },
    title: <Trans>State</Trans>,
  },
];

const BlocksCard = () => {
  const navigate = useNavigate();
  const { data: latestBlocks = [], isLoading } = useGetLatestBlocksQuery();
  const { data: unfinishedBlockHeaders = [] } = useGetUnfinishedBlockHeadersQuery();

  console.log('unfinishedBlockHeaders', unfinishedBlockHeaders);

  const rows = [
    ...unfinishedBlockHeaders,
    ...latestBlocks.map((row) => ({
      ...row,
      isFinished: true,
    })),
  ];

  function handleRowClick(event, row) {
    const { isFinished, headerHash } = row;

    if (isFinished && headerHash) {
      navigate(`block/${headerHash}`);
    }
  }

  return (
    <Card title={<Trans>Blocks</Trans>} action={<FullNodeBlockSearch />}>
      {!isLoading ? (
        <Table cols={cols} rows={rows} onRowClick={handleRowClick} />
      ) : (
        <Loading center />
      )}
    </Card>
  );
};

export default function FullNode() {
  return (
    <>
      <DashboardTitle><Trans>Full Node</Trans></DashboardTitle>
      <Flex gap={1}>
        <Typography variant="h5" gutterBottom>
          <Trans>Full Node Overview</Trans>
        </Typography>
      </Flex>
      <Flex flexDirection="column" gap={3}>
        <FullNodeCards />
        <BlocksCard />
        <FullNodeConnections />
      </Flex>
    </>
  );
}
