"""Local product-team view of retained quality counters; contains no resume content."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from backend.app.services.quality import get_quality_store
    report = get_quality_store().dashboard().model_dump(mode="json")
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print("Quality report saved to " + str(args.output))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
