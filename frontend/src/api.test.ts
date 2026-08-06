import { describe, expect, it } from "vitest";
import { countWords, formatBytes, isCanonicalGithubUrl } from "./api";

describe("intake helpers", () => {
  it("counts words across Latin and Persian whitespace", () => {
    expect(countWords("  یک ایده\nlocal first  ")).toBe(4);
    expect(countWords("  ")).toBe(0);
  });

  it("accepts only canonical public GitHub repository URLs", () => {
    expect(isCanonicalGithubUrl("https://github.com/openai/openai-python")).toBe(true);
    expect(isCanonicalGithubUrl("https://github.com/openai/openai-python.git")).toBe(true);
    expect(isCanonicalGithubUrl("https://github.com/openai/openai-python/issues")).toBe(false);
    expect(isCanonicalGithubUrl("git@github.com:openai/openai-python.git")).toBe(false);
  });

  it("formats artifact sizes", () => {
    expect(formatBytes(80)).toBe("80 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2.0 MB");
  });
});
