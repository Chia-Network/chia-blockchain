import React from 'react';
import { useToggle } from 'react-use';
import { Button, Menu, MenuItem } from '@material-ui/core';
import { Translate, ExpandMore } from '@material-ui/icons';
import useLocale, { Locales } from "../../hooks/useLocale";

const locales = {
  en: 'English',
  sk: 'Slovak',
};

export default function LocaleToggle() {
  const [locale, setLocale] = useLocale('en');
  const [open, toggleOpen] = useToggle(false);

  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);

  const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    setAnchorEl(event.currentTarget);
    toggleOpen();
  };

  const handleClose = () => {
    setAnchorEl(null);
    toggleOpen();
  };

  function handleSelect(locale: Locales) {
    setLocale(locale);
    toggleOpen();
  }

  return (
    <>
      <Button 
        aria-controls="simple-menu" 
        aria-haspopup="true" 
        onClick={handleClick}
        startIcon={<Translate />}
        endIcon={<ExpandMore />}
      >
        {locales[locale]}
      </Button>
      <Menu
        id="simple-menu"
        anchorEl={anchorEl}
        keepMounted
        open={open}
        onClose={handleClose}
      >
        <MenuItem onClick={() => handleSelect('en')}>English</MenuItem>
        <MenuItem onClick={() => handleSelect('sk')}>Slovak</MenuItem>
        <MenuItem >Help to translate</MenuItem>
      </Menu>
    </>
  );
}