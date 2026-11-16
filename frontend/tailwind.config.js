/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: {
          DEFAULT: '#0E0E11',
          elev: '#121214',
        },
        surface: {
          DEFAULT: '#18181B',
          elev: '#212124',
        },
        line: '#212124',
        accent: {
          DEFAULT: '#3B82F6',
          soft: '#1D4ED8',
        },
        ok: {
          DEFAULT: '#4ADE80',
          bg: '#14532D',
        },
        mute: '#A1A1AA',
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'sans-serif',
        ],
      },
      boxShadow: {
        sheet: '0 -8px 40px rgba(0,0,0,0.55)',
      },
      maxWidth: {
        phone: '430px',
        content: '720px',
      },
    },
  },
  plugins: [],
};
