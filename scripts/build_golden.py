"""One-off helper: assemble a single golden-payload JSON from the existing
DefiLlama + Merkl fixtures. Run once; commit the resulting file in tests/fixtures/."""
import json
from pathlib import Path

fx = Path("tests/fixtures")
payload = {
    "captured_at": "2026-05-28",
    "defillama_supply": json.loads((fx / "defillama_pools_sample.json").read_text(encoding="utf-8"))["data"],
    "defillama_borrow": json.loads((fx / "defillama_lendborrow_sample.json").read_text(encoding="utf-8")),
    "merkl_borrow": json.loads((fx / "merkl_borrow_sample.json").read_text(encoding="utf-8")),
}
out = fx / "golden_payload_20260525.json"
out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"wrote {out} ({len(payload['defillama_supply'])} supply pools)")
