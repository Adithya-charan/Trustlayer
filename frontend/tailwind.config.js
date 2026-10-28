/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: { 50: '#f3f6fb', 100: '#e4ebf6', 200: '#c8d6ec', 500: '#2f5fb3', 600: '#244b92', 700: '#1c3a74', 800: '#152c58', 900: '#0f2140' },
      },
      fontFamily: { sans: ['Inter', 'system-ui', 'Segoe UI', 'sans-serif'] },
    },
  },
  plugins: [],
}
