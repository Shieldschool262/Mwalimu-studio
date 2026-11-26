/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#EAF5EE",
          100: "#D6EBDD",
          200: "#AED7BD",
          300: "#7DBF98",
          400: "#46A472",
          500: "#1F8A57",
          600: "#0F7A4A",
          700: "#0C633D",
          800: "#0A5032",
          900: "#083F28",
        },
        ink: "#111111",
        muted: "#6B7280",
        line: "#E5E7EB",
        ai: "#FEF3C7",
        clay: {
          50: "#faf7f2",
          100: "#f2ebdf",
          600: "#9a6b3f",
          700: "#7c5330",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      borderRadius: {
        card: "12px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(17, 17, 17, 0.04)",
        drawer: "-12px 0 40px rgba(17, 17, 17, 0.16)",
      },
    },
  },
  plugins: [],
};
