import { afterEach, describe, expect, it, vi } from "vitest";
import { api, countWords, formatBytes, isCanonicalGithubUrl } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

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

  it("deletes an encoded run identifier", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.deleteRun("run/id");

    expect(fetchMock).toHaveBeenCalledWith("/api/runs/run%2Fid", { method: "DELETE" });
  });
});
