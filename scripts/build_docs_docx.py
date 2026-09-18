"""Build DOCX user/admin guides from Markdown (with screenshots).

Requires: pip install pypandoc_binary

Usage:
  python scripts/build_docs_docx.py
"""
from pathlib import Path

import pypandoc

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

FILES = (
    "INSTRUKCIYA_POLZOVATELA.md",
    "INSTRUKCIYA_ADMINISTRATORA.md",
)


def main():
    for name in FILES:
        md = DOCS / name
        docx = DOCS / name.replace(".md", ".docx")
        pypandoc.convert_file(
            str(md),
            "docx",
            outputfile=str(docx),
            extra_args=["--resource-path=.:screenshots"],
        )
        print(f"Wrote {docx.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
