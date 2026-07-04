import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        node: {
          session: "#3b82f6",
          workspace: "#f59e0b",
          agent: "#ec4899",
          model: "#06b6d4",
        },
      },
    },
  },
  plugins: [],
};
export default config;
