import React, { useMemo } from 'react';
import { Trans, t } from '@lingui/macro';
import { useToggle } from 'react-use';
import { Button, Menu, MenuItem } from '@material-ui/core';
import { Translate, ExpandMore } from '@material-ui/icons';
import useLocale from '../../../../hooks/useLocale';
import useOpenExternal from '../../../../hooks/useOpenExternal';

type Props = {
  defaultLocale: string;
  locales: [{
    locale: string;
    label: string;
  }];
};

export default function LocaleToggle(props: Props) {
  const { defaultLocale, locales } = props;
  const [currentLocale, setLocale] = useLocale(defaultLocale);
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

  const localeData = useMemo(
    () => locales.find((item)=> item.locale === currentLocale), 
    [currentLocale, locales],
  );

  const currentLocaleLabel = localeData?.label ?? t`Unknown`;

  return (
    <>
      <Button
        aria-controls="simple-menu"
        aria-haspopup="true"
        onClick={handleClick}
        startIcon={<Translate />}
        endIcon={<ExpandMore />}
      >
        {currentLocaleLabel}
      </Button>
      <Menu
        id="simple-menu"
        anchorEl={anchorEl}
        keepMounted
        open={open}
        onClose={handleClose}
      >
        {locales.map((item) => (
          <MenuItem
            key={item.locale}
            onClick={() => handleSelect(item.locale)}
            selected={item.locale === currentLocale}
          >
            {item.label}
          </MenuItem>
        ))}
        <MenuItem onClick={handleHelpTranslate}>
          <Trans>Help translate</Trans>
        </MenuItem>
      </Menu>
    </>
  );
}
