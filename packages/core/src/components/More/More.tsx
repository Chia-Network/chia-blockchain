import React, { ReactNode } from 'react';
import { Menu, MenuProps } from '../Menu';
import { MoreVert as MoreVertIcon } from '@mui/icons-material';
import IconButton from '../IconButton';

export type MoreProps = MenuProps & {
  children?: ReactNode;
  disabled?: boolean;
};

export default function More(props: MoreProps) {
  const { children, disabled = false, ...rest } = props;
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);
  const open = !!anchorEl;

  function handleClick(event: React.MouseEvent<HTMLElement>) {
    setAnchorEl(event.currentTarget);
  }

  function handleClose() {
    setAnchorEl(null);
  }

  return (
    <>
      <IconButton
        aria-label="more"
        aria-haspopup="true"
        onClick={handleClick}
        disabled={disabled}
      >
        <MoreVertIcon />
      </IconButton>
      <Menu
        anchorEl={anchorEl}
        keepMounted
        onClose={handleClose}
        {...rest}
        open={open}
      >
        {children}
      </Menu>
    </>
  );
}
