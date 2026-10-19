"""Repository contracts, design tokens and syntax checks (no production access)."""

import ast
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
config = yaml.safe_load((ROOT / "diagnostic_hub/config.yaml").read_text())
repository = yaml.safe_load((ROOT / "repository.yaml").read_text())
assert repository["url"] == "https://github.com/Soul7495/-HA-Signalraum"
assert config["version"] == "0.3.0"
assert config["slug"] == "diagnostic_hub"
assert config["arch"] == ["aarch64", "amd64"]
assert config["ingress"] and config["ingress_port"] == 8099
assert config["hassio_api"] and config["hassio_role"] == "manager"
assert config["options"]["automatic_evcc_enabled"] is False
assert config["ingress_stream"] and config["panel_admin"] and config["init"] is False
assert "ports" not in config and "host_network" not in config
assert config["map"] == [{"type": "share", "read_only": False}]
assert set(config["options"]) == set(config["schema"])
translation = yaml.safe_load((ROOT / "diagnostic_hub/translations/de.yaml").read_text())
assert set(translation["configuration"]) == set(config["options"])
design = yaml.safe_load((ROOT / "DESIGN.md").read_text().split("---")[1])
css = (ROOT / "diagnostic_hub/static/style.css").read_text()
for key, color in design["colors"].items():
    assert f"--{key}:{color}" in css, f"Token drift: {key}"
assert "--radius:.75rem" in css and "--space:1.25rem" in css
for section in (
    "Overview",
    "Colors",
    "Typography",
    "Layout",
    "Elevation & Depth",
    "Shapes",
    "Components",
    "Do's and Don'ts",
):
    assert f"## {section}" in (ROOT / "DESIGN.md").read_text()
for file in [*ROOT.glob("diagnostic_hub/*.py"), *ROOT.glob("tests/*.py"), *ROOT.glob("scripts/*.py")]:
    ast.parse(file.read_text(), filename=str(file))
for script in (ROOT / "diagnostic_hub/static").glob("*.js"):
    subprocess.run(["node", "--check", str(script)], check=True)
html = (ROOT / "diagnostic_hub/static/index.html").read_text()
js = (ROOT / "diagnostic_hub/static/app.js").read_text()
assert not re.search(r"\b(?:alert|confirm|prompt)\s*\(", js)
assert "innerHTML" not in js
assert "AbortController" in js and "AbortSignal.timeout" in js
assert '<html lang="de">' in html and '<base href="__BASE__">' in html
print("Repository metadata, translations, DESIGN token drift, Python/JS syntax and UI contracts: PASS")
