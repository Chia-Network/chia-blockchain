import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { type OfferSummaryRecord  } from '@chia/api';
import {
  Flex,
  StateColor,
  mojoToChia,
  mojoToCAT,
} from '@chia/core';
import {
  Box,
  Divider,
  Typography,
} from '@material-ui/core';
import { useTheme } from '@material-ui/core/styles';
import styled from 'styled-components';
import useAssetIdName from '../../hooks/useAssetIdName';
import OfferExchangeRate from './OfferExchangeRate';
import OfferSummaryRow from './OfferSummaryRow';

const StyledWarningText = styled(Typography)`
  color: ${StateColor.WARNING};
`;

type Props = {
  isMyOffer: boolean;
  summary: OfferSummaryRecord;
  makerTitle: React.ReactElement | string;
  takerTitle: React.ReactElement | string;
  rowIndentation: number;
  setIsMissingRequestedAsset?: (isMissing: boolean) => void;
};

export default function OfferSummary(props: Props) {
  const { isMyOffer, summary, makerTitle, takerTitle, rowIndentation, setIsMissingRequestedAsset } = props;
  const theme = useTheme();
  const { lookupByAssetId } = useAssetIdName();
  const horizontalPadding = `${theme.spacing(rowIndentation)}px`; // logic borrowed from Flex's gap computation
  const makerEntries: [string, number][] = Object.entries(summary.offered);
  const takerEntries: [string, number][] = Object.entries(summary.requested);
  const makerAssetInfo = makerEntries.length === 1 ? lookupByAssetId(makerEntries[0][0]) : undefined;
  const takerAssetInfo = takerEntries.length === 1 ? lookupByAssetId(takerEntries[0][0]) : undefined;
  const makerAmount = makerEntries[0][0].toLowerCase() === 'xch' ? Number(mojoToChia(makerEntries[0][1])) : Number(mojoToCAT(makerEntries[0][1]));
  const takerAmount = takerEntries[0][0].toLowerCase() === 'xch' ? Number(mojoToChia(takerEntries[0][1])) : Number(mojoToCAT(takerEntries[0][1]));
  const makerExchangeRate = makerAssetInfo && takerAssetInfo ? takerAmount / makerAmount : undefined;
  const takerExchangeRate = makerAssetInfo && takerAssetInfo ? makerAmount / takerAmount : undefined;

  const [takerUnknownCATs, makerUnknownCATs] = useMemo(() => {
    if (isMyOffer) {
      return [];
    }

    // Identify unknown CATs offered/requested by the maker
    const takerUnknownCATs = makerEntries.filter(([assetId, _]) => lookupByAssetId(assetId) === undefined).map(([assetId, _]) => assetId);
    const makerUnknownCATs = takerEntries.filter(([assetId, _]) => lookupByAssetId(assetId) === undefined).map(([assetId, _]) => assetId);

    return [takerUnknownCATs, makerUnknownCATs];
  }, [summary]);

  const sections: { tradeSide: 'buy' | 'sell', title: React.ReactElement | string, entries: [string, number][], unknownCATs: string[] | undefined }[] = [
    {tradeSide: isMyOffer ? 'sell' : 'buy', title: makerTitle, entries: isMyOffer ? makerEntries : takerEntries, unknownCATs: isMyOffer ? undefined : makerUnknownCATs},
    {tradeSide: isMyOffer ? 'buy' : 'sell', title: takerTitle, entries: isMyOffer ? takerEntries : makerEntries, unknownCATs: isMyOffer ? undefined : takerUnknownCATs},
  ];

  if (setIsMissingRequestedAsset) {
    const isMissingRequestedAsset = isMyOffer ? false : makerUnknownCATs?.length !== 0 ?? false;

    setIsMissingRequestedAsset(isMissingRequestedAsset);
  }

  if (!isMyOffer) {
    sections.reverse();
  }

  return (
    <Flex flexDirection="column" flexGrow={1} gap={3}>
      {sections.map(({tradeSide, title, entries, unknownCATs}, index) => (
        <>
          {title}
          <Box sx={{ paddingLeft: `${horizontalPadding}`, paddingRight: `${horizontalPadding}` }}>
            <Flex flexDirection="column" gap={1}>
              <Flex flexDirection="column" gap={1}>
                {entries.map(([assetId, amount], index) => (
                  <OfferSummaryRow assetId={assetId} amount={amount as number} rowNumber={index + 1} />
                ))}
              </Flex>
              {unknownCATs !== undefined && unknownCATs.length > 0 && (
                <Flex flexDirection="row" gap={1}>
                  {tradeSide === 'sell' && (
                    <StyledWarningText variant="caption"><Trans>Warning: Verify that the offered CAT asset IDs match the asset IDs of the tokens you expect to receive.</Trans></StyledWarningText>
                  )}
                  {tradeSide === 'buy' && (
                    <StyledWarningText variant="caption">Offer cannot be accepted because you don't possess the requested assets</StyledWarningText>
                  )}
                </Flex>
              )}
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
