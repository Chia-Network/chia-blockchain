import React, { ReactNode } from 'react';
import { Trans, Plural } from '@lingui/macro';
import NumberFormat from 'react-number-format';
import {
  Box,
  InputAdornment,
  FormControl,
  FormHelperText,
} from '@material-ui/core';
import { useWatch, useFormContext } from 'react-hook-form';
import TextField, { TextFieldProps } from '../TextField';
import chiaToMojo from '../../utils/chiaToMojo';
import catToMojo from '../../utils/catToMojo';
import useCurrencyCode from '../../hooks/useCurrencyCode';
import FormatLargeNumber from '../FormatLargeNumber';
import Flex from '../Flex';

interface NumberFormatCustomProps {
  inputRef: (instance: NumberFormat | null) => void;
  onChange: (event: { target: { name: string; value: string } }) => void;
  name: string;
}

function NumberFormatCustom(props: NumberFormatCustomProps) {
  const { inputRef, onChange, ...other } = props;

  function handleChange(values: Object) {
    onChange(values.value);
  }

  return (
    <NumberFormat
      {...other}
      getInputRef={inputRef}
      onValueChange={handleChange}
      thousandSeparator
      allowNegative={false}
      isNumericString
    />
  );
}

export type AmountProps = TextFieldProps & {
  children?: (props: { mojo: number; value: string | undefined }) => ReactNode;
  name?: string;
  symbol?: string; // if set, overrides the currencyCode. empty string is allowed
  showAmountInMojos?: boolean; // if true, shows the mojo amount below the input field
  feeMode?: boolean // if true, amounts are expressed in mojos used to set a transaction fee
};

export default function Amount(props: AmountProps) {
  const { children, name, symbol, showAmountInMojos, variant, fullWidth, ...rest } = props;
  const { control } = useFormContext();
  const defaultCurrencyCode = useCurrencyCode();

  const value = useWatch<string>({
    control,
    name,
  });

  const currencyCode = symbol === undefined ? defaultCurrencyCode : symbol;
  const isChiaCurrency = ['XCH', 'TXCH'].includes(currencyCode);
  const mojo = isChiaCurrency ? chiaToMojo(value) : catToMojo(value);

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
          },
          endAdornment: (
            <InputAdornment position="end">{currencyCode}</InputAdornment>
          ),
        }}
        {...rest}
      />
        <FormHelperText component='div' >
          <Flex alignItems="center" gap={2}>
            {showAmountInMojos && (
              <Flex flexGrow={1} gap={1}>
                {!!mojo && (
                  <>
                    <FormatLargeNumber value={mojo} />
                    <Box>
                      <Plural value={mojo} one="mojo" other="mojos" />
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
  feeMode: false,
};
