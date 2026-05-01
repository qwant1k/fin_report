/** @type {import('tailwindcss').Config} */
export default {
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
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04)',
      },
    },
  },
  plugins: [],
}
