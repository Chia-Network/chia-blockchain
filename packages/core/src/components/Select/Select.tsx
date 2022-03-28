import React from 'react';
import { get } from 'lodash';
import { Controller, useFormContext } from 'react-hook-form';
import { Select as MaterialSelect, SelectProps } from '@mui/material';

type Props = SelectProps & {
  hideError?: boolean;
  name: string;
};

export default function Select(props: Props) {
  const { name: controllerName, value: controllerValue, children, ...rest } = props;
  const { control, errors } = useFormContext();
  const errorMessage = get(errors, controllerName);

  return (
    // @ts-ignore
    <Controller
      name={controllerName}
      control={control}
      render={({ field: { onChange, onBlur, value, name, ref } }) => (
        <MaterialSelect
          onChange={(event, ...args) => {
            onChange(event, ...args);
            if (props.onChange) {
              props.onChange(event, ...args);
            }
          }}
          onBlur={onBlur}
          value={value}
          name={name}
          ref={ref}
          error={!!errorMessage}
          {...rest}
        >
          {children}
        </MaterialSelect>
      )}
    />
  );
}
