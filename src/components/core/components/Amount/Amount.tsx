import React, { ReactNode } from 'react';
import { Trans, Plural } from '@lingui/macro';
import { Box, InputAdornment, FormControl, FormHelperText } from '@material-ui/core';
import { useWatch, useFormContext } from 'react-hook-form';
import TextField, { TextFieldProps } from '../TextField';
import { chia_to_mojo } from '../../../../util/chia';
import useCurrencyCode from '../../../../hooks/useCurrencyCode';
import FormatLargeNumber from '../FormatLargeNumber';
import Flex from '../Flex';

export type AmountProps = TextFieldProps & {
  children?: (props: { mojo: number, value: string | undefined }) => ReactNode;
  name?: string;
};

export default function Amount(props: AmountProps) {
  const { children, name, variant, fullWidth, ...rest } = props;
  const { control } = useFormContext();
  const currencyCode = useCurrencyCode();

  const value = useWatch<string>({
    control,
    name,
  });

  const mojo = chia_to_mojo(value);

  return (
    <FormControl
      variant={variant}
      fullWidth={fullWidth}
    >
      <TextField
        name={name}
        variant={variant}
        type="text"
        InputProps={{
          endAdornment: <InputAdornment position="end">{currencyCode}</InputAdornment>,
        }}
        {...rest}
      />
      {!!mojo && (
        <FormHelperText>
          <Flex alignItems="center" gap={2}>
            <Flex flexGrow={1} gap={1}>
              <FormatLargeNumber value={mojo} />
              <Box>
                <Plural value={mojo} one="mojo" other="mojos" />
              </Box>
            </Flex>
            {children && children({
              mojo,
              value,
            })}
          </Flex>
        </FormHelperText>
      )}
    </FormControl>
  );
}

Amount.defaultProps = {
  label: <Trans>Amount</Trans>,
  name: 'amount',
  children: undefined,
};
