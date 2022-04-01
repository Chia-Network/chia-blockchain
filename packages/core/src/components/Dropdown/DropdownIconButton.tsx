import React, { type ReactNode } from 'react';
import { IconButton, IconButtonProps } from '@mui/material';
import DropdownBase from './DropdownBase';

export type DropdownIconButtonProps = IconButtonProps & {
  icon: ReactNode;
  children: (options: { onClose: () => void, open: boolean }) => ReactNode;
};

export default function DropdownIconButton(props: DropdownIconButtonProps) {
  const { children, icon, ...rest } = props;

  return (
    <DropdownBase>
      {({ onClose, onToggle, open }) => ([
        <IconButton key="button" onClick={onToggle} {...rest}>
          {icon}
        </IconButton>,
        children({ onClose, open }),
      ])}
    </DropdownBase>
  );
}
