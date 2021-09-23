import React from 'react';
import Button from '../Button';
import type { ButtonProps } from '../Button';
import { Check as CheckIcon } from '@material-ui/icons';

type Props = ButtonProps & {
  selected?: boolean;
};

export default function ButtonSelected(props: Props) {
  const { selected, children, ...rest } = props;
  const color = selected ? 'primary' : 'default';

  return (
    <Button color={color} {...rest}>
      {selected ? (
        <>
          <CheckIcon /> {children}
        </>
      ) : (
        children
      )}
    </Button>
  );
}
