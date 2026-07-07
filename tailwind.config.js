module.exports = {
  content: [
    './**/templates/**/*.html',
    './**/*.py',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        display: ['Syne', 'sans-serif'],
        body:    ['DM Sans', 'sans-serif'],
      },
      colors: {
        navy: { DEFAULT: '#0F1B2D', 700: '#1a2d47', 500: '#243d5c' },
        gold: { DEFAULT: '#F5A623', light: '#FEF3D7', dark: '#c8841a' },
        cream: '#FAFAF7',
      },
    }
  },
  plugins: [],
}