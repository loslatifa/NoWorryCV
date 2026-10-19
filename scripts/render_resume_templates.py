"""Render real sample PDFs into gallery thumbnails after importing templates."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, default=ROOT / ".dist/template-previews")
    args = parser.parse_args()
    poppler = shutil.which("pdftoppm")
    if not poppler:
        parser.error("pdftoppm is required to render thumbnails; install Poppler first")
    from backend.app.services.template_catalog import TEMPLATES, sample_pdf
    destination = ROOT / "backend/app/static/templates"
    args.workdir.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    for key in TEMPLATES:
        path = args.workdir / (key + ".pdf")
        path.write_bytes(sample_pdf(key))
        subprocess.run([poppler, "-png", "-singlefile", "-scale-to", "500", str(path), str(destination / key)],
                       check=True, capture_output=True)
    print("Rendered {0} gallery thumbnails from actual A4 sample PDFs.".format(len(TEMPLATES)))


if __name__ == "__main__":
    main()
