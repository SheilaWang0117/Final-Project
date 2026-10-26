// Simplified Chinese dictionary (keys are the English UI strings). Split into parts by page group.
import { ZH1 } from "./i18n_zh_1";
import { ZH2 } from "./i18n_zh_2";
import { ZH3 } from "./i18n_zh_3";
import { ZH4 } from "./i18n_zh_4";
import { ZH5 } from "./i18n_zh_5";
import { ZH6 } from "./i18n_zh_6";

export const ZH: Record<string, string> = { ...ZH1, ...ZH2, ...ZH3, ...ZH4, ...ZH5, ...ZH6 };
