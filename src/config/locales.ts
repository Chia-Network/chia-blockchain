import { i18n } from '@lingui/core';
import moment from 'moment';
import {
  da,
  de,
  en,
  fi,
  fr,
  it,
  ja,
  nl,
  pl,
  pt,
  ro,
  ru,
  sk,
  sv,
  vi,
  zh,
  es,
} from 'make-plural/plurals';
import * as materialLocales from '@material-ui/core/locale';

const catalogDa = require('../locales/da-DK/messages');
const catalogDe = require('../locales/de-DE/messages');
const catalogEnAu = require('../locales/en-AU/messages');
const catalogEnPt = require('../locales/en-PT/messages');
const catalogEn = require('../locales/en-US/messages');
const catalogEs = require('../locales/es-ES/messages');
const catalogFi = require('../locales/fi-FI/messages');
const catalogFr = require('../locales/fr-FR/messages');
const catalogIt = require('../locales/it-IT/messages');
const catalogJa = require('../locales/ja-JP/messages');
const catalogNl = require('../locales/nl-NL/messages');
const catalogPl = require('../locales/pl-PL/messages');
const catalogPtBr = require('../locales/pt-BR/messages');
const catalogPt = require('../locales/pt-PT/messages');
const catalogRo = require('../locales/ro-RO/messages');
const catalogRu = require('../locales/ru-RU/messages');
const catalogSk = require('../locales/sk-SK/messages');
const catalogSv = require('../locales/sv-SE/messages');
// const catalogViVn = require('../locales/vi-VN/messages');
const catalogZh = require('../locales/zh-TW/messages');
const catalogZhCN = require('../locales/zh-CN/messages');

export const defaultLocale = 'en-US';

// https://www.codetwo.com/admins-blog/list-of-office-365-language-id/
export const locales = [{
  locale: 'da-DK',
  label: 'Dansk',
}, {
  locale: 'de-DE',
  label: 'Deutsch',
}, {
  locale: 'en-US',
  label: 'English',
}, {
  locale: 'en-AU',
  label: 'English (Australia)',
}, {
  locale: 'en-PT',
  label: 'English (Pirate)',
}, {
  locale: 'es-ES',
  label: 'Español',
}, {
  locale: 'fr-FR',
  label: 'Français',
}, {
  locale: 'it-IT',
  label: 'Italiano',
}, {
  locale: 'ja-JP',
  label: '日本語 (日本)',
}, {
  locale: 'nl-NL',
  label: 'Nederlands',
}, {
  locale: 'pl-PL',
  label: 'Polski',
}, {
  locale: 'pt-PT',
  label: 'Português',
}, {
  locale: 'pt-BR',
  label: 'Português (Brasil)',
}, {
  locale: 'ro-RO',
  label: 'Română',
}, {
  locale: 'ru-RU',
  label: 'Русский',
}, {
  locale: 'sk-SK',
  label: 'Slovenčina',
}, {
  locale: 'fi-FI',
  label: 'Suomi',
}, {
  locale: 'sv-SE',
  label: 'Svenska',
}, /* {
  locale: 'vi-VN',
  label: 'Tiếng Việt',
}, */ {
  locale: 'zh-TW',
  label: '繁體中文',
}, {
  locale: 'zh-CN',
  label: '简体中文',
}];

i18n.loadLocaleData('da-DK', { plurals: da });
i18n.loadLocaleData('de-DE', { plurals: de });
i18n.loadLocaleData('en-AU', { plurals: en });
i18n.loadLocaleData('en-PT', { plurals: en });
i18n.loadLocaleData('en-US', { plurals: en });
i18n.loadLocaleData('es-ES', { plurals: es });
i18n.loadLocaleData('fi-FI', { plurals: fi });
i18n.loadLocaleData('fr-FR', { plurals: fr });
i18n.loadLocaleData('it-IT', { plurals: it });
i18n.loadLocaleData('ja-JP', { plurals: ja });
i18n.loadLocaleData('nl-NL', { plurals: nl });
i18n.loadLocaleData('pl-PL', { plurals: pl });
i18n.loadLocaleData('pt-BR', { plurals: pt });
i18n.loadLocaleData('pt-PT', { plurals: pt });
i18n.loadLocaleData('ro-RO', { plurals: ro });
i18n.loadLocaleData('ru-RU', { plurals: ru });
i18n.loadLocaleData('sk-SK', { plurals: sk });
i18n.loadLocaleData('sv-SE', { plurals: sv });
i18n.loadLocaleData('vi-VN', { plurals: vi });
i18n.loadLocaleData('zh-TW', { plurals: zh });
i18n.loadLocaleData('zh-CN', { plurals: zh });
i18n.load('da-DK', catalogDa.messages);
i18n.load('de-DE', catalogDe.messages);
i18n.load('en-PT', catalogEnPt.messages);
i18n.load('en-AU', catalogEnAu.messages);
i18n.load('en-US', catalogEn.messages);
i18n.load('es-ES', catalogEs.messages);
i18n.load('fi-FI', catalogFi.messages);
i18n.load('fr-FR', catalogFr.messages);
i18n.load('it-IT', catalogIt.messages);
i18n.load('ja-JP', catalogJa.messages);
i18n.load('nl-NL', catalogNl.messages);
i18n.load('pl-PL', catalogPl.messages);
i18n.load('pt-BR', catalogPtBr.messages);
i18n.load('pt-PT', catalogPt.messages);
i18n.load('ro-RO', catalogRo.messages);
i18n.load('ru-RU', catalogRu.messages);
i18n.load('sk-SK', catalogSk.messages);
i18n.load('sv-SE', catalogSv.messages);
// i18n.load('vi-VN', catalogViVn.messages);
i18n.load('zh-TW', catalogZh.messages);
i18n.load('zh-CN', catalogZhCN.messages);2

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
