import React, { useContext, forwardRef } from 'react';
import {
  MenuItem as BaseMenuItem,
  type MenuItemProps as BaseMenuItemsProps,
} from '@mui/material';
import { MenuContext, type MenuContextInterface } from '../Menu';

export type MenuItemProps = BaseMenuItemsProps & {
  close?: true | 'after';
};

function MenuItem(props: MenuItemProps, ref: any) {
  const { onClick, close, ...rest } = props;

  const menuContext: MenuContextInterface | undefined = useContext(MenuContext);

  async function handleClick(event: React.MouseEvent<HTMLLIElement>) {
    if (close === true) {
      menuContext?.close(event, 'menuItemClick');
    }

    await onClick?.(event);

    if (close === 'after') {
      menuContext?.close(event, 'menuItemClick');
    }
  }

  return <BaseMenuItem {...rest} onClick={handleClick} ref={ref} />;
}

export default forwardRef(MenuItem);
