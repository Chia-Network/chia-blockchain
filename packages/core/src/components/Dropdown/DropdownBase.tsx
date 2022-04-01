import React, { type ReactNode } from 'react';
import { styled, alpha } from '@mui/material/styles';
import { Box } from '@mui/material';
import Menu, { MenuProps } from '@mui/material/Menu';

const StyledMenu = styled((props: MenuProps) => (
  <Menu
    elevation={0}
    anchorOrigin={{
      vertical: 'bottom',
      horizontal: 'right',
    }}
    transformOrigin={{
      vertical: 'top',
      horizontal: 'right',
    }}
    {...props}
  />
))(({ theme }) => ({
  '& .MuiPaper-root': {
    borderRadius: 6,
    marginTop: theme.spacing(1),
    minWidth: 180,
    color:
      theme.palette.mode === 'light' ? 'rgb(55, 65, 81)' : theme.palette.grey[300],
    boxShadow:
      'rgb(255, 255, 255) 0px 0px 0px 0px, rgba(0, 0, 0, 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1) 0px 10px 15px -3px, rgba(0, 0, 0, 0.05) 0px 4px 6px -2px',
    '& .MuiMenu-list': {
      padding: '4px 0',
    },
    '& .MuiMenuItem-root': {
      '& .MuiSvgIcon-root': {
        fontSize: 18,
        color: theme.palette.text.secondary,
        marginRight: theme.spacing(1.5),
      },
      '&:active': {
        backgroundColor: alpha(
          theme.palette.primary.main,
          theme.palette.action.selectedOpacity,
        ),
      },
    },
  },
}));

export type DropdownBaseProps = {
  children: (props: { 
    onClose: () => void, 
    onOpen: (event: React.MouseEvent<HTMLElement>) => void,
    onToggle: (event: React.MouseEvent<HTMLElement>) => void,
    open: boolean;
  }) => [ReactNode, ReactNode];
};

export default function DropdownActions(props: DropdownBaseProps) {
  const { children } = props;
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);
  const open = Boolean(anchorEl);
  const handleOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };
  const handleClose = () => {
    setAnchorEl(null);
  };

  function handleToggle(event: React.MouseEvent<HTMLElement>) {
    if (open) {
      handleClose();
    } else {
      handleOpen(event);
    }
  }

  const [item, menuItems] = children({ 
    onClose: handleClose,
    onOpen: handleOpen,
    onToggle: handleToggle,
    open,
  });

  return (
    <Box>
      {item}
      <StyledMenu
        anchorEl={anchorEl}
        open={open}
        onClose={handleClose}
      >
        {menuItems}
      </StyledMenu>
    </Box>
  );
}