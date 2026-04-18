/** @type {import('tailwindcss').Config} */
export default {
    content: [
      "./index.html",
      "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
      extend: {
        colors: {
          // WCAG AA Compliant Text Colors on white (#FFFFFF)
          'text-primary': '#1A202C',        // gray-900 (17.5:1 contrast)
          'text-secondary': '#374151',       // gray-700 (7.2:1 contrast)
          'text-placeholder': '#6B7280',     // gray-500 (3.5:1 - acceptable for placeholder)
          // Link Colors
          'link-primary': '#2563EB',         // blue-600 (4.86:1 contrast)
          // Border & Focus Colors
          'border-default': '#9CA3AF',      // gray-400 (more visible)
          'border-focus': '#3B82F6',         // blue-500 (4.0:1 contrast)
          'focus-ring': '#3B82F6',            // blue-500
          // Button Colors
          'btn-primary-bg': '#1D4ED8',       // blue-700
          'btn-primary-hover-bg': '#1E40AF', // blue-800
          // 404 Page Colors
          'color-primary': '#0A4D68',        // (7.72:1 contrast - brand color)
          'color-text-dark': '#2C3E50',       // (13.9:1 contrast)
          'color-text-light': '#5C6B7B',      // (6.47:1 contrast)
          'color-404-text': '#34495E',        // (10.36:1 contrast)
          'color-background-light': '#F8F8F8',
          // V2 Semantic Colors
          'nav-active': '#1890FF',           // 导航选中态
          'text-secondary-light': '#64748B',  // 次要文本
          'border-light': '#E2E8F0',          // 浅色边框
          'bg-slate-100': '#F1F5F9',         // 浅灰背景
        },
      },
    },
    plugins: [require('@tailwindcss/typography')],
  }
