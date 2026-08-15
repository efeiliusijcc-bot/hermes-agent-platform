import type { GlobalThemeOverrides } from 'naive-ui'

export const darkThemeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#e0e0e0',
    primaryColorHover: '#f5f5f5',
    primaryColorPressed: '#ffffff',
    primaryColorSuppl: '#e0e0e0',
    successColor: '#66bb6a',
    infoColor: '#6ba3d6',
    warningColor: '#ffb74d',
    errorColor: '#ef5350',
    borderRadius: '8px',
    borderRadiusSmall: '6px',
    fontFamily:
      'Geist, "SF Pro Text", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontFamilyMono: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
    textColorBase: '#e0e0e0',
    bodyColor: '#1a1a1a',
    cardColor: '#2a2a2a',
    modalColor: '#2a2a2a',
    popoverColor: '#2a2a2a',
    tableColor: '#2a2a2a',
    inputColor: '#2a2a2a',
    borderColor: '#3a3a3a',
    dividerColor: '#3a3a3a',
  },
  Button: {
    fontWeight: '600',
    borderRadiusMedium: '6px',
    borderRadiusSmall: '6px',
    heightMedium: '36px',
    textColorPrimary: '#1a1a1a',
    colorPrimary: '#e0e0e0',
    colorHoverPrimary: '#f5f5f5',
    colorPressedPrimary: '#ffffff',
  },
  Card: {
    borderRadius: '8px',
    borderColor: '#3a3a3a',
    paddingMedium: '20px',
  },
  DataTable: {
    thColor: '#252525',
    thTextColor: '#a0a0a0',
    tdColorHover: '#333333',
    borderColor: '#3a3a3a',
  },
  Input: {
    borderRadius: '6px',
    border: '1px solid #555555',
    borderHover: '1px solid #777777',
    borderFocus: '1px solid #e0e0e0',
    boxShadowFocus: '0 0 0 2px rgba(224, 224, 224, 0.12)',
  },
  Menu: {
    itemColorActive: 'rgba(255, 255, 255, 0.08)',
    itemColorActiveHover: 'rgba(255, 255, 255, 0.12)',
    itemTextColorActive: '#e0e0e0',
    itemTextColorActiveHover: '#f5f5f5',
    itemIconColorActive: '#e0e0e0',
    itemIconColorActiveHover: '#ffffff',
    itemHeight: '38px',
    borderRadius: '6px',
  },
}

// Kept as an alias for downstream imports while the console is intentionally dark-only.
export const lightThemeOverrides = darkThemeOverrides
