import React, { ChangeEvent, ReactElement, ReactNode, forwardRef } from 'react';
import { Controller, ControllerProps, useFormContext } from 'react-hook-form';
import {
  RadioGroup as MaterialRadioGroup,
  RadioGroupProps,
} from '@material-ui/core';

type ReactRules<T> =
  | ControllerProps<ReactElement<T>>['rules']
  | {
      min?:
        | number
        | string
        | {
            value: number;
            message: ReactNode;
          };
      max?:
        | number
        | string
        | {
            value: number;
            message: ReactNode;
          };
      minLength?:
        | number
        | string
        | {
            value: number;
            message: ReactNode;
          };
      maxLength?:
        | number
        | string
        | {
            value: number;
            message: ReactNode;
          };
      required?:
        | boolean
        | {
            value: boolean;
            message: ReactNode;
          };
    };

type Props = RadioGroupProps & {
  hideError?: boolean;
  name: string;
  rules?: ReactRules<typeof MaterialRadioGroup>;
  boolean?: boolean;
};

const ParseBoolean = forwardRef((props: RadioGroupProps, ref) => {
  const { onChange, ...rest } = props;
  const { name } = rest;
  const { setValue } = useFormContext();

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const value = e.target.value === 'true';
    // @ts-ignore
    onChange(e, e.target.value === 'true');

    if (name) {
      setValue(name, value);
    }
  }

  return <MaterialRadioGroup onChange={handleChange} ref={ref} {...rest} />;
});

export default function RadioGroup(props: Props) {
  const { name, boolean, ...rest } = props;
  const { control } = useFormContext();

  return (
    // @ts-ignore
    <Controller
      name={name}
      control={control}
      render={({ field }) => (boolean ? <ParseBoolean {...field} {...rest} /> :  <MaterialRadioGroup {...field} {...rest} /> )}
    />
  );
}
