import React, { type ReactNode } from 'react';
import { Trans, Plural } from '@lingui/macro';
import BigNumber from 'bignumber.js';
import {
  Box,
  InputAdornment,
  FormControl,
  FormHelperText,
} from '@mui/material';
import { useWatch, useFormContext } from 'react-hook-form';
import TextField, { TextFieldProps } from '../TextField';
import chiaToMojo from '../../utils/chiaToMojo';
import catToMojo from '../../utils/catToMojo';
import useCurrencyCode from '../../hooks/useCurrencyCode';
import FormatLargeNumber from '../FormatLargeNumber';
import Flex from '../Flex';
import NumberFormatCustom from './NumberFormatCustom';

export type AmountProps = TextFieldProps & {
  children?: (props: {
    mojo: BigNumber;
    value: string | undefined;
  }) => ReactNode;
  name?: string;
  symbol?: string; // if set, overrides the currencyCode. empty string is allowed
  showAmountInMojos?: boolean; // if true, shows the mojo amount below the input field
  // feeMode?: boolean; // if true, amounts are expressed in mojos used to set a transaction fee
  'data-testid'?: string;
};

export default function Amount(props: AmountProps) {
  const {
    children,
    name,
    symbol,
    showAmountInMojos,
    variant,
    fullWidth,
    'data-testid': dataTestid,
    ...rest
  } = props;
  const { control } = useFormContext();
  const defaultCurrencyCode = useCurrencyCode();

  const value = useWatch<string>({
    control,
    name,
  });

  const correctedValue = value && value[0] === '.' ? `0${value}` : value;

  const currencyCode = symbol === undefined ? defaultCurrencyCode : symbol;
  const isChiaCurrency = ['XCH', 'TXCH'].includes(currencyCode);
  const mojo = isChiaCurrency
    ? chiaToMojo(correctedValue)
    : catToMojo(correctedValue);

  return (
    <FormControl variant={variant} fullWidth={fullWidth}>
      <TextField
        name={name}
        variant={variant}
        autoComplete="off"
        InputProps={{
          spellCheck: false,
          inputComponent: NumberFormatCustom as any,
          inputProps: {
            decimalScale: isChiaCurrency ? 12 : 3,
            'data-testid': dataTestid,
          },
          endAdornment: (
            <InputAdornment position="end">{currencyCode}</InputAdornment>
          ),
        }}
        {...rest}
      />
      <FormHelperText component="div">
        <Flex alignItems="center" gap={2}>
          {showAmountInMojos && (
            <Flex flexGrow={1} gap={1}>
              {!mojo.isZero() && (
                <>
                  <FormatLargeNumber value={mojo} />
                  <Box>
                    <Plural value={mojo.toNumber()} one="mojo" other="mojos" />
                  </Box>
                </>
              )}
            </Flex>
          )}
          {children &&
            children({
              mojo,
              value,
            })}
        </Flex>
      </FormHelperText>
    </FormControl>
  );
}

Amount.defaultProps = {
  label: <Trans>Amount</Trans>,
  name: 'amount',
  children: undefined,
  showAmountInMojos: true,
  // feeMode: false,
};
