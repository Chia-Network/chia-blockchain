import React, { ReactElement, ReactNode } from 'react';
import { get } from 'lodash';
import { Controller, ControllerProps, useFormContext } from 'react-hook-form';
import {
  TextField as MaterialTextField,
  TextFieldProps as MaterialTextFieldProps,
} from '@material-ui/core';

export type ReactRules<T> =
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

export type TextFieldProps = MaterialTextFieldProps & {
  hideError?: boolean;
  name: string;
  rules?: ReactRules<typeof MaterialTextField>;
};

export default function TextField(props: TextFieldProps): JSX.Element {
  const { name, ...rest } = props;
  const { control, errors } = useFormContext();
  const errorMessage = get(errors, name);

  return (
    // @ts-ignore
    <Controller
      as={MaterialTextField}
      name={name}
      control={control}
      error={!!errorMessage}
      helperText={errorMessage?.message}
      {...rest}
    />
  );
}
