const { i18n } = require("@lingui/core");
const { en, fi, it, ru, sk, sv, zh, es } = require('make-plural/plurals');
const catalogEn = require("./locales/en/messages");
const catalogEs = require('./locales/es/messages');
const catalogFi = require('./locales/fi/messages');
const catalogIt = require('./locales/it/messages');
const catalogRu = require('./locales/ru/messages');
const catalogSk = require('./locales/sk/messages');
const catalogSv = require('./locales/sv/messages');
const catalogZhCN = require('./locales/zh-CN/messages');

i18n.loadLocaleData('en', { plurals: en });
i18n.loadLocaleData('es', { plurals: es });
i18n.loadLocaleData('fi', { plurals: fi });
i18n.loadLocaleData('it', { plurals: it });
i18n.loadLocaleData('ru', { plurals: ru });
i18n.loadLocaleData('sk', { plurals: sk });
i18n.loadLocaleData('sv', { plurals: sv });
i18n.loadLocaleData('zh-CN', { plurals: zh });
i18n.load('en', catalogEn.messages);
i18n.load('es', catalogEs.messages);
i18n.load('fi', catalogFi.messages);
i18n.load('it', catalogIt.messages);
i18n.load('ru', catalogRu.messages);
i18n.load('sk', catalogSk.messages);
i18n.load('sv', catalogSv.messages);
i18n.load('zh-CN', catalogZhCN.messages);

i18n.activate('en');
