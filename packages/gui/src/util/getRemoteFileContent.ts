export default async function getRemoteFileContent(
  url: string,
  maxSize?: number,
): Promise<{ data: string; encoding: string }> {
  const ipcRenderer = (window as any).ipcRenderer;
  const requestOptions = {
    url,
    maxSize,
  };

  const { data, statusCode, encoding, error } = await ipcRenderer?.invoke(
    'fetchBinaryContent',
    requestOptions,
  );

  if (error) {
    throw error;
  }

  if (statusCode !== 200) {
    throw new Error(error.message || `Failed to fetch content from ${url}`);
  }

  return { data, encoding };
}
