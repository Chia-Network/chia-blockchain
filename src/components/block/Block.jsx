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
  getBlockRecord,
  getBlock,
} from '../../modules/fullnodeMessages';
import { chia_formatter } from '../../util/chia';
import { calculatePoolReward, calculateBaseFarmerReward } from '../../util/blockRewards';
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
  const [nextSubBlocks, setNextSubBlocks] = useState([]);

  const [error, setError] = useState();
  const [loading, setLoading] = useState(true);

  const hasPreviousSubBlock = !!blockRecord?.prev_hash;
  const hasNextSubBlock = !!nextSubBlocks.length;

  async function prepareData(headerHash) {
    setLoading(true);

    try {
      setBlock();
      setBlockRecord();
      setPrevBlockRecord();
      setNewPlotId();

      const block = await dispatch(getBlock(headerHash));
      setBlock(block);

      if (block) {
        setNewPlotId(await computeNewPlotId(block));
      }

      const blockRecord = await dispatch(getBlockRecord(headerHash));
      setBlockRecord(blockRecord);

      if (blockRecord?.prev_block_hash) {
        const prevBlockRecord = await dispatch(getBlockRecord(blockRecord?.prev_block_hash));
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

  function handleShowPreviousSubBlock() {
    const prevHash = blockRecord?.prev_hash;
    if (prevHash) {
      // save current hash
      setNextSubBlocks([headerHash, ...nextSubBlocks]);

      history.push(`/dashboard/block/${prevHash}`);
    }
  }

  function handleShowNextSubBlock() {
    const [nextSubBlock, ...rest] = nextSubBlocks;
    if (nextSubBlock) {
      setNextSubBlocks(rest);

      history.push(`/dashboard/block/${nextSubBlock}`);
    }
  }

  function handleShowPreviousBlock() {
    const prevBlockHash = blockRecord?.prev_block_hash;
    if (prevBlockHash) {
      // save current hash
      setNextSubBlocks([headerHash, ...nextSubBlocks]);

      history.push(`/dashboard/block/${prevBlockHash}`);
    }
  }

  function handleGoBack() {
    history.push('/dashboard');
  }

  if (loading) {
    return (
      <LayoutMain
        title={<Trans>Block</Trans>}
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
        title={<Trans>Block</Trans>}
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
        title={<Trans>Block</Trans>}
      >
        <Alert severity="warning">
          <Trans>
            Block with hash {headerHash} does not exists.
          </Trans>
        </Alert>
        
      </LayoutMain>
    );
  }

  const difficulty = prevBlockRecord && blockRecord
    ? blockRecord.weight - prevBlockRecord.weight
    : blockRecord?.weight ?? 0;

  const poolReward = chia_formatter(
    Number.parseFloat(calculatePoolReward(blockRecord.height)),
    'mojo',
  ).to('chia').toString();

  const baseFarmerReward = chia_formatter(
    Number.parseFloat(calculateBaseFarmerReward(blockRecord.height)),
    'mojo',
  ).to('chia').toString();

  const chia_fees = blockRecord.fees 
    ? chia_formatter(
      Number.parseFloat(BigInt(blockRecord.fees)),
      'mojo',
    ).to('chia').toString()
    : '';

  const rows = [
    {
      name: <Trans>Header hash</Trans>,
      value: blockRecord.header_hash,
    },
    {
      name: <Trans>Timestamp</Trans>,
      value: blockRecord.timestamp ? unix_to_short_date(blockRecord.timestamp) : null,
      tooltip: (
        <Trans>
          This is the time the block was created by the farmer, which is before
          it is finalized with a proof of time
        </Trans>
      ),
    },
    {
      name: <Trans>Height</Trans>,
      value: blockRecord.height,
    },
    {
      name: <Trans>Weight</Trans>,
      value: BigInt(blockRecord.weight).toLocaleString(),
      tooltip: (
        <Trans>
          Weight is the total added difficulty of all sub blocks up to and including
          this one
        </Trans>
      ),
    },
    {
      name: <Trans>Previous Block Hash</Trans>,
      value: blockRecord.prev_hash,
      onClick: handleShowPreviousSubBlock,
    },
    {
      name: <Trans>Difficulty</Trans>,
      value: BigInt(difficulty).toLocaleString(),
    },
    {
      name: <Trans>Total VDF Iterations</Trans>,
      value: BigInt(blockRecord.total_iters).toLocaleString(),
      tooltip: (
        <Trans>
          The total number of VDF (verifiable delay function) or proof of time
          iterations on the whole chain up to this sub block.
        </Trans>
      ),
    },
    {
      name: <Trans>Block VDF Iterations</Trans>,
      value: BigInt(block.reward_chain_sub_block.challenge_chain_ip_vdf.number_of_iterations).toLocaleString(),
      tooltip: (
        <Trans>
          The total number of VDF (verifiable delay function) or proof of time
          iterations on this block.
        </Trans>
      ),
    },
    {
      name: <Trans>Proof of Space Size</Trans>,
      value: block.reward_chain_sub_block.proof_of_space.size,
    },
    {
      name: <Trans>Plot Public Key</Trans>,
      value: block.reward_chain_sub_block.proof_of_space.plot_public_key,
    },
    {
      name: <Trans>Pool Public Key</Trans>,
      value: block.reward_chain_sub_block.proof_of_space.pool_public_key,
    },
    {
      name: <Trans>Farmer Puzzle Hash</Trans>,
      value: blockRecord.farmer_puzzle_hash,
    },
    {
      name: <Trans>Pool Puzzle Hash</Trans>,
      value: blockRecord.pool_puzzle_hash,
    },
    {
      name: <Trans>Plot Id</Trans>,
      value: newPlotId,
      tooltip: (
        <Trans>
          The seed used to create the plot.
          This depends on the pool pk and plot pk.
        </Trans>
      ),
    },
    {
      name: (
        <Trans>
          Transactions Filter Hash
        </Trans>
      ),
      value: block.foliage_block?.filter_hash,
    },
    /*
    {
      name: <Trans>Coinbase Amount</Trans>,
      value: `${chia_cb} TXCH`,
      tooltip: (
        <Trans>
          This is the chia block reward which goes to the pool (or farmer if not pooling)
        </Trans>
      ),
    },
    {
      name: <Trans>Coinbase Puzzle Hash</Trans>,
      value: blockRecord.pool_puzzle_hash,
    },
    */
   
    {
      name: <Trans>Pool Reward Amount</Trans>,
      value: `${poolReward} TXCH`,
    },
    {
      name: <Trans>Base Farmer Reward Amount</Trans>,
      value: `${baseFarmerReward} TXCH`,
    },
    {
      name: <Trans>Fees Amount</Trans>,
      value: chia_fees ? `${chia_fees} TXCH` : '',
      tooltip: (
        <Trans>
          The total transactions fees in this block. Rewarded to the farmer.
        </Trans>
      ),
    },
    {
      name: <Trans>Fees Puzzle Hash</Trans>,
      value: blockRecord.farmer_puzzle_hash,
    },
  ];

  return (
    <LayoutMain
      title={<Trans>Block</Trans>}
    >
      <Card
        title={(
          <Flex gap={1} alignItems="baseline">
            <BackIcon onClick={handleGoBack}>
              {' '}
            </BackIcon>
            <span>
              <Trans>
                Block at height {blockRecord.height} in the Chia
                blockchain
              </Trans>
            </span>
          </Flex>
        )}
        action={(
          <Flex gap={1}>
            <Button onClick={handleShowPreviousSubBlock} disabled={!hasPreviousSubBlock}>
              <Trans>
                Previous
              </Trans>
            </Button>
            <Button onClick={handleShowNextSubBlock} disabled={!hasNextSubBlock}>
              <Trans>
                Next
              </Trans>
            </Button>
          </Flex>
        )}
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
                    onClick={row.onClick}
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
