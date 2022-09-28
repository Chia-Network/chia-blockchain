import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { Box, Typography, ListItemIcon, Chip } from '@mui/material';
import {
  Delete as DeleteIcon,
  Visibility as VisibilityIcon,
  Edit as EditIcon,
} from '@mui/icons-material';
import type { KeyData } from '@chia/api';
import { useGetLoggedInFingerprintQuery } from '@chia/api-react';
import SelectKeyDetailDialog from './SelectKeyDetailDialog';
import CardListItem from '../../components/CardListItem';
import More from '../../components/More';
import { MenuItem } from '../../components/MenuItem';
import Flex from '../../components/Flex';
import useOpenDialog from '../../hooks/useOpenDialog';
import SelectKeyRenameForm from './SelectKeyRenameForm';
import WalletStatus from './WalletStatus';
import WalletDeleteDialog from './WalletDeleteDialog';

type SelectKeyItemProps = {
  keyData: KeyData;
  index: number;
  disabled?: boolean;
  loading?: boolean;
  onSelect: (fingerprint: number) => void;
};

export default function SelectKeyItem(props: SelectKeyItemProps) {
  const { keyData, onSelect, disabled, loading, index } = props;
  const openDialog = useOpenDialog();
  const [isRenaming, setIsRenaming] = useState<boolean>(false);

  const { data: currentFingerprint } = useGetLoggedInFingerprintQuery();

  const { fingerprint, label } = keyData;

  async function handleLogin() {
    onSelect(fingerprint);
  }

  function handleShowKey() {
    openDialog(
      <SelectKeyDetailDialog fingerprint={fingerprint} index={index} />
    );
  }

  function handleRename() {
    setIsRenaming(true);
  }

  function handleCloseRename() {
    setIsRenaming(false);
  }

  async function handleDeletePrivateKey() {
    await openDialog(<WalletDeleteDialog fingerprint={fingerprint} />);
  }

  return (
    <CardListItem
      onSelect={isRenaming ? undefined : handleLogin}
      data-testid={`SelectKeyItem-fingerprint-${fingerprint}`}
      key={fingerprint}
      disabled={disabled}
      loading={loading}
    >
      <Flex position="relative">
        <Flex
          direction="column"
          gap={isRenaming ? 1 : 0}
          minWidth={0}
          flexGrow={1}
        >
          {isRenaming ? (
            <SelectKeyRenameForm
              keyData={keyData}
              onClose={handleCloseRename}
            />
          ) : (
            <Typography variant="h6" noWrap>
              {label || <Trans>Wallet {index + 1}</Trans>}
            </Typography>
          )}
          <Typography variant="body2" color="textSecondary">
            {fingerprint}
          </Typography>
        </Flex>
        <Box>
          <Flex flexDirection="column" alignItems="flex-end" gap={0.5}>
            <More>
              <MenuItem onClick={handleRename} close>
                <ListItemIcon>
                  <EditIcon />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>Rename</Trans>
                </Typography>
              </MenuItem>
              <MenuItem onClick={handleShowKey} close>
                <ListItemIcon>
                  <VisibilityIcon />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>Details</Trans>
                </Typography>
              </MenuItem>
              <MenuItem onClick={handleDeletePrivateKey} close>
                <ListItemIcon>
                  <DeleteIcon />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>Delete</Trans>
                </Typography>
              </MenuItem>
            </More>
          </Flex>
        </Box>
        {currentFingerprint === fingerprint && (
          <Box position="absolute" bottom={-5} right={1}>
            <Chip
              size="small"
              label={
                <WalletStatus
                  variant="body2"
                  indicator
                  reversed
                  color="textColor"
                />
              }
            />
          </Box>
        )}
      </Flex>
    </CardListItem>
  );
}
