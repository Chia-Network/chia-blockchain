import React, { ReactNode } from 'react';
import { Menu, MenuProps } from '@material-ui/core';
import { MoreVert as MoreVertIcon } from '@material-ui/icons';
import IconButton from '../IconButton';

// anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
// transformOrigin={{ vertical: "top", horizontal: "right" }}

type Props = MenuProps & {
  children: ({ onClose }: { onClose: () => void }) => ReactNode;
  disabled?: boolean;
};

export default function More(props: Props) {
  const { children, disabled, ...rest } = props;
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
      <IconButton aria-label="more" aria-haspopup="true" onClick={handleClick} disabled={disabled}>
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
          onClose: handleClose,
        })}
      </Menu>
    </>
  );
}

More.defaultProps = {
  disabled: false,
};