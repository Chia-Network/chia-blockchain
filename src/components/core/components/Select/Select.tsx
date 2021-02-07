import React from 'react';
import { get } from 'lodash';
import { Controller, useFormContext } from 'react-hook-form';
import { Select as MaterialSelect, SelectProps } from '@material-ui/core';

type Props = SelectProps & {
  hideError?: boolean,
  name: string,
};

export default function Select(props: Props) {
  const { name, onChange, ...rest } = props;
  const { control, errors } = useFormContext();
  const errorMessage = get(errors, name);

  return (
    // @ts-ignore
    <Controller
      as={MaterialSelect}
      name={name}
      control={control}
      error={!!errorMessage}
      {...rest}
    />
  );
}
