import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trans } from '@lingui/macro';
import moment from 'moment';
import { Box, IconButton, Table as TableBase, TableBody, TableCell, TableRow, Tooltip, Typography, Chip } from '@material-ui/core';
import { CallReceived as CallReceivedIcon, CallMade as CallMadeIcon, ExpandLess as ExpandLessIcon, ExpandMore as ExpandMoreIcon } from '@material-ui/icons';
import { Card, CardKeyValue, CopyToClipboard, Flex, Loading, StateColor, TableControlled, toBech32m, useCurrencyCode, mojoToChiaLocaleString, mojoToCATLocaleString } from '@chia/core';
import { useGetOfferRecordMutation, useGetSyncStatusQuery } from '@chia/api-react';
import styled from 'styled-components';
import type { Row } from '@chia/core';
import { WalletType, TransactionType } from '@chia/api';
import useWallet from '../hooks/useWallet';
import useWalletTransactions from '../hooks/useWalletTransactions';

const StyledTableCellSmall = styled(TableCell)`
  border-bottom: 0;
  padding-left: 0;
  padding-right: 0 !important;
  vertical-align: top;
`;

const StyledTableCellSmallRight = styled(StyledTableCellSmall)`
  width: 100%;
  padding-left: 1rem;
`;

const StyledWarning = styled(Box)`
  color: ${StateColor.WARNING};
`;

async function handleRowClick(event: React.MouseEvent<HTMLTableRowElement>, row: Row, getOfferRecord, navigate) {
  if (row.tradeId) {
    try {
      const { data: response } = await getOfferRecord(row.tradeId);
      const { tradeRecord, success } = response;

      if (success === true && tradeRecord) {
        navigate('/dashboard/wallets/offers/view', {
          state: { tradeRecord: tradeRecord },
        });
      }
    }
    catch (e) {
      console.error(e);
    }
  }
}

const getCols = (type: WalletType, isSyncing, getOfferRecord, navigate) => [
  {
    field: (row: Row) => {
      const isOutgoing = [
        TransactionType.OUTGOING,
        TransactionType.OUTGOING_TRADE,
      ].includes(row.type);

      return (
        <Flex gap={1}>
          <Tooltip
            title={isOutgoing ? <Trans>Outgoing</Trans> : <Trans>Incoming</Trans>}
          >
            {isOutgoing 
              ? <CallMadeIcon color="secondary" />
              : <CallReceivedIcon color="primary" />}
          </Tooltip>
        </Flex>
      );
    },
  },
  {
    width: '100%',
    field: (row: Row, metadata) => {
      const { confirmed: isConfirmed, memos  } = row;
      const hasMemos = !!memos && !!Object.values(memos).length;
      const isRetire = row.toAddress === metadata.retireAddress;
      const isOffer = row.toAddress === metadata.offerTakerAddress;
      const shouldObscureAddress = isRetire || isOffer;

      return (
        <Flex flexDirection="column" gap={1} onClick={(event) => {
            if (!isSyncing) {
              handleRowClick(event, row, getOfferRecord, navigate);
            }
          }}>
          <Tooltip
            title={
              <Flex flexDirection="column" gap={1}>
                {shouldObscureAddress && (
                  <StyledWarning>
                    <Trans>This is not a valid address for sending funds to</Trans>
                  </StyledWarning>
                )}
                <Flex flexDirection="row" alignItems="center" gap={1}>
                  <Box maxWidth={200}>{row.toAddress}</Box>
                  {!shouldObscureAddress && (
                    <CopyToClipboard value={row.toAddress} fontSize="small" />
                  )}
                </Flex>
              </Flex>
            }
            interactive
          >
            <span>{shouldObscureAddress ?
                (row.toAddress.slice(0, 20) + '...')
              :
                row.toAddress
            }</span>
          </Tooltip>
          <Flex gap={0.5}>
            {isConfirmed ? (
              <Chip size="small" variant="outlined" label={<Trans>Confirmed</Trans>} />
            ) : (
              <Chip size="small" color="primary" variant="outlined" label={<Trans>Pending</Trans>} />
            )}
            {hasMemos && (
              <Chip size="small" variant="outlined" label={<Trans>Memo</Trans>} />
            )}
            {isRetire && (
              <Chip size="small" variant="outlined" label={<Trans>Retire</Trans>} />
            )}
            {isOffer && (
              <Chip size="small" variant="outlined" label={<Trans>Offer Accepted</Trans>} />
            )}
          </Flex>
        </Flex>
      );
    },
    title: <Trans>To</Trans>,
  },
  {
    field: (row: Row) => (
      <Typography color="textSecondary" variant="body2">
        {moment(row.createdAtTime * 1000).format('LLL')}
      </Typography>
    ),
    title: <Trans>Date</Trans>,
  },
  {
    field: (row: Row, metadata) => {
      const isOutgoing = [
        TransactionType.OUTGOING,
        TransactionType.OUTGOING_TRADE,
      ].includes(row.type);

      return (
        <>
          <strong>
            {isOutgoing 
              ? <Trans>-</Trans> 
              : <Trans>+</Trans>}
          </strong>
          &nbsp;
          <strong>
            {type === WalletType.CAT
              ? mojoToCATLocaleString(row.amount)
              : mojoToChiaLocaleString(row.amount)}
          </strong>
          &nbsp;
          {metadata.unit}
        </>
      );
    },
    title: <Trans>Amount</Trans>,
  },
  {
    field: (row: Row, metadata) => (
      <>
        <strong>{mojoToChiaLocaleString(row.feeAmount)}</strong>
        &nbsp;
        {metadata.feeUnit}
      </>
    ),
    title: <Trans>Fee</Trans>,
  },
  {
    field: (row: Row, _metadata, isExpanded, toggleExpand) => (
      <IconButton
        aria-label="expand row"
        size="small"
        onClick={toggleExpand}
      >
        {isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
      </IconButton>
    ),
  }
];

type Props = {
  walletId: number;
};

export default function WalletHistory(props: Props) {
  const { walletId } = props;

  const { data: walletState, isLoading: isWalletSyncLoading } = useGetSyncStatusQuery();
  const { wallet, loading: isWalletLoading, unit } = useWallet(walletId);
  const {
    transactions,
    isLoading: isWalletTransactionsLoading,
    page,
    rowsPerPage,
    count,
    pageChange,
  } = useWalletTransactions(walletId, 10, 0, 'RELEVANCE');
  const feeUnit = useCurrencyCode();
  const [getOfferRecord] = useGetOfferRecordMutation();
  const navigate = useNavigate();

  const isLoading = isWalletTransactionsLoading || isWalletLoading;
  const isSyncing = isWalletSyncLoading || walletState.syncing;

  const metadata = useMemo(() => {
    const retireAddress = feeUnit && toBech32m(
      '0000000000000000000000000000000000000000000000000000000000000000',
      feeUnit,
    );

    const offerTakerAddress = feeUnit && toBech32m(
      '0101010101010101010101010101010101010101010101010101010101010101',
      feeUnit,
    );

    return {
      unit,
      feeUnit,
      retireAddress,
      offerTakerAddress,
    };
  }, [unit, feeUnit]);

  const cols = useMemo(() => {
    if (!wallet) {
      return [];
    }

    return getCols(wallet.type, isSyncing, getOfferRecord, navigate);
  }, [wallet?.type]);

  return (
    <Card title={<Trans>Transactions</Trans>}>
      {transactions?.length ? (
        <TableControlled
          cols={cols}
          rows={transactions}
          rowsPerPageOptions={[5, 10, 25, 50, 100, { value: -1, label: <Trans>All</Trans> }]}
          page={page}
          rowsPerPage={rowsPerPage}
          count={count}
          onPageChange={pageChange}
          isLoading={isLoading}
          metadata={metadata}
          expandedCellShift={1}
          uniqueField="name"
          expandedField={(row) => {
            const { confirmedAtHeight, memos } = row;
            const memoValues = memos ? Object.values(memos) : [];
            const memoValuesDecoded = memoValues.map((memoHex) => {
              try {
                const buf = new Buffer(memoHex, 'hex');
                const decodedValue = buf.toString('utf8');

                const bufCheck = Buffer.from(decodedValue, 'utf8');
                if (bufCheck.toString('hex') !== memoHex) {
                  throw new Error('Memo is not valid utf8 string');
                }

                return decodedValue;
              } catch(error: any) {
                return memoHex;
              }
            });
            
            const memosDescription = memoValuesDecoded && memoValuesDecoded.length 
              ? (
                <Flex flexDirection="column">
                  {memoValuesDecoded.map((memo, index) => (
                    <Typography variant="inherit" key={index}>
                      {memo ?? ''}
                    </Typography>
                  ))}
                </Flex>
              )
              : <Trans>Not Available</Trans>;

            const rows = [confirmedAtHeight && {
              key: 'confirmedAtHeight',
              label: <Trans>Confirmed at Height</Trans>,
              value: confirmedAtHeight ? confirmedAtHeight : <Trans>Not Available</Trans>,
            }, {
              key: 'memos',
              label: <Trans>Memos</Trans>,
              value: memosDescription,
            }].filter((item) => !!item);

            return (
              <TableBase size="small">
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.key}>
                      <StyledTableCellSmall>
                        <Typography component='div' variant="body2" color="textSecondary" noWrap>
                          {row.label}
                        </Typography>
                      </StyledTableCellSmall>
                      <StyledTableCellSmallRight>
                        <Box maxWidth="100%">
                          <Typography component='div' variant="body2" noWrap>
                            {row.value}
                          </Typography>
                        </Box>
                      </StyledTableCellSmallRight>
                    </TableRow>
                  ))}
                </TableBody>
              </TableBase>
            );
          }}
          pages
        />
      ) : (
        <Typography variant="body2">
          <Trans>No previous transactions</Trans>
        </Typography>
      )}
    </Card>
  );
}