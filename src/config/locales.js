const { i18n } = require('@lingui/core');
const {
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
} = require('make-plural/plurals');

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
i18n.load('zh-CN', catalogZhCN.messages);

i18n.activate('en-US');

module.exports = i18n;
