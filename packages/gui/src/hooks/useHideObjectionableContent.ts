import { useLocalStorage } from '@chia/core';

export default function useHideObjectionableContent() {
  return useLocalStorage<boolean>('hideObjectionableContent', true);
}
