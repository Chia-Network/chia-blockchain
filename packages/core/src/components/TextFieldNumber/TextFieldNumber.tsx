import React, { type ReactNode } from 'react';
import { InputAdornment, FormControl, FormHelperText } from '@mui/material';
import { useWatch, useFormContext } from 'react-hook-form';
import TextField, { TextFieldProps } from '../TextField';
import NumberFormatCustom from './NumberFormatCustom';

export type TextFieldNumberProps = TextFieldProps & {
  children?: (props: { mojo: number; value: string | undefined }) => ReactNode;
  name?: string;
  currency?: ReactNode;
};

export default function TextFieldNumber(props: TextFieldNumberProps) {
  const { children, name, variant, fullWidth, currency, ...rest } = props;
  const { control } = useFormContext();

  const value = useWatch<string>({
    control,
    name,
  });

  return (
    <FormControl variant={variant} fullWidth={fullWidth}>
      <TextField
        name={name}
        variant={variant}
        autoComplete="off"
        InputProps={{
          spellCheck: false,
          inputComponent: NumberFormatCustom as any,
          endAdornment: currency ? (
            <InputAdornment position="end">{currency}</InputAdornment>
          ) : undefined,
        }}
        {...rest}
      />
      <FormHelperText component="div">
        {children &&
          children({
            value,
          })}
      </FormHelperText>
    </FormControl>
  );
}
