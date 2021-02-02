import React from 'react';
import { Trans } from '@lingui/macro';
import { useToggle } from 'react-use';
import { Button, Menu, MenuItem } from '@material-ui/core';
import { Translate, ExpandMore } from '@material-ui/icons';
import useLocale from '../../../../hooks/useLocale';
import useOpenExternal from '../../../../hooks/useOpenExternal';

// https://www.codetwo.com/admins-blog/list-of-office-365-language-id/
const locales: { [char: string]: string } = {
  en: 'English',
  sk: 'Slovenčina',
  "zh-CN": '中文 (中国)',
};

export default function LocaleToggle() {
  const [currentLocale, setLocale] = useLocale('en');
  const [open, toggleOpen] = useToggle(false);
  const openExternal = useOpenExternal();

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

  function handleHelpTranslate() {
    handleClose();

    openExternal('https://github.com/Chia-Network/chia-blockchain/tree/main/electron-react/src/locales/README.md');
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
        {currentLocale in locales ? locales[currentLocale] : 'Unknown'}
      </Button>
      <Menu
        id="simple-menu"
        anchorEl={anchorEl}
        keepMounted
        open={open}
        onClose={handleClose}
      >
        {Object.keys(locales).map((locale) => (
          <MenuItem
            key={locale}
            onClick={() => handleSelect(locale)}
            selected={locale === currentLocale}
          >
            {locales[locale]}
          </MenuItem>
        ))}
        <MenuItem onClick={handleHelpTranslate}>
          <Trans id="LocaleToggle.helpToTranslate">Help translate</Trans>
        </MenuItem>
      </Menu>
    </>
  );
}
