import { describe, expect, it } from "vitest";
import { errorTitle, parseApiError } from "@/lib/errors";

describe("parseApiError", () => {
  it("reads the preferred { detail: { code, message, retry_after } } shape", () => {
    const e = parseApiError(429, { detail: { code: "rate_limited", message: "Slow down", retry_after: 120 } });
    expect(e.code).toBe("rate_limited");
    expect(e.message).toBe("Slow down");
    expect(e.retryAfter).toBe(120);
    expect(errorTitle(e)).toBe("Rate limit reached");
  });

  it("falls back to the Retry-After header and a default message for a bare 429", () => {
    const e = parseApiError(429, "", "30");
    expect(e.code).toBe("rate_limited");
    expect(e.retryAfter).toBe(30);
    expect(e.message).toMatch(/10 runs per hour/);
  });

  it("maps FastAPI validation errors to fields", () => {
    const e = parseApiError(422, {
      detail: [
        { loc: ["body", "base"], msg: "Field required", type: "missing" },
        { loc: ["body", "audiences", 0], msg: "Input should be 'user' or 'dev'", type: "literal_error" },
      ],
    });
    expect(e.code).toBe("validation");
    expect(e.fields.base).toBe("Field required");
    expect(e.fields.audiences).toMatch(/user/);
  });

  it("recognises a commit-cap message without a code", () => {
    const e = parseApiError(422, { detail: "Range has 1284 commits; the limit is 400 commits per run" });
    expect(e.code).toBe("commit_cap");
  });

  it("treats a plain 404 as repo not found and a run 404 as run not found", () => {
    expect(parseApiError(404, { detail: "Not Found" }).code).toBe("repo_not_found");
    expect(parseApiError(404, { detail: "Run not found" }).code).toBe("run_not_found");
    expect(parseApiError(404, { detail: { code: "range_not_found", message: "No ref v9" } }).code).toBe("range_not_found");
  });

  it("accepts { error: { code, message } } and ignores HTML bodies", () => {
    expect(parseApiError(413, { error: { code: "commit_cap", message: "too big" } }).code).toBe("commit_cap");
    const e = parseApiError(502, "<html>Bad gateway</html>");
    expect(e.code).toBe("server");
    expect(e.message).not.toMatch(/html/);
  });
});
