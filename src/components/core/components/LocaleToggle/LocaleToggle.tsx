import React from 'react';
import { Trans } from '@lingui/macro';
import { useToggle } from 'react-use';
import { Button, Menu, MenuItem } from '@material-ui/core';
import { Translate, ExpandMore } from '@material-ui/icons';
import useLocale from '../../../../hooks/useLocale';
import useOpenExternal from '../../../../hooks/useOpenExternal';

// https://www.codetwo.com/admins-blog/list-of-office-365-language-id/
const locales: { [char: string]: string } = {
  'da-DK': 'Dansk',
  'de-DE': 'Deutsch',
  'en-US': 'English',
  'en-AU': 'English (Australia)',
  'en-PT': 'English (Pirate)',
  'es-ES': 'Español',
  'fr-FR': 'Français',
  'it-IT': 'Italiano',
  'ja-JP': '日本語 (日本)',
  'nl-NL': 'Nederlands',
  'pl-PL': 'Polski',
  'pt-PT': 'Português',
  'pt-BR': 'Português (Brasil)',
  'ro-RO': 'Română',
  'ru-RU': 'Русский',
  'sk-SK': 'Slovenčina',
  'fi-FI': 'Suomi',
  'sv-SE': 'Svenska',
  // 'vi-VN': 'Tiếng Việt',
  'zh-TW': '中文',
  'zh-CN': '中文 (中国)',
};

export default function LocaleToggle() {
  const [currentLocale, setLocale] = useLocale('en-US');
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

    openExternal('https://github.com/Chia-Network/chia-blockchain-gui/tree/main/src/locales/README.md');
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
          <Trans>Help translate</Trans>
        </MenuItem>
      </Menu>
    </>
  );
}
