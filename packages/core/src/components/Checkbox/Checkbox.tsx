import React, { ChangeEvent, type ReactNode, forwardRef } from 'react';
import { Controller, useFormContext } from 'react-hook-form';
import {
  Checkbox as MaterialCheckbox,
  type CheckboxProps as BaseCheckboxProps,
} from '@mui/material';

const ParseBoolean = (props: CheckboxProps) => {
  const { onChange, ...rest } = props;
  const { name } = rest;
  const { setValue } = useFormContext();

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const value = !!e.target.checked;
    // @ts-ignore
    onChange(e, value);

    if (name) {
      setValue(name, value);
    }
  }

  return <MaterialCheckbox onChange={handleChange} {...rest} />;
};

export type CheckboxProps = BaseCheckboxProps & {
  name: string;
  label?: ReactNode;
  value?: any;
};

function Checkbox(props: CheckboxProps, ref: any) {
  const { name, value = true, ...rest } = props;
  const { control } = useFormContext();

  return (
    // @ts-ignore
    <Controller
      name={name}
      control={control}
      render={({ field }) => (
        <ParseBoolean {...field} value={value} {...rest} ref={ref} />
      )}
    />
  );
}

export default forwardRef(Checkbox);
