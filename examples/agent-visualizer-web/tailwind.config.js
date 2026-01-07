/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        penguin: {
          dark: '#0f172a',
          darker: '#020617',
          accent: '#06b6d4',
        }
      }
    },
  },
  plugins: [],
}
