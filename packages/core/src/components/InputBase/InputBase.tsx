import React, { forwardRef, ReactElement, type ReactNode } from 'react';
import { get } from 'lodash';
import { Controller, ControllerProps, useFormContext } from 'react-hook-form';
import { InputBase as MaterialInputBase, InputBaseProps } from '@mui/material';

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

type Props = InputBaseProps & {
  hideError?: boolean;
  name: string;
  rules?: ReactRules<typeof MaterialInputBase>;
};

function InputBase(props: Props, ref: any) {
  const { name, ...rest } = props;
  const { control, errors } = useFormContext();
  const errorMessage = get(errors, name);

  return (
    // @ts-ignore
    <Controller
      name={name}
      control={control}
      render={({ field }) => (
        <MaterialInputBase
          error={!!errorMessage}
          {...rest}
          {...field}
          ref={ref}
        />
      )}
    />
  );
}

export default forwardRef(InputBase);
