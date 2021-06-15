import React from 'react';
import { Trans } from '@lingui/macro';
import { InputAdornment, FormControl, FormHelperText } from '@material-ui/core';
import { useWatch, useFormContext } from 'react-hook-form';
import TextField, { TextFieldProps } from '../TextField';
import { chia_to_mojo } from '../../../../util/chia';
import useCurrencyCode from '../../../../hooks/useCurrencyCode';
import FormatLargeNumber from '../FormatLargeNumber';

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
      {mojo > 1 && (
        <FormHelperText>
          <FormatLargeNumber value={mojo} />
          {mojo > 1 ? 'mojos' : 'mojo'}
        </FormHelperText>
      )}
    </FormControl>
  );
}

Fee.defaultProps = {
  label: <Trans>Fee</Trans>,
  name: 'fee',
};
