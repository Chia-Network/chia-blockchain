import React, { ReactNode } from 'react';
import { Menu } from '@material-ui/core';
import { MoreVert as MoreVertIcon } from '@material-ui/icons';
import IconButton from '../IconButton';

type Props = {
  children: ({ onClose }: { onClose: () => void }) => ReactNode,
};

export default function More(props: Props) {
  const { children, ...rest } = props;
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
        {children({
          onClose: handleClose
        })}
      </Menu>
    </>
  );
}
