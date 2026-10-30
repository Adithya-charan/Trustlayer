/** @type {import('tailwindcss').Config} */
// TrustLayer LIGHT design system.
// Surfaces: white cards on #F8FAFC. Primary blue #2563EB (navy.600), violet #7C3AED, teal #0D9488.
// `navy` is the brand BLUE scale (name kept so existing classes keep working); there is no dark surface in the app.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: { 50: '#EFF5FF', 100: '#DBEAFE', 200: '#BFD6FD', 300: '#93B8FB', 400: '#609AF8', 500: '#3B82F6', 600: '#2563EB', 700: '#1D4ED8', 800: '#1E40AF', 900: '#1E3A8A' },
        electric: '#2563EB',
        violet: { DEFAULT: '#7C3AED', 50: '#F5F3FF', 100: '#EDE9FE', 200: '#DDD6FE', 500: '#8B5CF6', 600: '#7C3AED', 700: '#6D28D9' },
        teal: { DEFAULT: '#0D9488', 50: '#F0FDFA', 100: '#CCFBF1', 500: '#14B8A6', 600: '#0D9488', 700: '#0F766E' },
        mist: '#F8FAFC',
        body: '#172033',
        muted: '#64748B',
        line: '#E2E8F0',
      },
      boxShadow: {
        card: '0 1px 2px rgba(15,23,42,0.04), 0 4px 14px -6px rgba(15,23,42,0.08)',
        lift: '0 2px 4px rgba(15,23,42,0.04), 0 16px 36px -14px rgba(37,99,235,0.22)',
        soft: '0 24px 60px -24px rgba(37,99,235,0.25)',
      },
      borderRadius: { xl: '0.875rem', '2xl': '1.125rem' },
      keyframes: {
        float: { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-6px)' } },
        flow: { to: { strokeDashoffset: '-32' } },
        drift: { '0%,100%': { transform: 'translate3d(0,0,0)' }, '50%': { transform: 'translate3d(18px,-12px,0)' } },
        ring: { '0%': { transform: 'scale(0.92)', opacity: '0.5' }, '100%': { transform: 'scale(1.35)', opacity: '0' } },
      },
      animation: {
        float: 'float 7s ease-in-out infinite',
        'float-slow': 'float 9s ease-in-out infinite',
        flow: 'flow 2s linear infinite',
        drift: 'drift 16s ease-in-out infinite',
        ring: 'ring 2.6s ease-out infinite',
      },
    },
  },
  plugins: [],
}
