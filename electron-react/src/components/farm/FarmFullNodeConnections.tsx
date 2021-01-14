import React from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { useSelector } from 'react-redux';
import { Link, Typography, Tooltip, IconButton } from '@material-ui/core';
import { Delete as DeleteIcon } from '@material-ui/icons';
import {
  Flex,
  Table,
  Card,
  FormatBytes,
  FormatConnectionStatus,
} from '@chia/core';
import Connection from '../../types/Connection';
import type { RootState } from '../../modules/rootReducer';
import FarmCloseConnection from './FarmCloseConnection';

const StyledIconButton = styled(IconButton)`
  padding: 0.2rem;
`;

const cols = [
  {
    minWidth: '200px',
    field(row: Connection) {
      return (
        <Tooltip title={row.node_id}>
          <span>{row.node_id}</span>
        </Tooltip>
      );
    },
    title: <Trans id="FarmFullNodeConnections.nodeId">Node ID</Trans>,
  },
  {
    width: '150px',
    field: 'peer_host',
    title: <Trans id="FarmFullNodeConnections.hostName">Host Name</Trans>,
  },
  {
    width: '150px',
    field(row: Connection) {
      return `${row.peer_port}/${row.peer_server_port}`;
    },
    title: <Trans id="FarmFullNodeConnections.port">Port</Trans>,
  },
  {
    width: '200px',
    field(row: Connection) {
      return (
        <>
          <FormatBytes value={row.bytes_written} />
          /
          <FormatBytes value={row.bytes_read} />
        </>
      );
    },
    title: <Trans id="FarmFullNodeConnections.upDown">Up/Down</Trans>,
  },
  {
    width: '100px',
    title: <Trans id="FarmFullNodeConnections.actions">Actions</Trans>,
    field(row: Connection) {
      return (
        <FarmCloseConnection nodeId={row.node_id}>
          {({ onClose }) => (
            <StyledIconButton onClick={() => onClose()}>
              <DeleteIcon />
            </StyledIconButton>
          )}
        </FarmCloseConnection>
      );
    },
  },
];

export default function FarmFullNodeConnections() {
  const connections = useSelector((state: RootState) =>
    state.farming_state.farmer.connections.filter(
      (connection) => connection.type === 1,
    ),
  );

  const connected = useSelector(
    (state: RootState) => state.daemon_state.farmer_connected,
  );

  return (
    <Card 
      title={(
        <Trans id="FarmFullNodeConnections.title">
          Your Full Node Connection
        </Trans>
      )}
      tooltip={(
        <Trans id="FarmFullNodeConnections.description">
          {'The full node that your farmer is connected to is below. '}
          <Link target="_blank" href="https://github.com/Chia-Network/chia-blockchain/wiki/Network-Architecture">
            Learn more
          </Link>
        </Trans>
      )}
      interactive
    >
      <Flex justifyContent="flex-end" gap={1}>
        <Typography variant="caption" color="textSecondary">
          <Trans id="FarmFullNodeConnections.connectionStatus">
            Connection Status:
          </Trans>
        </Typography>
        <FormatConnectionStatus connected={connected} />
      </Flex>
      <Table cols={cols} rows={connections} />
    </Card>
  );
}
