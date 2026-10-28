// 主题值来自 styles/tokens.ts（唯一事实来源，spec §9.2）。
import { theme } from 'ant-design-vue'

import { shellTokens } from './tokens'

export const themeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: shellTokens.colorAccent,
    colorBgBase: shellTokens.colorBg,
    colorBgLayout: shellTokens.colorBg,
    colorBgContainer: shellTokens.colorSurface,
    colorBgElevated: shellTokens.colorSurface2,
    colorBorder: shellTokens.colorBorder,
    colorBorderSecondary: shellTokens.colorBorder,
    colorTextBase: shellTokens.colorText,
    colorText: shellTokens.colorText,
    colorTextSecondary: shellTokens.colorMuted,
    colorTextTertiary: shellTokens.colorFaint,
    colorSuccess: shellTokens.colorSuccess,
    colorWarning: shellTokens.colorWarning,
    colorError: shellTokens.colorDanger,
    colorInfo: shellTokens.colorAccent,
    borderRadius: 8,
    fontSize: 13,
    fontFamily: shellTokens.font
  }
}
