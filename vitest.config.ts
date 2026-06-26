import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["web/**/*.test.ts"],
    // The web/ TypeScript module is planned but has no tests yet; don't fail CI
    // (vitest exits 1 on "no test files found" by default).
    passWithNoTests: true,
  },
});
