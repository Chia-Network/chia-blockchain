import { useCallback } from "react";
import { useLingui } from "@lingui/react";

export default function useTrans() {
  const { i18n } = useLingui();

  const handleTranslate = useCallback((messageId: string, values?: Object, options?: Object) => {
    return i18n._(messageId, values, options);
  }, [i18n]);

  return handleTranslate;
}