import React, { ReactNode } from 'react';
import { useWatch } from 'react-hook-form';
import { Trans } from '@lingui/macro';
import {
  Flex,
  Amount,
  Fee,
  Loading,
  TextField,
  Tooltip,
  FormatLargeNumber,
} from '@chia/core';
import { Box, Typography, IconButton } from '@mui/material';
import { Remove } from '@mui/icons-material';
import useOfferBuilderContext from '../../hooks/useOfferBuilderContext';
import OfferBuilderTokenSelector from './OfferBuilderTokenSelector';

export type OfferBuilderValueProps = {
  name: string;
  label: ReactNode;
  caption?: ReactNode;
  type?: 'text' | 'amount' | 'fee' | 'token';
  isLoading?: boolean;
  onRemove?: () => void;
  symbol?: string;
  showAmountInMojos?: boolean;
  usedAssets?: string[];
  disableReadOnly?: boolean;
};

export default function OfferBuilderValue(props: OfferBuilderValueProps) {
  const {
    name,
    caption,
    label,
    onRemove,
    isLoading = false,
    type = 'text',
    symbol,
    showAmountInMojos,
    usedAssets,
    disableReadOnly = false,
  } = props;
  const { readOnly: builderReadOnly } = useOfferBuilderContext();
  const value = useWatch({
    name,
  });

  const readOnly = disableReadOnly ? false : builderReadOnly;
  const displayValue = !value ? (
    <Trans>Not Available</Trans>
  ) : ['amount', 'fee', 'token'].includes(type) ? (
    <FormatLargeNumber value={value} />
  ) : (
    value
  );

  return (
    <Flex flexDirection="column" minWidth={0} gap={1}>
      {isLoading ? (
        <Loading />
      ) : readOnly ? (
        <>
          <Typography variant="body2" color="textSecondary">
            {label}
          </Typography>
          <Tooltip title={displayValue} copyToClipboard>
            <Typography variant="h6" noWrap>
              {type === 'token' ? (
                <OfferBuilderTokenSelector
                  variant="filled"
                  color="secondary"
                  label={label}
                  name={name}
                  required
                  fullWidth
                  readOnly
                />
              ) : (
                <>
                  {displayValue}
                  &nbsp;
                  {symbol}
                </>
              )}
            </Typography>
          </Tooltip>
        </>
      ) : (
        <Flex gap={2} alignItems="center">
          <Box flexGrow={1} minWidth={0}>
            {type === 'amount' ? (
              <Amount
                variant="filled"
                color="secondary"
                label={label}
                name={name}
                symbol={symbol}
                showAmountInMojos={showAmountInMojos}
                required
                fullWidth
              />
            ) : type === 'fee' ? (
              <Fee
                variant="filled"
                color="secondary"
                label={label}
                name={name}
                required
                fullWidth
              />
            ) : type === 'text' ? (
              <TextField
                variant="filled"
                color="secondary"
                label={label}
                name={name}
                required
                fullWidth
              />
            ) : type === 'token' ? (
              <OfferBuilderTokenSelector
                variant="filled"
                color="secondary"
                label={label}
                name={name}
                usedAssets={usedAssets}
                required
                fullWidth
              />
            ) : (
              <Typography variant="body2">
                <Trans>{type} is not supported</Trans>
              </Typography>
            )}
          </Box>
          {onRemove && (
            <Box>
              <IconButton onClick={onRemove}>
                <Remove />
              </IconButton>
            </Box>
          )}
        </Flex>
      )}
      {caption && (
        <Typography variant="caption" color="textSecondary">
          {caption}
        </Typography>
      )}
    </Flex>
  );
}
