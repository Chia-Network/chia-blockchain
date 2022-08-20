import React, { useEffect, useMemo, useState, useRef } from 'react';
import { WalletType } from '@chia/api';
import { useSetCATNameMutation } from '@chia/api-react';
import { Trans } from '@lingui/macro';
import { Box, Typography, Switch, CircularProgress } from '@mui/material';
import {
  Tooltip,
  CardListItem,
  Flex,
  Link,
  useShowError,
  Form,
  TextField,
} from '@chia/core';
import { type ListItem } from '../hooks/useWalletsList';
import { useForm } from 'react-hook-form';

export type WalletTokenCardProps = {
  item: ListItem;
  onHide: (id: number) => void;
  onShow: (id: number | string) => Promise<void>;
};

type FormData = {
  name: string;
};

export default function WalletTokenCard(props: WalletTokenCardProps) {
  const {
    item: { type, walletType, walletId, assetId, hidden, name = '' },
    onHide,
    onShow,
  } = props;

  const [isRenaming, setIsRenaming] = useState<boolean>(false);
  const [isChangingVisibility, setIsChangingVisibility] =
    useState<boolean>(false);
  const isChangingVisibilityRef = useRef<boolean>(isChangingVisibility);
  const [setCATName] = useSetCATNameMutation();
  const showError = useShowError();
  const form = useForm<FormData>({
    defaultValues: {
      name,
    },
  });

  isChangingVisibilityRef.current = isChangingVisibility;

  const isLoading = isRenaming || isChangingVisibility;

  useEffect(() => {
    form.setValue('name', name);
  }, [form, name]);

  async function handleSubmit(values: FormData) {
    return handleRename(values.name);
  }

  async function handleRename(newName: string) {
    if (isLoading) {
      return;
    }

    try {
      if (!newName || newName === name) {
        return;
      }

      setIsRenaming(true);
      setIsChangingVisibility(false);

      let currentWalletId = walletId;

      if (!currentWalletId) {
        if (!assetId) {
          return;
        }

        currentWalletId = await onShow(assetId);

        // hide wallet
        if (hidden && !isChangingVisibilityRef.current) {
          await onHide(currentWalletId);
        }
      }

      if (currentWalletId) {
        await setCATName({
          walletId: currentWalletId,
          name: newName,
        }).unwrap();
      }
    } catch (error) {
      showError(error);
    } finally {
      setIsChangingVisibility(false);
      setIsRenaming(false);
    }
  }

  async function handleVisibleChange(event) {
    if (isChangingVisibility) {
      return;
    }

    if (isRenaming) {
      // process
      setIsChangingVisibility(true);
      return;
    }

    try {
      const { checked } = event.target;
      const id = walletId ?? assetId;
      if (id) {
        if (checked) {
          setIsChangingVisibility(true);
          await onShow(id);
        } else {
          onHide(id);
        }
      }
    } finally {
      setIsChangingVisibility(false);
    }
  }

  const subTitle = useMemo(() => {
    if (type === 'WALLET') {
      if (walletType === WalletType.CAT) {
        return assetId;
      }

      return '';
    }

    return assetId;
  }, [assetId, type, walletType]);

  return (
    <CardListItem>
      <Flex gap={1} alignItems="center" width="100%">
        <Flex
          flexDirection="column"
          gap={0.5}
          flexGrow={1}
          flexBasis={0}
          minWidth={0}
        >
          {walletType === WalletType.STANDARD_WALLET ? (
            <Typography noWrap>{name}</Typography>
          ) : (
            <Form methods={form} onSubmit={handleSubmit}>
              <TextField
                name="name"
                label="Name"
                onBlur={(event) => handleRename(event.target.value)}
                disabled={isLoading}
                size="small"
                fullWidth
                hiddenLabel
              />
            </Form>
          )}
          {(!!subTitle || assetId) && (
            <Flex
              flexDirection="column"
              flexGrow={1}
              flexBasis={0}
              minWidth={0}
            >
              {!!subTitle && (
                <Tooltip
                  title={subTitle}
                  PopperProps={{
                    popperOptions: {
                      modifiers: [
                        {
                          name: 'offset',
                          options: { offset: [0, -12] },
                        },
                      ],
                    },
                  }}
                  copyToClipboard
                >
                  <Typography color="textSecondary" variant="caption" noWrap>
                    {subTitle}
                  </Typography>
                </Tooltip>
              )}
              {assetId && (
                <Link
                  href={`https://www.taildatabase.com/tail/${assetId}`}
                  target="_blank"
                  variant="caption"
                >
                  <Trans>Search on Tail Database</Trans>
                </Link>
              )}
            </Flex>
          )}
        </Flex>
        {walletType !== WalletType.STANDARD_WALLET && (
          <Box width="60px" textAlign="center" position="relative">
            <Box position="absolute" top="0" left="25%">
              <CircularProgress
                size={34}
                sx={{ zIndex: -1, opacity: isLoading ? 1 : 0 }}
              />
            </Box>
            <Switch
              checked={!hidden}
              onChange={handleVisibleChange}
              disabled={isChangingVisibility}
              sx={{ opacity: isLoading ? 0 : 1 }}
            />
          </Box>
        )}
      </Flex>
    </CardListItem>
  );
}
