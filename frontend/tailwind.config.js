/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: {
          DEFAULT: '#0A0A0A',
          elev: '#121212',
        },
        surface: {
          DEFAULT: '#1C1C1E',
          elev: '#27272A',
        },
        line: '#3F3F46',
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
