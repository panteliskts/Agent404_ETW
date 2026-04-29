import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bess: {
          blue: "#1d4ed8",
          green: "#15803d",
          orange: "#b45309",
          teal: "#0f766e",
          red: "#b91c1c",
          graphite: "#17202a",
          steel: "#52616f",
          text: "#17202a",
          bg: "#f3f5f7"
        }
      }
    }
  },
  plugins: []
};

export default config;
