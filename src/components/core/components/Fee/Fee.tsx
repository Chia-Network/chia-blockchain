import React from 'react';
import { Trans, Plural } from '@lingui/macro';
import { Box, InputAdornment, FormControl, FormHelperText } from '@material-ui/core';
import { useWatch, useFormContext } from 'react-hook-form';
import styled from 'styled-components';
import TextField, { TextFieldProps } from '../TextField';
import { chia_to_mojo } from '../../../../util/chia';
import useCurrencyCode from '../../../../hooks/useCurrencyCode';
import StateColor from '../../constants/StateColor';
import FormatLargeNumber from '../FormatLargeNumber';
import Flex from '../Flex';

const StyledWarning = styled(Box)`
  color: ${StateColor.WARNING};
`;

type FeeProps = TextFieldProps & {
  name: string;
};

export default function Fee(props: FeeProps) {
  const { name, variant, fullWidth, ...rest } = props;
  const { control } = useFormContext();
  const currencyCode = useCurrencyCode();

  const fee = useWatch<boolean>({
    control,
    name,
  });

  const mojo = chia_to_mojo(fee);

  const isHigh = mojo >= 1000;
  const isLow = mojo !== 0 && mojo < 1;

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
            {isHigh && (
              <StyledWarning>
                <Trans>Value is too high</Trans>
              </StyledWarning>
            )}
            {isLow && (
              <StyledWarning>
                <Trans>Incorrect value</Trans>
              </StyledWarning>
            )}
          </Flex>
        </FormHelperText>
      )}
    </FormControl>
  );
}

Fee.defaultProps = {
  label: <Trans>Fee</Trans>,
  name: 'fee',
};
