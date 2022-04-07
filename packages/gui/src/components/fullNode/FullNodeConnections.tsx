import React from 'react';
import { Trans } from '@lingui/macro';
import { Delete as DeleteIcon } from '@mui/icons-material';
import styled from 'styled-components';
import {
  Button,
  Card,
  FormatBytes,
  FormatLargeNumber,
  Loading,
  Table,
  IconButton,
  useOpenDialog,
} from '@chia/core';
import { useGetFullNodeConnectionsQuery } from '@chia/api-react';
import { Tooltip } from '@mui/material';
import { service_connection_types } from '../../util/service_names';
import Connection from '../../types/Connection';
import FullNodeCloseConnection from './FullNodeCloseConnection';
import FullNodeAddConnection from './FullNodeAddConnection';

const StyledIconButton = styled(IconButton)`
  padding: 0.2rem;
`;

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
  {
    title: <Trans>Actions</Trans>,
    field(row: Connection) {
      return (
        <FullNodeCloseConnection nodeId={row.nodeId}>
          {({ onClose }) => (
            <StyledIconButton onClick={onClose}>
              <DeleteIcon />
            </StyledIconButton>
          )}
        </FullNodeCloseConnection>
      );
    },
  },
];

export default function Connections() {
  const openDialog = useOpenDialog();
  const { data: connections, isLoading } = useGetFullNodeConnectionsQuery();

  function handleAddPeer() {
    openDialog(<FullNodeAddConnection />);
  }

  return (
    <Card
      title={<Trans>Connections</Trans>}
      action={
        <Button onClick={handleAddPeer} variant="outlined">
          <Trans>Connect to other peers</Trans>
        </Button>
      }
      transparent
    >
      <Table cols={cols} rows={connections} isLoading={isLoading} />
    </Card>
  );
}
