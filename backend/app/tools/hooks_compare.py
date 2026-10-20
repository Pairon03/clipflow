"""Compara o gancho antigo (enhance.pick_cold_open) com o novo (hooks.analyze) nos seus projetos reais.

Uso, na pasta backend com o ambiente do ClipFlow ativo:
    python -m app.tools.hooks_compare                 # lista os projetos com transcrição
    python -m app.tools.hooks_compare <projeto>       # compara os cortes selecionados (usa o Ollama se ligado)
    python -m app.tools.hooks_compare <projeto> --sem-ia

Só lê: não altera cortes nem o banco. Grava um relatório JSON em ClipFlowStudio/logs/.
"""
from __future__ import annotations

import json
import sys
import time

from .. import config, db, storage
from ..pipeline import enhance, hooks, llm, render, transcribe
from ..pipeline.runner import transcript_path


def _span_text(words: list[dict], a: float, b: float, base: float) -> str:
    return " ".join(w["text"] for w in words if w["start"] >= base + a - 0.01 and w["end"] <= base + b + 0.25)


def compare(pid: str, use_llm: bool = True) -> dict:
    tpath = transcript_path(pid)
    all_words = transcribe.all_words(transcribe.load(tpath))
    clips = db.fetch_all("SELECT * FROM clips WHERE project_id = ? AND (selected = 1 OR status = 'done') "
                         "ORDER BY start", (pid,))
    rows = []
    for clip in clips:
        words = clip["words"] or render.words_for_clip(all_words, clip["start"], clip["end"])
        t0 = time.monotonic()
        old = enhance.pick_cold_open(words, clip["start"], clip["end"])
        t_old = time.monotonic() - t0
        new = hooks.analyze(words, clip["start"], clip["end"], use_llm=use_llm,
                            timeout=float(config.get("ai.hook_timeout_s")))
        ch = new["chosen"]
        rows.append({
            "clip": clip["id"], "start": clip["start"], "end": clip["end"],
            "old": _span_text(words, *old, clip["start"]) if old else None, "old_s": round(t_old, 3),
            "new": new["candidates"][ch]["clean"] if ch is not None else None,
            "new_total": new["candidates"][ch]["total"] if ch is not None else None,
            "new_engine": new["engine"], "new_s": new["elapsed_s"], "reason": new["reason"],
            "candidates": [{"text": c["clean"], "total": c["total"], "scores": c["scores"],
                            "ai_reason": c.get("reason_ai", "")} for c in new["candidates"]],
        })
    return {"project": pid, "model": config.get("ai.ollama_model") if use_llm and llm.enabled() else None,
            "rows": rows}


def main(argv: list[str]) -> int:
    db.init()
    if not argv:
        for p in db.fetch_all("SELECT id, name FROM projects ORDER BY created_at DESC"):
            if transcript_path(p["id"]).exists():
                print(f"{p['id']}  {p['name']}")
        return 0
    pid, use_llm = argv[0], "--sem-ia" not in argv
    if not transcript_path(pid).exists():
        print("Projeto sem transcrição:", pid)
        return 1
    report = compare(pid, use_llm)
    for r in report["rows"]:
        print("=" * 90)
        print(f"Corte {r['clip']} ({r['end'] - r['start']:.0f}s)")
        print(f"  ANTES : {r['old']!r}  ({r['old_s']}s)")
        print(f"  AGORA : {r['new']!r}  nota {r['new_total']}  [{r['new_engine']}, {r['new_s']}s] {r['reason']}")
        for c in r["candidates"]:
            print(f"     {c['total']:5.2f}  {c['text'][:80]!r}  {c['ai_reason'][:60]}")
    out = storage.root() / "logs" / f"ganchos_{pid}_{int(time.time())}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nRelatório salvo em", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
