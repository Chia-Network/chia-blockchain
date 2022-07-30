import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Card,
  FormatBytes,
  FormatLargeNumber,
  Loading,
  Table,
} from '@chia/core';
import { useGetFullNodeConnectionsQuery } from '@chia/api-react';
import { Connection } from '@chia/api';
import { Tooltip } from '@mui/material';
import { service_connection_types } from '../../util/service_names';

const cols = [
  {
    minWidth: '200px',
    field(row: Connection) {
      return (
        <Tooltip title={row.nodeId}>
          <span>{row.nodeId}</span>
        </Tooltip>
      );
    },
    title: <Trans>Node ID</Trans>,
  },
  {
    field: 'peerHost',
    title: <Trans>IP address</Trans>,
  },
  {
    field(row: Connection) {
      return `${row.peerPort}/${row.peerServerPort}`;
    },
    title: <Trans>Port</Trans>,
  },
  {
    field(row: Connection) {
      return (
        <>
          <FormatBytes
            value={row.bytesWritten}
            unit="MiB"
            removeUnit
            fixedDecimals
          />
          /
          <FormatBytes
            value={row.bytesRead}
            unit="MiB"
            removeUnit
            fixedDecimals
          />
        </>
      );
    },
    title: <Trans>MiB Up/Down</Trans>,
  },
  {
    field(row: Connection) {
      // @ts-ignore
      return service_connection_types[row.type];
    },
    title: <Trans>Connection type</Trans>,
  },
  {
    field: (row: Connection) => <FormatLargeNumber value={row.peakHeight} />,
    title: <Trans>Height</Trans>,
  },
];

export default function Connections() {
  const { data: connections, isLoading } = useGetFullNodeConnectionsQuery();

  return (
    <Card title={<Trans>Full Node Connections</Trans>}>
      {isLoading ? (
        <Loading center />
      ) : !connections?.length ? (
        <Trans>List of connections is empty</Trans>
      ) : (
        <Table cols={cols} rows={connections} />
      )}
    </Card>
  );
}
