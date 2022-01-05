import React from 'react';
import { OfferSummaryRecord } from '@chia/core';
import {
  Flex
} from '@chia/core';
import {
  Box,
  Divider,
} from '@material-ui/core';
import { useTheme } from '@material-ui/core/styles';
import useAssetIdName from '../../../hooks/useAssetIdName';
import OfferExchangeRate from './OfferExchangeRate';
import OfferSummaryRow from './OfferSummaryRow';
import { mojo_to_chia, mojo_to_colouredcoin } from '../../../util/chia';

type Props = {
  isMyOffer: boolean;
  summary: OfferSummaryRecord;
  makerTitle: React.ReactElement | string;
  takerTitle: React.ReactElement | string;
  rowIndentation: number;
};

export default function OfferSummary(props: Props) {
  const { isMyOffer, summary, makerTitle, takerTitle, rowIndentation } = props;
  const theme = useTheme();
  const { lookupByAssetId } = useAssetIdName();
  const horizontalPadding = `${theme.spacing(rowIndentation)}px`; // logic borrowed from Flex's gap computation
  const makerEntries: [string, number][] = Object.entries(summary.offered);
  const takerEntries: [string, number][] = Object.entries(summary.requested);
  const makerAssetInfo = makerEntries.length === 1 ? lookupByAssetId(makerEntries[0][0]) : undefined;
  const takerAssetInfo = takerEntries.length === 1 ? lookupByAssetId(takerEntries[0][0]) : undefined;
  const makerAmount = makerEntries[0][0].toLowerCase() === 'xch' ? Number(mojo_to_chia(makerEntries[0][1])) : Number(mojo_to_colouredcoin(makerEntries[0][1]));
  const takerAmount = takerEntries[0][0].toLowerCase() === 'xch' ? Number(mojo_to_chia(takerEntries[0][1])) : Number(mojo_to_colouredcoin(takerEntries[0][1]));
  const makerExchangeRate = makerAssetInfo && takerAssetInfo ? takerAmount / makerAmount : undefined;
  const takerExchangeRate = makerAssetInfo && takerAssetInfo ? makerAmount / takerAmount : undefined;
  const sections: { title: React.ReactElement | string, entries: [string, number][] }[] = [
    {title: makerTitle, entries: isMyOffer ? makerEntries : takerEntries},
    {title: takerTitle, entries: isMyOffer ? takerEntries : makerEntries}
  ];

  if (!isMyOffer) {
    sections.reverse();
  }

  return (
    <Flex flexDirection="column" flexGrow={1} gap={3}>
      {sections.map(({title, entries}, index) => (
        <>
          {title}
          <Box sx={{ paddingLeft: `${horizontalPadding}`, paddingRight: `${horizontalPadding}` }}>
            <Flex flexDirection="column" gap={1}>
              {entries.map(([assetId, amount], index) => (
                <OfferSummaryRow assetId={assetId} amount={amount as number} rowNumber={index + 1} />
              ))}
            </Flex>
          </Box>
          {index !== sections.length - 1 && (
            <Divider />
          )}
        </>
      ))}
      {!!makerAssetInfo && !!takerAssetInfo && !!makerExchangeRate && !!takerExchangeRate && (
        <Flex flexDirection="column" gap={2}>
          <Divider />
          <OfferExchangeRate makerAssetInfo={makerAssetInfo} takerAssetInfo={takerAssetInfo} makerExchangeRate={makerExchangeRate} takerExchangeRate={takerExchangeRate} />
        </Flex>
      )}
    </Flex>
  );
}

OfferSummary.defaultProps = {
  isMyOffer: false,
  rowIndentation: 3,
};
