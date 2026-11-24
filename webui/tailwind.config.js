/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--bg)',
        surface: 'var(--surface)',
        elevated: 'var(--surface-2)',
        line: 'var(--border)',
        ink: 'var(--text)',
        muted: 'var(--muted)',
        accent: 'var(--accent)',
        gain: 'var(--green)',
        loss: 'var(--red)',
        warn: 'var(--amber)',
      },
      borderRadius: { card: '14px' },
    },
  },
  plugins: [],
};
