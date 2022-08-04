import React, { ReactElement, ReactNode } from 'react';
import { get } from 'lodash';
import { Controller, ControllerProps, useFormContext } from 'react-hook-form';
import {
  TextField as MaterialTextField,
  TextFieldProps as MaterialTextFieldProps,
} from '@mui/material';

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
  "data-testid"?: string;
};

export default function TextField(props: TextFieldProps): JSX.Element {
  const { name, onChange: baseOnChange, "data-testid": dataTestid, inputProps, ...rest } = props;
  const { control, errors } = useFormContext();
  const errorMessage = get(errors, name);

  return (
    // @ts-ignore
    <Controller
      name={name}
      control={control}
      render={({ field: { onChange, value } }) => {
        function handleChange(...args) {
          onChange(...args);

          if (baseOnChange) {
            baseOnChange(...args);
          }
        }

        return (
          <MaterialTextField
            value={value}
            onChange={handleChange}
            error={!!errorMessage}
            helperText={errorMessage?.message}
            inputProps={{
              "data-testid": dataTestid,
              ...inputProps,
            }}
            {...rest}
          />
        );
      }}
    />
  );
}
