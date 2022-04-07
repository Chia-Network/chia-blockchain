import React, { useMemo, useState } from 'react';
import { WalletType } from '@chia/api';
import { Trans } from '@lingui/macro';
import { Typography, Switch, CircularProgress } from '@mui/material';
import { Tooltip, CardListItem, Flex, Link } from '@chia/core';

export type WalletTokenCardProps = {
  item: {
    type: 'WALLET',
    walletType: WalletType;
    hidden: boolean;
    name: string;
    id: number | string;
  };
  onHide: (id: number) => void;
  onShow: (id: number | string) => Promise<void>;
};

export default function WalletTokenCard(props: WalletTokenCardProps) {
  const {
    item: {
      type,
      walletType,
      walletId,
      assetId,
      hidden,
      name,
    },
    onHide,
    onShow,
  } = props;

  const [isLoading, setIsLoading] = useState<boolean>(false);

  async function handleVisibleChange(event) {
    try {
      const { checked } = event.target;
      const id = walletId ?? assetId;
      if (checked) {
        setIsLoading(true);
        await onShow(id);
      } else if (!checked) {
        onHide(id);
      }
    } finally {
      setIsLoading(false);
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
        <Flex flexDirection="column" flexGrow={1} flexBasis={0} minWidth={0}>
          <Typography noWrap>{name}</Typography>
          {!!subTitle && (
            <Tooltip title={subTitle} copyToClipboard>
              <Typography color="textSecondary" variant="caption" noWrap>
                {subTitle}
              </Typography>
            </Tooltip>
          )}
          {assetId && (
            <Link href={`https://www.taildatabase.com/tail/${assetId}`} target="_blank" variant="caption">
              <Trans>Search on Tail Database</Trans>
            </Link>
          )}
        </Flex>
        {isLoading ? (
          <CircularProgress size={40} />
        ) : (
          <Switch checked={!hidden} onChange={handleVisibleChange} />
        )}
      </Flex>

    </CardListItem>
  );
}
