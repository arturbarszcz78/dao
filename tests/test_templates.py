"""Every template parses; public templates pass the copy lint."""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from dao.config import lint_public_copy, load_config

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "dao" / "templates"
PUBLIC = ["home.html", "proposals.html", "proposal.html", "proposal_new.html", "seats.html", "decisions.html",
          "inbox.html", "log.html", "log_entry.html", "live.html", "seat.html", "how.html",
          "decision_record.html", "charter.html", "base.html"]


def test_templates_parse():
    env = Environment(loader=FileSystemLoader(str(TPL)))
    for p in sorted(TPL.glob("*.html")):
        env.parse(p.read_text(encoding="utf-8"), filename=str(p))


def test_no_dict_method_shadowing():
    """Jinja resolves `d.keys` to dict.keys (the method), not d["keys"]. Data keys that collide with dict
    method names must use subscript syntax. Found the hard way on /records."""
    bad = re.compile(r"\b\w+\.(keys|values|items|get|update|pop|copy|clear)\b(?!\()")
    hits = []
    for p in sorted(TPL.glob("*.html")):
        text = re.sub(r"<script.*?</script>", " ", p.read_text(encoding="utf-8"), flags=re.S)
        for m in re.finditer(r"{[{%].*?[}%]}", text, flags=re.S):
            if bad.search(m.group(0)):
                hits.append(f"{p.name}: {m.group(0)}")
    assert hits == []


def test_example_decision_record_is_complete_and_public_register():
    """The worked example at /decisions/example defines the record shape; keep it whole and clean."""
    import yaml
    from dao.config import _flatten_strings
    rec = yaml.safe_load((ROOT / "config" / "examples" / "decision_record.yaml").read_text(encoding="utf-8"))
    assert rec["example"] is True
    for key in ("item", "inputs", "seats", "rebuttals", "risk_review", "synthesis", "cost", "human_decision", "execution"):
        assert key in rec, key
    cfg = load_config(ROOT / "config")
    seat_ids = {a.id for a in cfg.agent_seats}
    for s in rec["seats"] + [rec["risk_review"]]:
        assert s["seat"] in seat_ids, s["seat"]
        for field in ("model", "prompt_hash", "position", "confidence", "summary", "counter_argument", "would_change_my_mind"):
            assert field in s, f"{s['seat']} missing {field}"
    assert rec["synthesis"]["seat"] == "orchestrator"
    assert {"recommendation", "confidence", "dissent", "would_change_my_mind", "reasons"} <= set(rec["synthesis"])
    assert lint_public_copy(cfg, _flatten_strings(rec)) == []


def test_public_templates_pass_copy_lint():
    cfg = load_config(ROOT / "config")
    extra = []
    for name in PUBLIC:
        text = (TPL / name).read_text(encoding="utf-8")
        text = re.sub(r"{[{%#].*?[}%#]}", " ", text, flags=re.S)
        text = re.sub(r"<script.*?</script>", " ", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        extra.append(text)
    assert lint_public_copy(cfg, extra) == []
