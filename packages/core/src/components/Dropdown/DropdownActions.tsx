import React, { cloneElement, type ReactNode } from 'react';
import { styled, alpha } from '@mui/material/styles';
import Button, { type ButtonProps } from '@mui/material/Button';
import Menu, { MenuProps } from '@mui/material/Menu';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';

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
      theme.palette.mode === 'light'
        ? 'rgb(55, 65, 81)'
        : theme.palette.grey[300],
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
          theme.palette.action.selectedOpacity
        ),
      },
    },
  },
}));

export type DropdownActionsProps = ButtonProps & {
  label?: ReactNode;
  toggle?: ReactNode;
  children: (props: { onClose: () => void }) => ReactNode;
};

export type DropdownActionsChildProps = {
  onClose: () => void;
};

export default function DropdownActions(props: DropdownActionsProps) {
  const { label, children, toggle, ...rest } = props;
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);
  const open = Boolean(anchorEl);
  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();

    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  function handlePreventDefault(event: any) {
    event.preventDefault();
    event.stopPropagation();
  }

  return (
    <div>
      {toggle ? cloneElement(toggle, {
        onClick: handleClick,
      }) : (
        <Button
          variant="contained"
          onClick={handleClick}
          endIcon={<KeyboardArrowDownIcon />}
          disableElevation
          {...rest}
        >
          {label}
        </Button>
      )}

      <StyledMenu anchorEl={anchorEl} open={open} onClose={handleClose} onClick={handlePreventDefault}>
        {children({ onClose: handleClose })}
      </StyledMenu>
    </div>
  );
}
