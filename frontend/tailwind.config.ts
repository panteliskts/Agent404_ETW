import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bess: {
          blue: "#3b82f6",
          green: "#22c55e",
          orange: "#f97316",
          teal: "#14b8a6",
          red: "#ef4444",
          text: "#111827",
          bg: "#f9fafb"
        }
      }
    }
  },
  plugins: []
};

export default config;
