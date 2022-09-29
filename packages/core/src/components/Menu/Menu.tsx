import React, {
  createContext,
  forwardRef,
  SyntheticEvent,
  useCallback,
  useMemo,
} from 'react';
import { Menu as BaseMenu } from '@mui/material';
import type { MenuProps } from '@mui/material';

export interface MenuContextInterface {
  close: (event: SyntheticEvent<HTMLElement>, reason: any) => void;
}

export const MenuContext = createContext<MenuContextInterface | undefined>(
  undefined
);

export { MenuProps };

function Menu(props: MenuProps, ref: any) {
  const { children, onClose, ...rest } = props;

  const handleClose = useCallback(
    (
      event: SyntheticEvent<HTMLElement>,
      reason: 'escapeKeyDown' | 'backdropClick' | 'tabKeyDown' | 'menuItemClick'
    ) => {
      event.stopPropagation();
      onClose?.(event, reason as any);
    },
    [onClose]
  );

  const context = useMemo(
    () => ({
      close: handleClose,
    }),
    [handleClose]
  );

  return (
    <MenuContext.Provider value={context}>
      <BaseMenu {...rest} onClose={handleClose} ref={ref}>
        {children}
      </BaseMenu>
    </MenuContext.Provider>
  );
}

export default forwardRef(Menu);
