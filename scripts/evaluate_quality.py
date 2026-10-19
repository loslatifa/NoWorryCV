"""Run fixed synthetic quality gates and optionally compare a saved release baseline."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["stub", "configured"], default="stub")
    parser.add_argument("--suite", choices=["resume"], default="resume")
    parser.add_argument("--model", help="仅本次真实评测使用的模型名称，不修改 .env")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".dist/evaluations/latest.json")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--max-score-drop", type=int, default=2)
    args = parser.parse_args()
    if args.dataset is None:
        args.dataset = ROOT / "evals" / ("preparation_quality_v1.json" if args.suite=="preparation" else "resume_quality_v1.json")
    if args.max_score_drop < 0:
        parser.error("--max-score-drop 必须非负")
    if args.baseline and args.output.resolve() == args.baseline.resolve():
        parser.error("输出文件不能覆盖回归基线")
    if args.output.resolve() == args.dataset.resolve():
        parser.error("输出文件不能覆盖评测集")
    if args.model is not None and (args.provider != "configured" or not args.model.strip()):
        parser.error("--model 只能指定用于 configured 评测的非空模型名")
    if args.provider == "stub":
        os.environ["LLM_PROVIDER"] = "stub"
        os.environ["LLM_STRICT_MODE"] = "false"
    else:
        # A release check must fail if the chosen provider is unavailable.
        os.environ["LLM_STRICT_MODE"] = "true"
    if args.model:
        from backend.app.core.config import get_settings, reset_settings_cache
        selected = get_settings().llm_provider.strip().lower()
        if selected in {"qwen", "dashscope"}:
            os.environ["QWEN_MODEL"] = args.model.strip()
        else:
            os.environ["LLM_MODEL"] = args.model.strip()
        reset_settings_cache()
    from backend.app.services.llm.provider import get_llm_provider
    if args.suite == "preparation":
        from backend.app.services.preparation_evaluation import evaluate_preparation_dataset as evaluate_dataset
    else:
        from backend.app.services.evaluation import evaluate_dataset
    if args.provider == "configured" and not get_llm_provider().is_available:
        print("未配置可用模型，真实模型回归评测未执行。", file=sys.stderr)
        return 2
    provider = get_llm_provider()
    print(f'评测模型：{getattr(provider, "name", "unknown")} / {getattr(provider, "model", "stub")}；模式：{args.provider}', flush=True)
    def progress(case, completed, total):
        error = case.get("error", {})
        diagnostic = f' [{error["code"]} / {error["stage"]}]' if error else ""
        print(f'[{completed}/{total}] {case["case_id"]}: {"PASS" if case["passed"] else "FAIL"}{diagnostic} · {case["duration_ms"]} ms {", ".join(case["failures"])}', flush=True)
    try:
        report = evaluate_dataset(args.dataset, args.baseline, args.max_score_drop, on_case=progress)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print("评测配置无效：" + type(exc).__name__, file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f'{sum(case["passed"] for case in report["cases"])}/{len(report["cases"])} passed; {len(report["regressions"])} regressions; report: {args.output}')
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
