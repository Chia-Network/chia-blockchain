export default function usePersist(baseNamespace: string): (namespace?: string) => string {
  if (!baseNamespace) {
    throw new Error('baseNamespace is required');
  }

  function handleGenerateNamespace(namespace?: string): string {
    return namespace ? `${baseNamespace}.${namespace}` : baseNamespace;
  }

  return handleGenerateNamespace;
}

