import typography from '@tailwindcss/typography';
import containerQueries from '@tailwindcss/container-queries';

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        'text-primary': '#1A202C',
        'text-secondary': '#374151',
        'text-placeholder': '#6B7280',
        'link-primary': '#2563EB',
        'border-default': '#9CA3AF',
        'border-focus': '#3B82F6',
        'focus-ring': '#3B82F6',
        'btn-primary-bg': '#1D4ED8',
        'btn-primary-hover-bg': '#1E40AF',
        'color-primary': '#0A4D68',
        'color-text-dark': '#2C3E50',
        'color-text-light': '#5C6B7B',
        'color-404-text': '#34495E',
        'color-background-light': '#F8F8F8',
        'nav-active': '#1890FF',
        'text-secondary-light': '#64748B',
        'border-light': '#E2E8F0',
        'bg-slate-100': '#F1F5F9',
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'ui-sans-serif',
          'system-ui',
          'Segoe UI',
          'Noto Sans',
          'sans-serif',
          'Apple Color Emoji',
          'Segoe UI Emoji',
          'Noto Color Emoji',
        ],
      },
      typography: {
        DEFAULT: {
          css: {
            pre: false,
            code: false,
            'pre code': false,
            'code::before': false,
            'code::after': false,
          },
        },
      },
      padding: {
        'safe-bottom': 'env(safe-area-inset-bottom)',
      },
      transitionProperty: {
        width: 'width',
      },
    },
  },
  plugins: [typography, containerQueries],
};
