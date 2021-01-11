import React, { useEffect, useState } from 'react';
import { Button, Paper, TableRow, Table, TableBody, TableCell, TableContainer } from '@material-ui/core';
import { Alert } from '@material-ui/lab';
import { Trans } from '@lingui/macro';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useParams, useHistory } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import { Card, Loading, TooltipIcon, Flex } from '@chia/core';
import styled from 'styled-components';
import {
  unix_to_short_date,
  hex_to_array,
  arr_to_hex,
  sha256,
} from '../../util/utils';
import {
  getSubBlockRecord,
  getSubBlock,
} from '../../modules/fullnodeMessages';
import { chia_formatter } from '../../util/chia';
// import { calculate_block_reward } from '../../util/block_rewards';
import LayoutMain from '../layout/LayoutMain';

/* global BigInt */

const BackIcon = styled(ArrowBackIosIcon)`
  font-size: 1.25rem;
  cursor: pointer;
`;

async function computeNewPlotId(block) {
  const { pool_public_key, plot_public_key } = block.reward_chain_sub_block.proof_of_space;

  let buf = hex_to_array(pool_public_key);
  buf = buf.concat(hex_to_array(plot_public_key));
  const bufHash = await sha256(buf);
  return arr_to_hex(bufHash);
}

export default function Block() {
  const { headerHash } = useParams();
  const history = useHistory();
  const dispatch = useDispatch();
  const [block, setBlock] = useState();
  const [blockRecord, setBlockRecord] = useState();
  const [prevBlockRecord, setPrevBlockRecord] = useState();
  const [newPlotId, setNewPlotId] = useState();

  const [error, setError] = useState();
  const [loading, setLoading] = useState(true);

  const hasPreviousBlock = !!blockRecord?.prev_block_hash;

  async function prepareData(headerHash) {
    setLoading(true);

    try {
      setBlock();
      setBlockRecord();
      setPrevBlockRecord();
      setNewPlotId();

      const block = await dispatch(getSubBlock(headerHash));
      setBlock(block);

      if (block) {
        setNewPlotId(await computeNewPlotId(block));
      }

      const blockRecord = await dispatch(getSubBlockRecord(headerHash));
      setBlockRecord(blockRecord);

      if (blockRecord?.prev_block_hash) {
        const prevBlockRecord = await dispatch(getSubBlockRecord(blockRecord?.prev_block_hash));
        setPrevBlockRecord(prevBlockRecord);
      }
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }


  useEffect(() => {
    prepareData(headerHash);
  }, [headerHash]);

  function handleShowPreviousBlock() {
    const prevBlockHash = blockRecord?.prev_block_hash;
    if (prevBlockHash) {
      history.push(`/dashboard/block/${prevBlockHash}`);
    }
  }

  function handleGoBack() {
    history.push('/dashboard');
  }

  if (loading) {
    return (
      <LayoutMain
        title={<Trans id="Block.title">Block</Trans>}
      >
        <Flex justifyContent="center">
          <Loading />
        </Flex>
      </LayoutMain>
    );
  }

  if (error) {
    return (
      <LayoutMain
        title={<Trans id="Block.title">Block</Trans>}
      >
        <Alert severity="error">
          {error.message}
        </Alert>
      </LayoutMain>
    );
  }

  if (!block) {
    return (
      <LayoutMain
        title={<Trans id="Block.title">Block</Trans>}
      >
        <Alert severity="warning">
          <Trans id="Block.notFound">
            Block with hash {headerHash} does not exists.
          </Trans>
        </Alert>
        
      </LayoutMain>
    );
  }

  const difficulty = prevBlockRecord && blockRecord
    ? blockRecord.weight - prevBlockRecord.weight
    : blockRecord?.weight ?? 0;

  const chia_cb = '';/*chia_formatter(
    Number.parseFloat(calculate_block_reward(blockRecord.height)),
    'mojo',
  )
    .to('chia')
    .toString();
    */
  const chia_fees = chia_formatter(
    Number.parseFloat(BigInt(blockRecord.fees)),
    'mojo',
  )
    .to('chia')
    .toString();

  const rows = [
    {
      name: <Trans id="Block.headerHash">Header hash</Trans>,
      value: blockRecord.header_hash,
    },
    {
      name: <Trans id="Block.timestamp">Timestamp</Trans>,
      value: unix_to_short_date(blockRecord.timestamp),
      tooltip: (
        <Trans id="Block.timestampTooltip">
          This is the time the block was created by the farmer, which is before
          it is finalized with a proof of time
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.height">Height</Trans>,
      value: blockRecord.height,
    },
    {
      name: <Trans id="Block.weight">Weight</Trans>,
      value: BigInt(blockRecord.weight).toLocaleString(),
      tooltip: (
        <Trans id="Block.weightTooltip">
          Weight is the total added difficulty of all sub blocks up to and including
          this one
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.previousBlock">Previous Block</Trans>,
      value: blockRecord.prev_block_hash,
      previousBlock: true,
    },
    {
      name: <Trans id="Block.difficulty">Difficulty</Trans>,
      value: BigInt(difficulty).toLocaleString(),
    },
    {
      name: <Trans id="Block.totalVDFIterations">Total VDF Iterations</Trans>,
      value: BigInt(blockRecord.total_iters).toLocaleString(),
      tooltip: (
        <Trans id="Block.totalVDFIterationsTooltip">
          The total number of VDF (verifiable delay function) or proof of time
          iterations on the whole chain up to this sub block.
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.blockVDFIterations">Block VDF Iterations</Trans>,
      value: BigInt(block.reward_chain_sub_block.challenge_chain_ip_vdf.number_of_iterations).toLocaleString(),
      tooltip: (
        <Trans id="Block.blockVDFIterationsTooltip">
          The total number of VDF (verifiable delay function) or proof of time
          iterations on this block.
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.proofOfSpaceSize">Proof of Space Size</Trans>,
      value: block.reward_chain_sub_block.proof_of_space.size,
    },
    {
      name: <Trans id="Block.plotPublicKey">Plot Public Key</Trans>,
      value: block.reward_chain_sub_block.proof_of_space.plot_public_key,
    },
    {
      name: <Trans id="Block.poolPublicKey">Pool Public Key</Trans>,
      value: block.reward_chain_sub_block.proof_of_space.pool_public_key,
    },
    {
      name: <Trans id="Block.plotId">Plot Id</Trans>,
      value: newPlotId,
      tooltip: (
        <Trans id="Block.plotIdTooltip">
          The seed used to create the plot.
          This depends on the pool pk and plot pk.
        </Trans>
      ),
    },
    {
      name: (
        <Trans id="Block.transactionsFilterHash">
          Transactions Filter Hash
        </Trans>
      ),
      value: block.foliage_block.filter_hash,
    }, /*
    {
      name: (
        <Trans id="Block.transactionsGeneratorHash">
          Transactions Generator Hash
        </Trans>
      ),
      value: block.foliage_block.generator_hash,
    }, */
    {
      name: <Trans id="Block.coinbaseAmount">Coinbase Amount</Trans>,
      value: `${chia_cb} TXCH`,
      tooltip: (
        <Trans id="Block.coinbaseAmountTooltip">
          This is the chia block reward which goes to the pool (or farmer if not pooling)
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.coinbasePuzzleHash">Coinbase Puzzle Hash</Trans>,
      value: blockRecord.pool_puzzle_hash,
    },
    {
      name: <Trans id="Block.feesAmount">Fees Amount</Trans>,
      value: `${chia_fees} TXCH`,
      tooltip: (
        <Trans id="Block.feesAmountTooltip">
          The total transactions fees in this block. Rewarded to the farmer.
        </Trans>
      ),
    },
    {
      name: <Trans id="Block.feesPuzzleHash">Fees Puzzle Hash</Trans>,
      value: blockRecord.farmer_puzzle_hash,
    },
  ];

  return (
    <LayoutMain
      title={<Trans id="Block.title">Block</Trans>}
    >
      <Card
        title={(
          <Flex gap={1} alignItems="baseline">
            <BackIcon onClick={handleGoBack}>
              {' '}
            </BackIcon>
            <span>
              <Trans id="Block.description">
                Block at height {blockRecord.height} in the Chia
                blockchain
              </Trans>
            </span>
          </Flex>
        )}
        action={hasPreviousBlock ? (
          <Button onClick={handleShowPreviousBlock}>
            <Trans id="Block.previousBlock">
              Previous Block
            </Trans>
          </Button>
        ) : null}
      >
        <TableContainer component={Paper}>
          <Table>
            <TableBody>
              {rows.map((row, index) => (
                <TableRow key={index}>
                  <TableCell component="th" scope="row">
                    {row.name}{' '}
                    {row.tooltip && (
                      <TooltipIcon>
                        {row.tooltip}
                      </TooltipIcon>
                    )}
                  </TableCell>
                  <TableCell
                    onClick={row.previousBlock ? handleShowPreviousBlock : undefined}
                    align="right"
                  >
                    {row.value}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>
    </LayoutMain>
  );
}
