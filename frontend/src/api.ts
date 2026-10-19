import type { components } from "./api.generated";
export type Draft = components["schemas"]["ResumeDraft"];
export type Version = components["schemas"]["DraftVersion"];
export type Job = components["schemas"]["TailorRunJobStatus"];
export type Mutation = components["schemas"]["DraftMutationResponse"];
export type Diff = components["schemas"]["DraftDiffResponse"];
export type Score = components["schemas"]["JDMatchScoreResponse"];
export type PartialRequest = components["schemas"]["PartialRewriteRequest"];

export function credential(runId: string, profileId: string | null): string {
  const read = (storage: Storage, key: string) => {
    try {
      return JSON.parse(storage.getItem(key) || "null");
    } catch {
      return null;
    }
  };
  const active = read(sessionStorage, "noworrycv-active-run");
  if (active?.runId === runId && active?.token) return active.token;
  const history = read(localStorage, "noworrycv-run-history");
  const token =
    Array.isArray(history) && history.find((item) => item.id === runId)?.token;
  if (token) return token;
  const profiles = read(localStorage, "noworrycv-candidate-archives");
  return Array.isArray(profiles)
    ? profiles.find((item) => item.id === profileId)?.token || ""
    : "";
}

export async function request<T>(
  runId: string,
  token: string,
  suffix: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(
    `/api/v1/tailor-runs/${encodeURIComponent(runId)}${suffix}`,
    {
      method,
      headers: {
        "X-Run-Token": token,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  const payload = await response.json();
  if (!response.ok)
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : "操作失败，请稍后重试。",
    );
  return payload as T;
}
