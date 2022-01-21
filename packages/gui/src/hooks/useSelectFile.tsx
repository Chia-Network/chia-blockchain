import { useShowSaveDialog, useShowError } from '@chia/core';

export default function useSelectFile(): () => Promise<string | undefined> {
  const showSaveDialog = useShowSaveDialog();
  const showError = useShowError();

  async function handleSelect(): Promise<string | undefined> {
    try {
      const result = await showSaveDialog();
      const { filePath } = result;

      return filePath;
    } catch (error: any) {
      showError(error);
    }
  }

  return handleSelect;
}
