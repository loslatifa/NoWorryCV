import React, { useEffect, useReducer, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  credential,
  request,
  type Draft,
  type Version,
  type Job,
  type Mutation,
  type Diff,
  type Score,
  type PartialRequest,
} from "./api";
import "./style.css";

type Point = { id: string; text: string };
declare global {
  interface Window {
    ExperienceParagraphs: {
      compose(points: Point[]): { text: string };
      reconcile(
        points: Point[],
        text: string,
        options: { kind: string; ownerId: string; createId: () => string },
      ): Point[];
    };
  }
}
const clone = <T,>(value: T): T => structuredClone(value);
const comparable = (draft: Draft) =>
  JSON.stringify({ ...draft, markdown: "", traceability: [] });
type History = {
  past: Draft[];
  present: Draft | null;
  future: Draft[];
  revision: number;
};
type Action =
  | { type: "reset" | "edit"; draft: Draft }
  | { type: "undo" | "redo" };
function history(state: History, action: Action): History {
  if (action.type === "reset")
    return {
      past: [],
      present: clone(action.draft),
      future: [],
      revision: state.revision + 1,
    };
  if (action.type === "edit") {
    if (
      !state.present ||
      comparable(state.present) === comparable(action.draft)
    )
      return state;
    return {
      past: [...state.past.slice(-99), state.present],
      present: clone(action.draft),
      future: [],
      revision: state.revision,
    };
  }
  if (action.type === "undo" && state.past.length && state.present)
    return {
      past: state.past.slice(0, -1),
      present: state.past.at(-1)!,
      future: [state.present, ...state.future],
      revision: state.revision + 1,
    };
  if (action.type === "redo" && state.future.length && state.present)
    return {
      past: [...state.past, state.present],
      present: state.future[0],
      future: state.future.slice(1),
      revision: state.revision + 1,
    };
  return state;
}

function Paragraph({
  points,
  onCommit,
  onPending,
  revision,
  label,
}: {
  points: string[];
  onCommit: (points: string[]) => void;
  onPending: (pending: boolean) => void;
  revision: number;
  label: string;
}) {
  const composed = window.ExperienceParagraphs.compose(
    points.map((text, i) => ({ id: String(i), text })),
  ).text;
  const [text, setText] = useState(composed);
  useEffect(() => setText(composed), [composed, revision]);
  return (
    <label className="field">
      {label}
      <textarea
        rows={5}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          onPending(e.target.value !== composed);
        }}
        onBlur={() => {
          const facts = points.map((text, i) => ({ id: String(i), text }));
          const updated = window.ExperienceParagraphs.reconcile(facts, text, {
            kind: "projects",
            ownerId: "draft",
            createId: () => crypto.randomUUID(),
          });
          onCommit(updated.map((point) => point.text));
          onPending(false);
        }}
      />
    </label>
  );
}

function Editor() {
  const query = new URLSearchParams(location.search);
  const runId = query.get("run") || "";
  const profileId = query.get("profile");
  const [token] = useState(() => credential(runId, profileId));
  const [job, setJob] = useState<Job | null>(null);
  const [state, dispatch] = useReducer(history, {
    past: [],
    present: null,
    future: [],
    revision: 0,
  });
  const [baseline, setBaseline] = useState("");
  const [paragraphDirty, setParagraphDirty] = useState(false);
  const [versions, setVersions] = useState<Version[]>([]);
  const [versionId, setVersionId] = useState("");
  const [score, setScore] = useState<Score | null>(null);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("正在读取已保存简历…");
  const [instruction, setInstruction] = useState("");
  const [target, setTarget] = useState("summary");
  const draft = state.present;
  const dirty = !!draft && (comparable(draft) !== baseline || paragraphDirty);
  const api = <T,>(suffix: string, method = "GET", body?: unknown) =>
    request<T>(runId, token, suffix, method, body);

  useEffect(() => {
    let cancelled = false;
    if (!runId || !token) {
      setError("缺少任务或访问凭据。请从当前浏览器的工作台打开编辑器。");
      setNotice("");
      return;
    }
    request<Job>(runId, token, "/status")
      .then((loaded) => {
        if (cancelled) return;
        if (!loaded.result)
          throw new Error("该任务尚无可编辑结果，请先在工作台完成生成。");
        setJob(loaded);
        dispatch({ type: "reset", draft: loaded.result.final_package.draft });
        setBaseline(comparable(loaded.result.final_package.draft));
        setVersions(loaded.result.draft_versions || []);
        setVersionId(loaded.result.active_version_id || "");
        setNotice("已载入已保存版本。");
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message);
          setNotice("");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runId, token]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const edit = (change: (next: Draft) => void) => {
    if (!draft || busy) return;
    const next = clone(draft);
    change(next);
    dispatch({ type: "edit", draft: next });
    setDiff(null);
    setScore(null);
  };
  async function operate(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败。");
    } finally {
      setBusy(false);
    }
  }
  function acceptMutation(mutation: Mutation) {
    dispatch({ type: "reset", draft: mutation.version.draft });
    setBaseline(comparable(mutation.version.draft));
    setParagraphDirty(false);
    setVersions(mutation.versions || []);
    setVersionId(mutation.version.id || "");
    setDiff(null);
    setScore(null);
  }
  async function refreshScore(current: Draft) {
    setScore(await api<Score>("/score", "POST", { draft: current }));
  }
  async function save() {
    if (!draft) return;
    await operate(async () => {
      const mutation = await api<Mutation>("/draft", "PUT", {
        draft,
        label: "React 编辑器保存",
      });
      acceptMutation(mutation);
      setNotice("已保存为新的简历版本。");
      try {
        await refreshScore(mutation.version.draft);
      } catch {
        setError("简历已保存，评分刷新失败，可稍后重试。");
      }
    });
  }
  async function restore() {
    if (
      !versionId ||
      (dirty && !window.confirm("恢复历史版本将替换未保存修改，继续吗？"))
    )
      return;
    await operate(async () => {
      const mutation = await api<Mutation>(
        `/draft-versions/${encodeURIComponent(versionId)}/restore`,
        "POST",
      );
      acceptMutation(mutation);
      setNotice("已恢复历史版本。");
    });
  }
  async function rewrite() {
    if (
      !draft ||
      (dirty && !window.confirm("局部重写会将当前内容保存为新版本，继续吗？"))
    )
      return;
    await operate(async () => {
      const [target_type, section, item] = target.split(":");
      const body: PartialRequest = {
        draft,
        target_type,
        instruction,
        section_index: section === undefined ? null : Number(section),
        item_index: item === undefined ? null : Number(item),
      };
      const mutation = await api<Mutation>("/rewrite-part", "POST", body);
      acceptMutation(mutation);
      setNotice("局部重写已保存为新版本，请核对表述。");
    });
  }
  const back = `/app/?run=${encodeURIComponent(runId)}${profileId ? `&profile=${encodeURIComponent(profileId)}` : ""}`;
  return (
    <div className="workspace">
      <aside className="sidebar">
        <a className="brand" href="/app/">
          N
          <span>
            NoWorryCV<small>求职，心里有底</small>
          </span>
        </a>
        <p className="eyebrow">我的工作空间</p>
        <a className="nav" href={back}>
          ← 返回工作台
        </a>
        <div className="nav selected">简历编辑器</div>
        <div className="sidebar-note">
          从你的经历出发，
          <br />
          打磨每一次表达。
        </div>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">RESUME EDITOR</p>
            <h1>把经历，写得更清楚。</h1>
            <p className="subtitle">
              {job?.target_company || "我的简历"}
              {job?.target_job_title ? ` · ${job.target_job_title}` : ""}
            </p>
          </div>
          <span className={`badge ${dirty ? "changed" : ""}`}>
            {dirty ? "有未保存修改" : "已保存版本"}
          </span>
        </header>
        <div className="toolbar">
          <div>
            <button
              onClick={() => dispatch({ type: "undo" })}
              disabled={busy || (!state.past.length && !paragraphDirty)}
            >
              撤销
            </button>
            <button
              onClick={() => dispatch({ type: "redo" })}
              disabled={busy || !state.future.length}
            >
              重做
            </button>
          </div>
          <button
            className="primary"
            onClick={save}
            disabled={busy || !draft || !dirty}
          >
            {busy ? "处理中…" : "保存简历"}
          </button>
        </div>
        <div className="status" role="status">
          {notice}
        </div>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {draft && (
          <div className="layout">
            <fieldset className="editor" disabled={busy}>
              <section className="card">
                <div className="section-title">
                  <span className="number">01</span>
                  <h2>个人介绍</h2>
                </div>
                <label className="field">
                  简历标题
                  <input
                    value={draft.headline || ""}
                    onChange={(e) =>
                      edit((next) => {
                        next.headline = e.target.value;
                      })
                    }
                  />
                </label>
                <label className="field">
                  个人摘要
                  <textarea
                    rows={4}
                    value={draft.summary || ""}
                    onChange={(e) =>
                      edit((next) => {
                        next.summary = e.target.value;
                      })
                    }
                  />
                </label>
                <label className="field">
                  技能与工具
                  <textarea
                    rows={3}
                    value={(draft.skills_section || []).join("、")}
                    onChange={(e) =>
                      edit((next) => {
                        next.skills_section = e.target.value
                          .split(/[、，,\n]+/)
                          .map((v) => v.trim())
                          .filter(Boolean);
                      })
                    }
                  />
                </label>
              </section>
              {(["experience_section", "project_section"] as const).map(
                (kind, k) => (
                  <section className="card" key={kind}>
                    <div className="section-title">
                      <span className="number">0{k + 2}</span>
                      <h2>
                        {kind === "experience_section"
                          ? "工作经历"
                          : "项目经历"}
                      </h2>
                      <button
                        className="subtle"
                        onClick={() =>
                          edit((next) => {
                            next[kind] = [
                              ...(next[kind] || []),
                              { heading: "", subheading: "", bullets: [] },
                            ];
                          })
                        }
                      >
                        新增经历
                      </button>
                    </div>
                    {(draft[kind] || []).map((section, index) => (
                      <article className="experience" key={index}>
                        <div className="fields">
                          <label className="field">
                            {kind === "experience_section"
                              ? "公司与岗位"
                              : "项目名称"}
                            <input
                              value={section.heading}
                              onChange={(e) =>
                                edit((next) => {
                                  next[kind]![index].heading = e.target.value;
                                })
                              }
                            />
                          </label>
                          <label className="field">
                            时间与补充说明
                            <input
                              value={section.subheading || ""}
                              onChange={(e) =>
                                edit((next) => {
                                  next[kind]![index].subheading =
                                    e.target.value;
                                })
                              }
                            />
                          </label>
                        </div>
                        <Paragraph
                          revision={state.revision}
                          label="经历正文"
                          onPending={setParagraphDirty}
                          points={section.bullets || []}
                          onCommit={(points) =>
                            edit((next) => {
                              next[kind]![index].bullets = points;
                            })
                          }
                        />
                        <button
                          className="danger subtle"
                          onClick={() =>
                            edit((next) => {
                              next[kind]!.splice(index, 1);
                            })
                          }
                        >
                          删除此经历
                        </button>
                      </article>
                    ))}
                    {!draft[kind]?.length && (
                      <p className="muted">
                        暂无经历，可以添加已有的工作或项目内容。
                      </p>
                    )}
                  </section>
                ),
              )}
              <section className="card">
                <div className="section-title">
                  <span className="number">04</span>
                  <h2>教育经历</h2>
                </div>
                <label className="field">
                  教育信息
                  <textarea
                    rows={4}
                    value={(draft.education_section || []).join("\n")}
                    onChange={(e) =>
                      edit((next) => {
                        next.education_section = e.target.value.split("\n");
                      })
                    }
                  />
                </label>
              </section>
            </fieldset>
            <aside className="tools">
              <section className="card">
                <h2>版本记录</h2>
                <p className="muted">每次保存保留一个版本，可随时恢复。</p>
                <label className="field">
                  历史版本
                  <select
                    value={versionId}
                    onChange={(e) => setVersionId(e.target.value)}
                    disabled={busy}
                  >
                    {versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label} ·{" "}
                        {new Date(v.created_at).toLocaleString("zh-CN")}
                      </option>
                    ))}
                  </select>
                </label>
                <button onClick={restore} disabled={busy || !versionId}>
                  恢复所选版本
                </button>
              </section>
              <section className="card">
                <h2>岗位匹配参考</h2>
                <p className="muted">保存后刷新，供你检查内容取舍。</p>
                <button
                  onClick={() => operate(() => refreshScore(draft))}
                  disabled={busy}
                >
                  刷新匹配分
                </button>
                {score && (
                  <div className="score">
                    <strong>{score.tailored.score}</strong>
                    <span>
                      原始 {score.baseline.score} · 变化{" "}
                      {score.score_delta > 0 ? "+" : ""}
                      {score.score_delta}
                    </span>
                  </div>
                )}
                {score?.compliance_report.risk_level !== undefined && (
                  <p className="muted">
                    表述风险：
                    {(
                      {
                        low: "较低",
                        medium: "需核对",
                        high: "请重点核对",
                      } as Record<string, string>
                    )[score.compliance_report.risk_level] ||
                      score.compliance_report.risk_level}
                  </p>
                )}
              </section>
              <section className="card">
                <h2>局部重写</h2>
                <p className="muted">选择一处内容，说明希望改善的表达。</p>
                <label className="field">
                  重写范围
                  <select
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                    disabled={busy}
                  >
                    <option value="summary">个人摘要</option>
                    <option value="skills">技能</option>
                    {(
                      ["experience_section", "project_section"] as const
                    ).flatMap((kind) =>
                      (draft[kind] || []).flatMap((section, si) =>
                        (section.bullets || []).map((_, bi) => (
                          <option
                            key={`${kind}:${si}:${bi}`}
                            value={`${kind === "experience_section" ? "experience_bullet" : "project_bullet"}:${si}:${bi}`}
                          >
                            {section.heading || "未命名经历"} · 第 {bi + 1} 处
                          </option>
                        )),
                      ),
                    )}
                  </select>
                </label>
                <label className="field">
                  改写要求
                  <textarea
                    rows={3}
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    disabled={busy}
                    placeholder="例如：更简洁地突出行动与成果"
                  />
                </label>
                <button
                  onClick={rewrite}
                  disabled={busy || !instruction.trim()}
                >
                  重写并保存新版本
                </button>
              </section>
              <section className="card">
                <h2>原文对照</h2>
                <p className="muted">查看与原始资料的内容差异。</p>
                <button
                  onClick={() =>
                    operate(async () => {
                      setDiff(
                        await api<Diff>("/draft-diff", "POST", { draft }),
                      );
                    })
                  }
                  disabled={busy}
                >
                  查看差异
                </button>
                {diff && (
                  <div className="diff-list">
                    <p>
                      新增 {diff.added_count} · 修改 {diff.modified_count} ·
                      删除 {diff.removed_count}
                    </p>
                    {(diff.items || []).map((item) => (
                      <details key={item.id}>
                        <summary>{item.label}</summary>
                        {item.original_text && (
                          <p className="original">{item.original_text}</p>
                        )}
                        <p>{item.revised_text || "已移除"}</p>
                        {item.risk_message && (
                          <p className="risk">{item.risk_message}</p>
                        )}
                      </details>
                    ))}
                  </div>
                )}
              </section>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Editor />
  </React.StrictMode>,
);
