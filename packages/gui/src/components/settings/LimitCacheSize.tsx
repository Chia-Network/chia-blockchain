import React, { useEffect } from 'react';
import { Trans } from '@lingui/macro';
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

import { getCacheInstances, removeFromLocalStorage } from '../../util/utils';

import { defaultCacheSizeLimit } from '../nfts/gallery/NFTGallery';

type FormData = {
  cacheLimitSize: number;
};

const ipcRenderer = (window as any).ipcRenderer;

function LimitCacheSize(props: any) {
  const { forceUpdateCacheSize } = props;
  const openDialog = useOpenDialog();

  const [cacheLimitSize, setCacheLimitSize] = useLocalStorage(
    `cacheLimitSize`,
    defaultCacheSizeLimit,
  );

  const methods = useForm<FormData>({
    defaultValues: {
      cacheLimitSize: cacheLimitSize ?? 0,
    },
  });

  function removeFromLocalStorageListener(_event, response: any) {
    removeFromLocalStorage({ removedObjects: response?.removedEntries });
    forceUpdateCacheSize();
  }

  useEffect(() => {
    ipcRenderer.on('removedFromLocalStorage', removeFromLocalStorageListener);
    return () => {
      ipcRenderer.removeListener(
        'removedFromLocalStorage',
        removeFromLocalStorageListener,
      );
    };
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
      ipcRenderer.invoke('adjustCacheLimitSize', {
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
          label="MiB"
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

export default React.memo(LimitCacheSize);
