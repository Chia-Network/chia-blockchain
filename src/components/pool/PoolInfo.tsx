import React from 'react';
import { t, Trans } from '@lingui/macro';
import styled from 'styled-components';
import {
  Box,
  CardContent,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableRow,
} from '@material-ui/core';
import type PoolInfoType from '../../types/PoolInfo';
import { Flex } from '@chia/core';

const StyledLogo = styled.img`
  max-height: 300px;
  max-width: 350px;
`;

type Props = {
  poolInfo: PoolInfoType;
};

export default function PoolInfo(props: Props) {
  const { poolInfo } = props;

  const rows = [{
    label: <Trans>Fee</Trans>,
    value: poolInfo.fee,
  }, {
    label: <Trans>Protocol Version</Trans>,
    value: poolInfo.protocol_version,
  }, {
    label: <Trans>Minimum Difficulty</Trans>,
    value: poolInfo.minimum_difficulty,
  }, {
    label: <Trans>Relative Lock Height</Trans>,
    value: poolInfo.relative_lock_height,
  }, {
    label: <Trans>Target Puzzle Hash</Trans>,
    value: poolInfo.target_puzzle_hash,
  }].filter(row => row.value !== undefined);

  return (
    <Flex flexDirection="column" gap={2}>
      <Box>
        <StyledLogo src={poolInfo.logo_url} alt={t`Pool logo`} />
      </Box>
      <Flex flexDirection="column" gap={1}>
        <Typography gutterBottom variant="h5" component="h2">
          {poolInfo.name}
        </Typography>
        <Typography gutterBottom variant="body1" color="textSecondary" component="p">
          {poolInfo.pool_url}
        </Typography>
        <Typography variant="body2" color="textSecondary" component="p">
          {poolInfo.description}
        </Typography>
      </Flex>
      <Table size="small" aria-label="a dense table">
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.label}>
              <TableCell component="th" scope="row">
                <Typography variant="body2" color="textSecondary"> 
                  {row.label}
                </Typography>
              </TableCell>
              <TableCell align="right">
                <Typography variant="body2"> 
                  {row.value}
                </Typography>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Flex>
  );
}
