import { i18n } from '@lingui/core';
import moment from 'moment';
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
import * as materialLocales from '@material-ui/core/locale';

const catalogArSA = require('../locales/ar-SA/messages');
const catalogBeBY = require('../locales/be-BY/messages');
const catalogBgBG = require('../locales/bg-BG/messages');
const catalogCaES = require('../locales/ca-ES/messages');
const catalogCsCZ = require('../locales/cs-CZ/messages');
const catalogDa = require('../locales/da-DK/messages');
const catalogDe = require('../locales/de-DE/messages');
const catalogElGR = require('../locales/el-GR/messages');
const catalogEnAu = require('../locales/en-AU/messages');
const catalogEnNZ = require('../locales/en-NZ/messages');
const catalogEnPt = require('../locales/en-PT/messages');
const catalogEn = require('../locales/en-US/messages');
const catalogEs = require('../locales/es-ES/messages');
const catalogEsAR = require('../locales/es-AR/messages');
const catalogEsMX = require('../locales/es-MX/messages');
const catalogFaIR = require('../locales/fa-IR/messages');
const catalogFi = require('../locales/fi-FI/messages');
const catalogFr = require('../locales/fr-FR/messages');
const catalogHrHR = require('../locales/hr-HR/messages');
const catalogHuHU = require('../locales/hu-HU/messages');
const catalogIdID = require('../locales/id-ID/messages');
const catalogIt = require('../locales/it-IT/messages');
const catalogJa = require('../locales/ja-JP/messages');
const catalogKoKR = require('../locales/ko-KR/messages');
const catalogNl = require('../locales/nl-NL/messages');
const catalogNoNO = require('../locales/no-NO/messages');
const catalogPl = require('../locales/pl-PL/messages');
const catalogPtBr = require('../locales/pt-BR/messages');
const catalogPt = require('../locales/pt-PT/messages');
const catalogRo = require('../locales/ro-RO/messages');
const catalogRu = require('../locales/ru-RU/messages');
const catalogSk = require('../locales/sk-SK/messages');
const catalogSqAL = require('../locales/sq-AL/messages');
const catalogSrSP = require('../locales/sr-SP/messages');
const catalogSv = require('../locales/sv-SE/messages');
const catalogTrTR = require('../locales/tr-TR/messages');
const catalogUkUA = require('../locales/uk-UA/messages');
// const catalogViVn = require('../locales/vi-VN/messages');
const catalogZh = require('../locales/zh-TW/messages');
const catalogZhCN = require('../locales/zh-CN/messages');

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

i18n.load('ar-SA', catalogArSA.messages);
i18n.load('be-BY', catalogBeBY.messages);
i18n.load('bg-BG', catalogBgBG.messages);
i18n.load('ca-ES', catalogCaES.messages);
i18n.load('cs-CZ', catalogCsCZ.messages);
i18n.load('da-DK', catalogDa.messages);
i18n.load('de-DE', catalogDe.messages);
i18n.load('el-GR', catalogElGR.messages);
i18n.load('en-NZ', catalogEnNZ.messages);
i18n.load('en-PT', catalogEnPt.messages);
i18n.load('en-AU', catalogEnAu.messages);
i18n.load('en-US', catalogEn.messages);
i18n.load('es-ES', catalogEs.messages);
i18n.load('es-AR', catalogEsAR.messages);
i18n.load('es-MX', catalogEsMX.messages);
i18n.load('fa-IR', catalogFaIR.messages);
i18n.load('fi-FI', catalogFi.messages);
i18n.load('fr-FR', catalogFr.messages);
i18n.load('hr-HR', catalogHrHR.messages);
i18n.load('hu-HU', catalogHuHU.messages);
i18n.load('id-ID', catalogIdID.messages);
i18n.load('it-IT', catalogIt.messages);
i18n.load('ja-JP', catalogJa.messages);
i18n.load('ko-KR', catalogKoKR.messages);
i18n.load('nl-NL', catalogNl.messages);
i18n.load('no-NO', catalogNoNO.messages);
i18n.load('pl-PL', catalogPl.messages);
i18n.load('pt-BR', catalogPtBr.messages);
i18n.load('pt-PT', catalogPt.messages);
i18n.load('ro-RO', catalogRo.messages);
i18n.load('ru-RU', catalogRu.messages);
i18n.load('sk-SK', catalogSk.messages);
i18n.load('sq-AL', catalogSqAL.messages);
i18n.load('sr-SP', catalogSrSP.messages);
i18n.load('sv-SE', catalogSv.messages);
i18n.load('tr-TR', catalogTrTR.messages);
i18n.load('uk-UA', catalogUkUA.messages);
// i18n.load('vi-VN', catalogViVn.messages);
i18n.load('zh-TW', catalogZh.messages);
i18n.load('zh-CN', catalogZhCN.messages);

export function getMaterialLocale(locale: string) {
  const materialLocale = locale.replace('-', '');
  return materialLocales[materialLocale] ?? materialLocales.enUS;
}

export function activateLocale(locale: string) {
  i18n.activate(locale);
  moment.locale([locale, 'en']);

  // @ts-ignore
  if (typeof window !== 'undefined') {
    window.ipcRenderer?.send('set-locale', locale);
  }
}

export { i18n };

activateLocale(defaultLocale);
