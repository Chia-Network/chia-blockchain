import React, { ChangeEvent, ReactNode } from 'react';
import { Controller, useFormContext } from 'react-hook-form';
import { Checkbox as MaterialCheckbox, CheckboxProps } from '@material-ui/core';

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

type Props = {
  name: string;
  label?: ReactNode;
  value?: any;
};

export default function Checkbox(props: Props): JSX.Element {
  const { name, ...rest } = props;
  const { control } = useFormContext();

  return (
    // @ts-ignore
    <Controller as={<ParseBoolean />} name={name} control={control} {...rest} />
  );
}

Checkbox.defaultProps = {
  value: true,
};
