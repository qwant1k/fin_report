/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        kdif: {
          green: '#1F6B38',
          greenLight: '#70AD47',
          repo: '#FFFF00',
          danger: '#FF0000',
          surface: '#F4F8F4',
        },
        brand: {
          50: '#ecfdf5',
          100: '#d1fae5',
          200: '#a7f3d0',
          300: '#6ee7b7',
          400: '#34d399',
          500: '#10b981',
          600: '#059669',
          700: '#047857',
          800: '#065f46',
          900: '#064e3b',
          950: '#022c22',
        },
        ink: {
          50: '#f6f7f9',
          100: '#eceef2',
          200: '#d4d9e2',
          300: '#aeb6c5',
          400: '#828da3',
          500: '#647088',
          600: '#4e5870',
          700: '#3f475b',
          800: '#363c4d',
          900: '#181d29',
          950: '#0b0f18',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Plus Jakarta Sans"', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04)',
        'card-hover': '0 18px 40px -20px rgba(15, 23, 42, 0.30), 0 8px 16px -10px rgba(15,23,42,0.14)',
        soft: '0 2px 8px -2px rgba(15,23,42,0.08), 0 4px 24px -8px rgba(15,23,42,0.06)',
        glow: '0 0 0 1px rgba(16,185,129,0.18), 0 10px 36px -10px rgba(16,185,129,0.40)',
        'inner-soft': 'inset 0 1px 2px rgba(15,23,42,0.05)',
        ring: '0 0 0 4px rgba(16,185,129,0.14)',
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(135deg, #047857 0%, #059669 45%, #0d9488 100%)',
        'brand-sheen': 'linear-gradient(135deg, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0) 45%)',
        'app-light':
          'radial-gradient(900px 500px at 100% -8%, rgba(16,185,129,0.10), transparent 60%), radial-gradient(800px 500px at -5% 0%, rgba(14,165,164,0.08), transparent 55%)',
      },
      keyframes: {
        'fade-in': { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        float: {
          '0%,100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-6px)' },
        },
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgba(16,185,129,0.45)' },
          '70%': { boxShadow: '0 0 0 10px rgba(16,185,129,0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(16,185,129,0)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.3s ease-out',
        'fade-in-up': 'fade-in-up 0.45s cubic-bezier(0.22,1,0.36,1)',
        'scale-in': 'scale-in 0.22s ease-out',
        shimmer: 'shimmer 1.8s infinite',
        float: 'float 5s ease-in-out infinite',
        'pulse-ring': 'pulse-ring 2s cubic-bezier(0.66,0,0,1) infinite',
      },
      borderRadius: {
        xl: '0.85rem',
        '2xl': '1.1rem',
        '3xl': '1.5rem',
      },
    },
  },
  plugins: [],
}
