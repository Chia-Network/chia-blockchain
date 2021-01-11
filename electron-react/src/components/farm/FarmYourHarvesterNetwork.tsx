import React from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { useSelector } from 'react-redux';
import {
  Typography,
  Tooltip,
  IconButton,
} from '@material-ui/core';
import { Delete as DeleteIcon } from '@material-ui/icons';
import {
  Flex,
  Table,
  FormatBytes,
  FormatConnectionStatus,
  Card,
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
    title: <Trans id="FarmYourHarvesterNetwork.nodeId">Node ID</Trans>,
  },
  {
    width: '150px',
    field: 'peer_host',
    title: <Trans id="FarmYourHarvesterNetwork.hostName">Host Name</Trans>,
  },
  {
    width: '150px',
    field(row: Connection) {
      return `${row.peer_port}/${row.peer_server_port}`;
    },
    title: <Trans id="FarmYourHarvesterNetwork.port">Port</Trans>,
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
    title: <Trans id="FarmYourHarvesterNetwork.upDown">Up/Down</Trans>,
  },
  {
    width: '100px',
    title: <Trans id="FarmYourHarvesterNetwork.actions">Actions</Trans>,
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

export default function FarmYourHarvesterNetwork() {
  const connections = useSelector((state: RootState) =>
    state.farming_state.farmer.connections.filter(
      (connection) => connection.type === 2,
    ),
  );

  const connected = useSelector(
    (state: RootState) => state.daemon_state.harvester_connected,
  );

  return (
    <Card
      gap={1}
      title={(
        <Trans id="FarmYourHarvesterNetwork.title">
          Your Harvester Network
        </Trans>
      )}
      tooltip={(
        <Trans id="FarmYourHarvesterNetwork.description">
          A harvester is a service running on a machine where plot(s) are actually stored. 
          A farmer and harvester talk to a full node to see the state of the chain. 
          View your network of connected harvesters below Learn more
        </Trans>
      )}
      interactive
    >
      <Flex justifyContent="flex-end" gap={1}>
        <Typography variant="caption" color="textSecondary">
          <Trans id="FarmYourHarvesterNetwork.connectionStatus">
            Connection Status:
          </Trans>
        </Typography>
        <FormatConnectionStatus connected={connected} />
      </Flex>

      <Table cols={cols} rows={connections} />
    </Card>
  );
}
