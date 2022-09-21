import React, { useEffect } from 'react';
import { Trans, t } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { useLocalStorage } from '@chia/core';
import {
  AlertDialog,
  ButtonLoading,
  Flex,
  Form,
  TextField,
  useOpenDialog,
} from '@chia/core';

import { getCacheInstances } from '../../util/utils';

import { defaultCacheSizeLimit } from '../nfts/gallery/NFTGallery';

type FormData = {
  size: number;
};

const ipcRenderer = (window as any).ipcRenderer;

export default function LimitCacheSize(props: any) {
  const { forceUpdateCacheSize } = props;
  const openDialog = useOpenDialog();

  const [cacheLimitSize, setCacheLimitSize] = useLocalStorage(
    `limit-cache-cacheLimitSize`,
    defaultCacheSizeLimit,
  );

  const methods = useForm<FormData>({
    defaultValues: {
      cacheLimitSize: cacheLimitSize ?? 0,
    },
  });

  useEffect(() => {
    ipcRenderer.on('removeFromLocalStorage', (_event, response: any) => {
      const { removedEntries } = response;

      Object.keys(localStorage).forEach((key) => {
        try {
          const entry = JSON.parse(localStorage[key]);
          if (
            (entry.video &&
              removedEntries.map((file) => file.video).indexOf(entry.video) >
                -1) ||
            (entry.image &&
              removedEntries.map((file) => file.image).indexOf(entry.image) >
                -1) ||
            (entry.binary &&
              removedEntries.map((file) => file.binary).indexOf(entry.binary) >
                -1)
          ) {
            localStorage.removeItem(key);
          }
        } catch (e) {
          console.error(e.message);
        }
      });
      forceUpdateCacheSize();
    });
  }, []);

  const { isSubmitting } = methods.formState;
  const isLoading = isSubmitting;
  const canSubmit = !isLoading;

  async function handleSubmit(values: FormData) {
    if (isSubmitting) {
      return;
    }

    setCacheLimitSize(values?.cacheLimitSize);

    if (ipcRenderer) {
      await ipcRenderer.invoke('adjustCacheLimitSize', {
        newSize: values?.cacheLimitSize,
        cacheInstances: getCacheInstances(),
      });
    }

    await openDialog(
      <AlertDialog>
        <Trans>Successfully updated cache size limit.</Trans>
      </AlertDialog>,
    );
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit} noValidate>
      <Flex gap={2} row>
        <TextField
          label="GiB"
          name="cacheLimitSize"
          type="number"
          disabled={!canSubmit}
          size="small"
          InputProps={{
            inputProps: {
              min: 0,
            },
          }}
        />
        <ButtonLoading
          size="small"
          disabled={!canSubmit}
          type="submit"
          loading={!canSubmit}
          variant="outlined"
          color="secondary"
        >
          <Trans>Update</Trans>
        </ButtonLoading>
      </Flex>
    </Form>
  );
}
