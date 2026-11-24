/** Tokens semánticos Atlas Financials — cero colores crudos en componentes (convención Atlas). */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'hsl(var(--bg) / <alpha-value>)',
        surface: 'hsl(var(--surface) / <alpha-value>)',
        'surface-2': 'hsl(var(--surface-2) / <alpha-value>)',
        ink: 'hsl(var(--ink) / <alpha-value>)',
        'ink-soft': 'hsl(var(--ink-soft) / <alpha-value>)',
        muted: 'hsl(var(--muted) / <alpha-value>)',
        border: 'hsl(var(--border) / <alpha-value>)',
        accent: 'hsl(var(--accent) / <alpha-value>)',
        'accent-strong': 'hsl(var(--accent-strong) / <alpha-value>)',
        'on-accent': 'hsl(var(--on-accent) / <alpha-value>)',
        'accent-soft': 'hsl(var(--accent-soft) / <alpha-value>)',
        rail: 'hsl(var(--rail) / <alpha-value>)',
        'rail-ink': 'hsl(var(--rail-ink) / <alpha-value>)',
        'rail-hi': 'hsl(var(--rail-hi) / <alpha-value>)',
        'rail-muted': 'hsl(var(--rail-muted) / <alpha-value>)',
        pos: 'hsl(var(--pos) / <alpha-value>)',
        neg: 'hsl(var(--neg) / <alpha-value>)',
        warn: 'hsl(var(--warn) / <alpha-value>)',
      },
      fontFamily: {
        display: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Arial', 'sans-serif'],
        body: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Arial', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        float: '0 10px 40px -10px rgba(0,0,0,0.12)',
        accent: '0 0 20px hsl(var(--accent) / 0.2)',
      },
      borderRadius: {
        DEFAULT: '8px',
        panel: '10px',
      },
    },
  },
  plugins: [],
}
