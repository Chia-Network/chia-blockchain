import { i18n } from '@lingui/core';
import {
  ar,
  be,
  bg,
  ca,
  cs,
  da,
  de,
  el,
  en,
  es,
  fa,
  fi,
  fr,
  hr,
  hu,
  id,
  it,
  ja,
  ko,
  nl,
  no,
  pl,
  pt,
  ro,
  ru,
  sk,
  sq,
  sr,
  sv,
  tr,
  uk,
  vi,
  zh,
} from 'make-plural/plurals';
import * as coreLocales from '@chia/core/src/locales';
import * as walletsLocales from '@chia/wallets/src/locales';
import * as guiLocales from '../locales';

export const defaultLocale = 'en-US';

// https://www.codetwo.com/admins-blog/list-of-office-365-language-id/
// https://www.venea.net/web/culture_code
export const locales = [
  {
    locale: 'be-BY',
    label: 'Беларускі',
  },
  {
    locale: 'bg-BG',
    label: 'български език',
  },
  {
    locale: 'ca-ES',
    label: 'Català',
  },
  {
    locale: 'cs-CZ',
    label: 'Čeština',
  },
  {
    locale: 'da-DK',
    label: 'Dansk',
  },
  {
    locale: 'de-DE',
    label: 'Deutsch',
  },
  {
    locale: 'en-US',
    label: 'English',
  },
  {
    locale: 'en-AU',
    label: 'English (Australia)',
  },
  {
    locale: 'en-NZ',
    label: 'English (New Zealand)',
  },
  {
    locale: 'en-PT',
    label: 'English (Pirate)',
  },
  {
    locale: 'es-ES',
    label: 'Español',
  },
  {
    locale: 'es-AR',
    label: 'Español (Argentina)',
  },
  {
    locale: 'es-MX',
    label: 'Español (México)',
  },
  {
    locale: 'el-GR',
    label: 'Ελληνικά',
  },
  {
    locale: 'fr-FR',
    label: 'Français',
  },
  {
    locale: 'hr-HR',
    label: 'Hrvatski',
  },
  {
    locale: 'id-ID',
    label: 'Indonesia',
  },
  {
    locale: 'it-IT',
    label: 'Italiano',
  },
  {
    locale: 'hu-HU',
    label: 'Magyar',
  },
  {
    locale: 'nl-NL',
    label: 'Nederlands',
  },
  {
    locale: 'no-NO',
    label: 'Norsk bokmål',
  },
  {
    locale: 'fa-IR',
    label: 'Persian',
  },
  {
    locale: 'pl-PL',
    label: 'Polski',
  },
  {
    locale: 'pt-PT',
    label: 'Português',
  },
  {
    locale: 'pt-BR',
    label: 'Português (Brasil)',
  },
  {
    locale: 'ro-RO',
    label: 'Română',
  },
  {
    locale: 'ru-RU',
    label: 'Русский',
  },
  {
    locale: 'sq-AL',
    label: 'Shqipe',
  },
  {
    locale: 'sk-SK',
    label: 'Slovenčina',
  },
  {
    locale: 'sr-SP',
    label: 'Srpski',
  },
  {
    locale: 'fi-FI',
    label: 'Suomi',
  },
  {
    locale: 'sv-SE',
    label: 'Svenska',
  },
  {
    locale: 'tr-TR',
    label: 'Türkçe',
  },
  {
    locale: 'uk-UA',
    label: 'Українська',
  },
  {
    locale: 'ar-SA',
    label: '(العربية (المملكة العربية السعودية',
  },
  {
    locale: 'ko-KR',
    label: '한국어',
  },
  /* {
  locale: 'vi-VN',
  label: 'Tiếng Việt',
}, */ {
    locale: 'zh-TW',
    label: '繁體中文',
  },
  {
    locale: 'zh-CN',
    label: '简体中文',
  },
  {
    locale: 'ja-JP',
    label: '日本語 (日本)',
  },
];

i18n.loadLocaleData('ar-SA', { plurals: ar });
i18n.loadLocaleData('be-BY', { plurals: be });
i18n.loadLocaleData('bg-BG', { plurals: bg });
i18n.loadLocaleData('ca-ES', { plurals: ca });
i18n.loadLocaleData('cs-CZ', { plurals: cs });
i18n.loadLocaleData('da-DK', { plurals: da });
i18n.loadLocaleData('de-DE', { plurals: de });
i18n.loadLocaleData('el-GR', { plurals: el });
i18n.loadLocaleData('en-AU', { plurals: en });
i18n.loadLocaleData('en-PT', { plurals: en });
i18n.loadLocaleData('en-US', { plurals: en });
i18n.loadLocaleData('en-NZ', { plurals: en });
i18n.loadLocaleData('es-ES', { plurals: es });
i18n.loadLocaleData('es-AR', { plurals: es });
i18n.loadLocaleData('es-MX', { plurals: es });
i18n.loadLocaleData('fa-IR', { plurals: fa });
i18n.loadLocaleData('fi-FI', { plurals: fi });
i18n.loadLocaleData('fr-FR', { plurals: fr });
i18n.loadLocaleData('hr-HR', { plurals: hr });
i18n.loadLocaleData('hu-HU', { plurals: hu });
i18n.loadLocaleData('id-ID', { plurals: id });
i18n.loadLocaleData('it-IT', { plurals: it });
i18n.loadLocaleData('ja-JP', { plurals: ja });
i18n.loadLocaleData('ko-KR', { plurals: ko });
i18n.loadLocaleData('nl-NL', { plurals: nl });
i18n.loadLocaleData('no-NO', { plurals: no });
i18n.loadLocaleData('pl-PL', { plurals: pl });
i18n.loadLocaleData('pt-BR', { plurals: pt });
i18n.loadLocaleData('pt-PT', { plurals: pt });
i18n.loadLocaleData('ro-RO', { plurals: ro });
i18n.loadLocaleData('ru-RU', { plurals: ru });
i18n.loadLocaleData('sk-SK', { plurals: sk });
i18n.loadLocaleData('sq-AL', { plurals: sq });
i18n.loadLocaleData('sr-SP', { plurals: sr });
i18n.loadLocaleData('sv-SE', { plurals: sv });
i18n.loadLocaleData('tr-TR', { plurals: tr });
i18n.loadLocaleData('uk-UA', { plurals: uk });
i18n.loadLocaleData('vi-VN', { plurals: vi });
i18n.loadLocaleData('zh-TW', { plurals: zh });
i18n.loadLocaleData('zh-CN', { plurals: zh });

locales.forEach(({ locale }) => {
  const importName = locale.replace('-', '');

  const messages = {
    ...coreLocales[importName].messages,
    ...walletsLocales[importName].messages,
    ...guiLocales[importName].messages,
  };

  i18n.load(locale, messages);
});

export { i18n };
