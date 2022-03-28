import React, { useMemo, useState, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { useToggle } from 'react-use';
import { Button, Menu, MenuItem, MenuProps } from '@mui/material';
import { ExpandMore } from '@mui/icons-material';

type DropdownOption = {
  value: string | number;
  label: ReactNode;
};

type Props = MenuProps & {
  selected: string | number;
  options: DropdownOption[];
  onSelect: (value: string) => void;
  defaultOpen?: boolean;
  placeholder?: ReactNode;
  startIcon?: ReactNode;
  children?: (option?: DropdownOption) => ReactNode;
};

export default function Dropdown(props: Props) {
  const { selected, options, defaultOpen, onSelect, placeholder, startIcon, children, open: _, ...rest } = props;
  const [open, toggleOpen] = useToggle(defaultOpen);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    setAnchorEl(event.currentTarget);
    toggleOpen();
  };

  const handleClose = () => {
    setAnchorEl(null);
    toggleOpen();
  };

  function handleSelect(option: DropdownOption) {
    toggleOpen();
    onSelect(option.value);
  }

  const selectedOption = useMemo(
    () => options.find(option => option.value === selected),
    [options, selected],
  );

  const value = selectedOption?.label ?? placeholder;

  return (
    <>
      <Button
        aria-controls="dropdown"
        aria-haspopup="true"
        onClick={handleClick}
        endIcon={<ExpandMore />}
        startIcon={startIcon}
      >
        {children ? children(selectedOption) : value}
      </Button>
      <Menu
        id="dropdown"
        anchorEl={anchorEl}
        onClose={handleClose}
        getContentAnchorEl={null}
        open={open}
        {...rest}
        keepMounted
      >
        {options.map((option) => (
          <MenuItem
            key={option.value}
            onClick={() => handleSelect(option)}
            selected={option.value === selected}
          >
            {option.label}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}

Dropdown.defaultProps = {
  defaultOpen: false,
  placeholder: <Trans>Select...</Trans>,
  startIcon: undefined,
  children: undefined,
};
