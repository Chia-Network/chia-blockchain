import React from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { useSelector } from 'react-redux';
import {
  Card,
  CardContent,
  Typography,
  Tooltip,
  IconButton,
} from '@material-ui/core';
import { Delete as DeleteIcon } from '@material-ui/icons';
import Table from '../table/Table';
import Flex from '../flex/Flex';
import TooltipIcon from '../tooltip/TooltipIcon';
import FormatBytes from '../format/FormatBytes';
import Connection from '../../types/Connection';
import type { RootState } from '../../modules/rootReducer';
import FormatConnectionStatus from '../format/FormatConnectionStatus';
import FarmCloseConnection from './FarmCloseConnection';
import BlockContainer from '../block/BlockContainer';

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
    title: <Trans id="FarmFullNodeConnections.nodeId">Node Id</Trans>,
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
    <BlockContainer>
      <Flex flexDirection="column" gap={2}>
        <Flex alignItems="center" gap={1}>
          <Typography variant="h5" gutterBottom>
            <Trans id="FarmFullNodeConnections.title">
              Your Full Node Connnection
            </Trans>
          </Typography>
          <TooltipIcon interactive>
            <Trans id="FarmFullNodeConnections.description">
              The full node that your farmer is connected to is below. Learn
              more
            </Trans>
          </TooltipIcon>
        </Flex>
        <Flex flexDirection="column" gap={1}>
          <Flex justifyContent="flex-end" gap={1}>
            <Typography variant="caption" color="textSecondary">
              <Trans id="FarmFullNodeConnections.connectionStatus">
                Connection Status:
              </Trans>
            </Typography>
            <FormatConnectionStatus connected={connected} />
          </Flex>

          <Table cols={cols} rows={connections} />
        </Flex>
      </Flex>
    </BlockContainer>
  );
}
