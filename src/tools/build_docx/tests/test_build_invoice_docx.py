from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.build_docx.builder import DocxBuilder
from src.tools.build_docx.mappers.invoice_to_docx_spec import invoice_to_docx_spec


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    examples_dir = base_dir / "examples"
    invoice = json.loads((examples_dir / "sample_invoice_data.json").read_text(encoding="utf-8"))
    spec = invoice_to_docx_spec(invoice)
    spec_path = examples_dir / "sample_docx_spec.json"
    spec_path.write_text(json.dumps(spec.to_dict(), indent=2), encoding="utf-8")

    output_path = examples_dir / "sample_invoice.docx"
    if output_path.exists():
        try:
            output_path.unlink()
        except PermissionError:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = examples_dir / f"sample_invoice_{timestamp}.docx"
    DocxBuilder().build(spec, output_path)
    print(output_path)


if __name__ == "__main__":
    main()
