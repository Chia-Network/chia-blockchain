import React from 'react';
import { Trans } from '@lingui/macro';
import { useToggle } from 'react-use';
import { Button, Menu, MenuItem } from '@material-ui/core';
import { Translate, ExpandMore } from '@material-ui/icons';
import useLocale from '../../hooks/useLocale';

const locales: { [char: string]: string } = {
  en: 'English',
  sk: 'Slovenčina',
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

  function handleSelect(locale: string) {
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
        {locale in locales ? locales[locale] : 'Unknown'}
      </Button>
      <Menu
        id="simple-menu"
        anchorEl={anchorEl}
        keepMounted
        open={open}
        onClose={handleClose}
      >
        {Object.keys(locales).forEach((locale) => (
          <MenuItem onClick={() => handleSelect(locale)}>{locales[locale]}</MenuItem>
        ))}
        <MenuItem
          component="a"
          href="https://github.com/Chia-Network/chia-blockchain/tree/master/electron-react/src/locales/README.md"
          target="_blank"
          onClick={() => handleClose()}
        >
          <Trans id="LocaleToggle.helpToTranslate">
            Help to translate
          </Trans>
        </MenuItem>
      </Menu>
    </>
  );
}
