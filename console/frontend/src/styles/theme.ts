// 唯一主题事实来源（设计文档 §3.4.4）。这里出现的每一个色值，
// 都能在 styles/variables.less 或 console-preview.html 的 :root 里找到同名项。
import { theme } from 'ant-design-vue'

export const themeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#5b8cff',
    colorBgBase: '#0b1020',
    colorBgLayout: '#0b1020',
    colorBgContainer: '#141a2e',
    colorBgElevated: '#1a2138',
    colorBorder: '#232b45',
    colorBorderSecondary: '#1e2740',
    colorTextBase: '#e6e8f0',
    colorText: '#e6e8f0',
    colorTextSecondary: '#8b93a7',
    colorTextTertiary: '#5b6478',
    colorSuccess: '#35c48a',
    colorWarning: '#e8b339',
    colorError: '#f0655c',
    colorInfo: '#5b8cff',
    borderRadius: 8,
    fontSize: 13,
    fontFamily: "'Inter', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
  }
}
