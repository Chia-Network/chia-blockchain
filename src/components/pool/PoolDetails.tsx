import { Loading } from '@chia/core';
import React, { useMemo } from 'react';
import { Alert } from '@material-ui/lab';
import { useAsync } from 'react-use';
import { t, Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import isURL from 'validator/es/lib/isURL';
import styled from 'styled-components';
import {
  Card,
  CardMedia,
  CardContent,
  CardHeader,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableRow,
} from '@material-ui/core';

const StyledCard = styled(Card)`
  max-width: 350px;
  // min-height: 150px;
`;

const StyledCardMedia = styled(CardMedia)`
  min-height: 150px;
  background-size: contain;
`;

type Props = {
  poolUrl: string;
};

export default function PoolDetails(props: Props) {
  const { poolUrl } = props;
  const isValidUrl = useMemo(() => isURL(poolUrl), [poolUrl]);

  const poolDetails = useAsync(async () => {
    if (!poolUrl) {
      return null;
    }

    if (!isValidUrl) {
      throw new Error(t`The pool URL speciefied is not valid. ${poolUrl}`);
    }

    return JSON.parse('{"description": "(example) The Reference Pool allows you to pool with low fees, paying out daily using Chia.", "fee": "0.01", "logo_url": "https://www.chia.net/img/chia_logo.svg", "minimum_difficulty": 10, "name": "The Reference Pool", "protocol_version": "1.0.0", "relative_lock_height": 100, "target_puzzle_hash": "0x95c8d9dabe37eaf94e2143a4df3cfcb29c010326ea08531a5872d40cf79b6452"}');

    const url = `${poolUrl}/pool_info`;
    const response = await fetch(url);
    const data = await response.json();

    return data;
  }, [poolUrl]);

  if (poolDetails.loading) {
    return (
      <Flex justifyContent="center">
        <Loading />
      </Flex>
    );
  } 

  if (poolDetails.error) {
    return (
      <Alert severity="warning">
        {poolDetails.error.message}
      </Alert>
    );
  }

  if (!poolUrl) {
    return null;
  }

  const pool = poolDetails.value;

  const rows = [{
    label: <Trans>Fee</Trans>,
    value: pool.fee,
  }, {
    label: <Trans>Protocol Version</Trans>,
    value: pool.protocol_version,
  }, {
    label: <Trans>Minimum Difficulty</Trans>,
    value: pool.minimum_difficulty,
  }, {
    label: <Trans>Relative Lock Height</Trans>,
    value: pool.relative_lock_height,
  }].filter(row => row.value !== undefined);

  return (
    <StyledCard variant="outlined">
      {/** 
      <CardHeader
        title={<Trans>Pool Details</Trans>}
      />
      */}
      <StyledCardMedia
        image={pool.logo_url}
      />
      <CardContent>
        <Typography gutterBottom variant="h5" component="h2">
          {pool.name}
        </Typography>
        <Typography variant="body2" color="textSecondary" component="p">
          {pool.description}
        </Typography>
      </CardContent>
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
    </StyledCard>
  );
}

/* 
    <Flex flexDirection="column" flexGrow={1}>
      
    </Flex>
    */