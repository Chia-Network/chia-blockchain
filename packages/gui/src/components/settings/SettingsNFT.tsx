import React from 'react';
import { Trans } from '@lingui/macro';
import { Grid } from '@mui/material';
import { Flex, SettingsLabel } from '@chia/core';
import { Switch, FormGroup, FormControlLabel } from '@mui/material';
import useHideObjectionableContent from '../../hooks/useHideObjectionableContent';

export default function SettingsGeneral() {
  const [hideObjectionableContent, setHideObjectionableContent] =
    useHideObjectionableContent();

  function handleChangeHideObjectionableContent(
    event: React.ChangeEvent<HTMLInputElement>,
  ) {
    setHideObjectionableContent(event.target.checked);
  }

  return (
    <Grid container>
      <Grid item xs={12} sm={6} lg={3}>
        <Flex flexDirection="column" gap={1}>
          <SettingsLabel>
            <Trans>Gallery Management</Trans>
          </SettingsLabel>

          <FormGroup>
            <FormControlLabel
              control={
                <Switch
                  checked={hideObjectionableContent}
                  onChange={handleChangeHideObjectionableContent}
                />
              }
              label={<Trans>Hide objectionable content</Trans>}
            />
          </FormGroup>
        </Flex>
      </Grid>
    </Grid>
  );
}
