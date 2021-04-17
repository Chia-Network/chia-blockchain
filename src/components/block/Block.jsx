import React, { useEffect, useState } from 'react';
import { Button, Paper, TableRow, Table, TableBody, TableCell, TableContainer } from '@material-ui/core';
import { Alert } from '@material-ui/lab';
import { Trans } from '@lingui/macro';
import { useParams, useHistory } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import { Card, Link, Loading, TooltipIcon, Flex, CurrencyCode } from '@chia/core';
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
import { mojo_to_chia } from '../../util/chia';
import { calculatePoolReward, calculateBaseFarmerReward } from '../../util/blockRewards';
import LayoutMain from '../layout/LayoutMain';
import toBech32m from '../../util/toBech32m';
import BlockTitle from './BlockTitle';
import useCurrencyCode from '../../hooks/useCurrencyCode';

/* global BigInt */

async function computeNewPlotId(block) {
  const { pool_public_key, plot_public_key } = block.reward_chain_block.proof_of_space;
  if (!pool_public_key) {
    return undefined;
  }
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
  const currencyCode = useCurrencyCode();

  const [error, setError] = useState();
  const [loading, setLoading] = useState(true);

  const hasPreviousBlock = !!blockRecord?.prev_hash && !!blockRecord?.height;
  const hasNextBlock = !!nextSubBlocks.length;

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

      if (blockRecord?.prev_hash && !!blockRecord?.height) {
        const prevBlockRecord = await dispatch(getBlockRecord(blockRecord?.prev_hash));
        setPrevBlockRecord(prevBlockRecord);
      }
    } catch (e) {
      console.log('e', e);
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    prepareData(headerHash);
  }, [headerHash]);

  function handleShowPreviousBlock() {
    const prevHash = blockRecord?.prev_hash;
    if (prevHash && blockRecord?.height) {
      // save current hash
      setNextSubBlocks([headerHash, ...nextSubBlocks]);

      history.push(`/dashboard/block/${prevHash}`);
    }
  }

  function handleShowNextBlock() {
    const [nextSubBlock, ...rest] = nextSubBlocks;
    if (nextSubBlock) {
      setNextSubBlocks(rest);

      history.push(`/dashboard/block/${nextSubBlock}`);
    }
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
        title={<Trans>Block Test</Trans>}
      >
        <Card
          title={(
            <BlockTitle>
              <Trans>
                Block with hash {headerHash}
              </Trans>
            </BlockTitle>
          )}
        >
          <Alert severity="error">
            {error.message}
          </Alert>
        </Card>
      </LayoutMain>
    );
  }

  if (!block) {
    return (
      <LayoutMain
        title={<Trans>Block</Trans>}
      >
        <Card
          title={(
            <BlockTitle>
              <Trans>
                Block
              </Trans>
            </BlockTitle>
          )}
        >
          <Alert severity="warning">
            <Trans>
              Block with hash {headerHash} does not exists.
            </Trans>
          </Alert>
        </Card>
      </LayoutMain>
    );
  }

  const difficulty = prevBlockRecord && blockRecord
    ? blockRecord.weight - prevBlockRecord.weight
    : blockRecord?.weight ?? 0;

  const poolReward = mojo_to_chia(calculatePoolReward(blockRecord.height));
  const baseFarmerReward = mojo_to_chia(calculateBaseFarmerReward(blockRecord.height));

  const chiaFees = blockRecord.fees
    ? mojo_to_chia(BigInt(blockRecord.fees))
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
      name: <Trans>Previous Header Hash</Trans>,
      value: (
        <Link onClick={handleShowPreviousBlock}>
          {blockRecord.prev_hash}
        </Link>
      ),
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
      value: BigInt(block.reward_chain_block.challenge_chain_ip_vdf.number_of_iterations).toLocaleString(),
      tooltip: (
        <Trans>
          The total number of VDF (verifiable delay function) or proof of time
          iterations on this block.
        </Trans>
      ),
    },
    {
      name: <Trans>Proof of Space Size</Trans>,
      value: block.reward_chain_block.proof_of_space.size,
    },
    {
      name: <Trans>Plot Public Key</Trans>,
      value: block.reward_chain_block.proof_of_space.plot_public_key,
    },
    {
      name: <Trans>Pool Public Key</Trans>,
      value: block.reward_chain_block.proof_of_space.pool_public_key,
    },
    {
      name: <Trans>Farmer Puzzle Hash</Trans>,
      value: (
        <Link target="_blank" href={`https://www.chiaexplorer.com/blockchain/puzzlehash/${blockRecord.farmer_puzzle_hash}`}>
          {currencyCode ? toBech32m(blockRecord.farmer_puzzle_hash, currencyCode.toLowerCase()) : ''}
        </Link>
      ),
    },
    {
      name: <Trans>Pool Puzzle Hash</Trans>,
      value: (
        <Link target="_blank" href={`https://www.chiaexplorer.com/blockchain/puzzlehash/${blockRecord.pool_puzzle_hash}`}>
          {currencyCode ? toBech32m(blockRecord.pool_puzzle_hash, currencyCode.toLowerCase()) : ''}
        </Link>
      ),
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
      value: block.foliage_transaction_block?.filter_hash,
    },
    {
      name: <Trans>Pool Reward Amount</Trans>,
      value: `${poolReward} ${currencyCode}`,
    },
    {
      name: <Trans>Base Farmer Reward Amount</Trans>,
      value: `${baseFarmerReward} ${currencyCode}`,
    },
    {
      name: <Trans>Fees Amount</Trans>,
      value: chiaFees ? `${chiaFees} ${currencyCode}` : '',
      tooltip: (
        <Trans>
          The total transactions fees in this block. Rewarded to the farmer.
        </Trans>
      ),
    },
  ];

  return (
    <LayoutMain
      title={<Trans>Block</Trans>}
    >
      <Card
        title={(
          <BlockTitle>
            <Trans>
              Block at height {blockRecord.height} in the Chia
              blockchain
            </Trans>
          </BlockTitle>
        )}
        action={(
          <Flex gap={1}>
            <Button onClick={handleShowPreviousBlock} disabled={!hasPreviousBlock}>
              <Trans>
                Previous
              </Trans>
            </Button>
            <Button onClick={handleShowNextBlock} disabled={!hasNextBlock}>
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
