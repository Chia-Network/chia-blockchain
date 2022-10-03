import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, SettingsLabel } from '@chia/core';
import {
  FormGroup,
  FormControlLabel,
  Grid,
  Switch,
  Typography,
} from '@mui/material';
import useEnableAutoLogin from '../../hooks/useEnableAutoLogin';

export default function SettingsStartup() {
  const [enableAutoLogin, setEnableAutoLogin] = useEnableAutoLogin();

  return (
    <Grid container>
      <Grid item>
        <Flex flexDirection="column" gap={1}>
          <SettingsLabel>
            <Trans>Startup</Trans>
          </SettingsLabel>

          <FormGroup>
            <FormControlLabel
              control={
                <Switch
                  checked={enableAutoLogin}
                  onChange={() => setEnableAutoLogin(!enableAutoLogin)}
                  inputProps={{ 'data-testid': 'Enable_Auto_Login' }}
                 
                />
              }
              label={<Trans>Enable Auto Login</Trans>}
            />
          </FormGroup>
          <Typography variant="body2" color="textSecondary">
            <Trans>
              Changes will take effect the next time Chia is started
            </Trans>
          </Typography>
        </Flex>
      </Grid>
    </Grid>
  );
}
