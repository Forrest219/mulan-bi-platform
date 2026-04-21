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
        gray: {
          50: 'oklch(0.98 0 0)',
          100: 'oklch(0.94 0 0)',
          200: 'oklch(0.92 0 0)',
          300: 'oklch(0.85 0 0)',
          400: 'oklch(0.77 0 0)',
          500: 'oklch(0.69 0 0)',
          600: 'oklch(0.51 0 0)',
          700: 'oklch(0.42 0 0)',
          800: 'oklch(0.32 0 0)',
          850: 'oklch(0.27 0 0)',
          900: 'oklch(0.2 0 0)',
          950: 'oklch(0.16 0 0)',
        },
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
          '-apple-system',
          'BlinkMacSystemFont',
          'Inter',
          'Vazirmatn',
          'ui-sans-serif',
          'system-ui',
          'Segoe UI',
          'Roboto',
          'Ubuntu',
          'Cantarell',
          'Noto Sans',
          'sans-serif',
          'Helvetica Neue',
          'Arial',
          'Apple Color Emoji',
          'Segoe UI Emoji',
          'Segoe UI Symbol',
          'Noto Color Emoji',
        ],
        primary: ['Archivo', 'Vazirmatn', 'sans-serif'],
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
