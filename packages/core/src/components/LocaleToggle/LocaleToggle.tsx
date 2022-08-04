import React, { useContext, useMemo } from 'react';
import { Trans, t } from '@lingui/macro';
import { useToggle } from 'react-use';
import { Divider, Menu, MenuItem } from '@mui/material';
import { Translate, ExpandMore } from '@mui/icons-material';
import useLocale from '../../hooks/useLocale';
import useOpenExternal from '../../hooks/useOpenExternal';
import Button from '../Button';
import { LocaleContext } from '../LocaleProvider';

export default function LocaleToggle(props) {
  const { ...rest } = props;
  const { locales } = useContext(LocaleContext);
  const [currentLocale, setLocale] = useLocale();
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

    openExternal(
      'https://github.com/Chia-Network/chia-blockchain-gui/tree/main/src/locales/README.md',
    );
  }

  const localeData = useMemo(
    () => locales.find((item) => item.locale === currentLocale),
    [currentLocale, locales],
  );

  const currentLocaleLabel = localeData?.label ?? t`Unknown`;

  return (
    <>
      <Button
        aria-controls="menu"
        aria-haspopup="true"
        onClick={handleClick}
        startIcon={<Translate />}
        endIcon={<ExpandMore />}
        data-testid="LocaleToggle-dropdown"
        {...rest}
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
        <MenuItem onClick={handleHelpTranslate}>
          <Trans>Help translate</Trans>
        </MenuItem>
        <Divider />
        {locales.map((item) => (
          <MenuItem
            key={item.locale}
            onClick={() => handleSelect(item.locale)}
            selected={item.locale === currentLocale}
            data-testid={`LocaleToggle-locale-${item.locale}`}
          >
            {item.label}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}
