import React, { useEffect, useCallback, useState } from 'react';
import Grid from '@material-ui/core/Grid';
import { Trans } from '@lingui/macro';
import { withStyles } from '@material-ui/core/styles';
import Typography from '@material-ui/core/Typography';
import { Paper, TableRow, Tooltip } from '@material-ui/core';
import Button from '@material-ui/core/Button';
import Table from '@material-ui/core/Table';
import TableBody from '@material-ui/core/TableBody';
import TableCell from '@material-ui/core/TableCell';
import TableContainer from '@material-ui/core/TableContainer';
import { useDispatch } from 'react-redux';
import HelpIcon from '@material-ui/icons/Help';
import {
  unix_to_short_date,
  hex_to_array,
  arr_to_hex,
  sha256,
} from '../../util/utils';
import {
  clearBlock,
  getHeader,
  getBlock,
} from '../../modules/fullnodeMessages';
import { chia_formatter } from '../../util/chia';

import { hash_header } from '../../util/header';
import { calculate_block_reward } from '../../util/block_rewards';

/* global BigInt */

const styles = (theme) => ({
  form: {
    margin: theme.spacing(1),
  },
  clickable: {
    cursor: 'pointer',
  },
  error: {
    color: 'red',
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
  },
  balancePaper: {
    marginTop: theme.spacing(2),
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1),
  },
  table: {
    minWidth: 650,
  },
  connect: {
    marginLeft: theme.spacing(1),
  },
});

const Block = (props) => {
  const [headerHash, setHeaderHash] = useState('');
  const [plotId, setPlotId] = useState('');
  const [didMount, setDidMount] = useState(false);

  const { prev_header_hash } = props.block.header.data;
  const { height } = props.block.header.data;

  const dispatch = useDispatch();

  const handleClearBlock = useCallback(() => dispatch(clearBlock()), [
    dispatch,
  ]);

  const handleGetHeader = useCallback(
    (headerHash) => dispatch(getHeader(headerHash)),
    [dispatch],
  );

  const handleGetBlock = useCallback(
    (headerHash) => dispatch(getBlock(headerHash)),
    [dispatch],
  );

  const fetchHeaderIfNecessary = useCallback(async () => {
    if (props.prevHeader) {
      const phh = await hash_header(props.prevHeader);
      let phh_expected = props.block.header.data.prev_header_hash;
      if (phh_expected.startsWith('0x') || phh_expected.startsWith('0X')) {
        phh_expected = phh_expected.slice(2);
      }
      if (phh !== phh_expected) {
        handleGetHeader(props.block.header.data.prev_header_hash);
      }
    } else {
      handleGetHeader(props.block.header.data.prev_header_hash);
    }
    const newHeaderHash = await hash_header(props.block.header);

    let buf = hex_to_array(props.block.proof_of_space.pool_public_key);
    buf = buf.concat(hex_to_array(props.block.proof_of_space.plot_public_key));
    const bufHash = await sha256(buf);
    const newPlotId = arr_to_hex(bufHash);
    setHeaderHash(newHeaderHash);
    setPlotId(newPlotId);
  }, [handleGetHeader, props]);

  useEffect(
    (prevProps) => {
      (async () => {
        if (!didMount || height > 0) {
          await fetchHeaderIfNecessary();
        }
      })();
    },
    [prev_header_hash, height, didMount, setDidMount, fetchHeaderIfNecessary],
  );

  const { classes } = props;
  const { block } = props;
  const { prevHeader } = props;

  let diff = 0;
  if (block.header.data.height === 0) {
    diff = block.header.data.weight;
  } else if (prevHeader) {
    diff = block.header.data.weight - prevHeader.data.weight;
  }
  const newHeaderHash = `0x${headerHash}`;
  const newPlotId = `0x${plotId}`;

  const chia_cb = chia_formatter(
    Number.parseFloat(calculate_block_reward(block.header.data.height)),
    'mojo',
  )
    .to('chia')
    .toString();
  const chia_fees = chia_formatter(
    Number.parseFloat(BigInt(block.header.data.total_transaction_fees)),
    'mojo',
  )
    .to('chia')
    .toString();

  const rows = [
    {
      name: <Trans id="Block.headerHash">Header hash</Trans>,
      value: newHeaderHash,
    },
    {
      name: <Trans id="Block.timestamp">Timestamp</Trans>,
      value: unix_to_short_date(block.header.data.timestamp),
      tooltip: (
        <Trans id="Block.timestampTooltip">
          This is the time the block was created by the farmer, which is before
          it is finalized with a proof of time
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.height">Height</Trans>,
      value: block.header.data.height,
    },
    {
      name: <Trans id="Block.weight">Weight</Trans>,
      value: BigInt(block.header.data.weight).toLocaleString(),
      tooltip: (
        <Trans id="Block.weightTooltip">
          Weight is the total added difficulty of all blocks up to and including
          this one
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.previousBlock">Previous block</Trans>,
      value: block.header.data.prev_header_hash,
      previousBlock: true,
    },
    {
      name: <Trans id="Block.difficulty">Difficulty</Trans>,
      value: BigInt(diff).toLocaleString(),
    },
    {
      name: <Trans id="Block.totalVDFIterations">Total VDF Iterations</Trans>,
      value: BigInt(block.header.data.total_iters).toLocaleString(),
      tooltip: (
        <Trans id="Block.totalVDFIterationsTooltip">
          The total number of VDF (verifiable delay function) or proof of time
          iterations on the whole chain up to this block.
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.blockVDFIterations">Block VDF Iterations</Trans>,
      value: BigInt(block.proof_of_time.number_of_iterations).toLocaleString(),
      tooltip: (
        <Trans id="Block.blockVDFIterationsTooltip">
          The total number of VDF (verifiable delay function) or proof of time
          iterations on this block.
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.proofOfSpaceSize">Proof of Space Size</Trans>,
      value: block.proof_of_space.size,
    },
    {
      name: <Trans id="Block.plotPublicKey">Plot Public Key</Trans>,
      value: block.proof_of_space.plot_public_key,
    },
    {
      name: <Trans id="Block.poolPublicKey">Pool Public Key</Trans>,
      value: block.proof_of_space.pool_public_key,
    },
    {
      name: <Trans id="Block.plotId">Plot Id</Trans>,
      value: newPlotId,
      tooltip: (
        <Trans id="Block.plotIdTooltip">
          The seed used to create the plot, this depends on the pool pk and plot
          pk
        </Trans>
      ),
    },
    {
      name: (
        <Trans id="Block.transactionsFilterHash">
          Transactions Filter Hash
        </Trans>
      ),
      value: block.header.data.filter_hash,
    },
    {
      name: (
        <Trans id="Block.transactionsGeneratorHash">
          Transactions Generator Hash
        </Trans>
      ),
      value: block.header.data.generator_hash,
    },
    {
      name: <Trans id="Block.coinbaseAmount">Coinbase Amount</Trans>,
      value: `${chia_cb} TXCH`,
      tooltip: (
        <Trans id="Block.coinbaseAmountTooltip">
          The Chia block reward, goes to the pool (or farmer if not pooling)
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.coinbasePuzzleHash">Coinbase Puzzle Hash</Trans>,
      value: block.header.data.pool_target.puzzle_hash,
    },
    {
      name: <Trans id="Block.feesAmount">Fees Amount</Trans>,
      value: `${chia_fees} TXCH`,
      tooltip: (
        <Trans id="Block.feesAmountTooltip">
          The total fees in this block, goes to the farmer
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.feesPuzzleHash">Fees Puzzle Hash</Trans>,
      value: block.header.data.farmer_rewards_puzzle_hash,
    },
  ];

  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <Button onClick={handleClearBlock}>
            <Trans id="Block.title">Block</Trans>
          </Button>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              <Trans id="Block.description">
                Block at height {block.header.data.height} in the Chia
                blockchain
              </Trans>
            </Typography>
          </div>
          <TableContainer component={Paper}>
            <Table className={classes.table} aria-label="simple table">
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.name}>
                    <TableCell component="th" scope="row">
                      {row.name}{' '}
                      {row.tooltip ? (
                        <Tooltip title={row.tooltip}>
                          <HelpIcon
                            style={{ color: '#c8c8c8', fontSize: 12 }}
                          />
                        </Tooltip>
                      ) : (
                        ''
                      )}
                    </TableCell>
                    <TableCell
                      onClick={
                        row.previousBlock
                          ? () => handleGetBlock(row.value)
                          : () => {}
                      }
                      align="right"
                    >
                      {row.value}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Grid>
      </Grid>
    </Paper>
  );
};

export default withStyles(styles)(Block);
