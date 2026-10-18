"""Correção manual de legendas: realinha o texto editado aos tempos por palavra originais."""
from __future__ import annotations

import difflib
import re


def realign(words: list[dict], new_text: str) -> list[dict]:
    """Aplica o texto corrigido mantendo a sincronização.

    Palavras iguais mantêm seus tempos; trechos substituídos/inseridos dividem o tempo
    do trecho original proporcionalmente ao tamanho das novas palavras.
    """
    new_tokens = [t for t in re.split(r"\s+", new_text.strip()) if t]
    if not words:
        return []
    if not new_tokens:
        raise ValueError("O texto da legenda não pode ficar vazio")
    old_tokens = [w["text"] for w in words]
    sm = difflib.SequenceMatcher(a=[t.lower() for t in old_tokens], b=[t.lower() for t in new_tokens],
                                 autojunk=False)
    out: list[dict] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                w = dict(words[i1 + k])
                w["text"] = new_tokens[j1 + k]  # preserva maiúsculas/pontuação corrigidas
                out.append(w)
        elif op == "delete":
            continue
        else:
            toks = new_tokens[j1:j2]
            if i2 > i1:
                start, end = words[i1]["start"], words[i2 - 1]["end"]
            else:  # inserção: usa o espaço entre as palavras vizinhas (ou uma fatia curta)
                prev_end = out[-1]["end"] if out else words[0]["start"]
                nxt = words[i1]["start"] if i1 < len(words) else prev_end + 0.3 * len(toks)
                start, end = prev_end, max(nxt, prev_end + 0.12 * len(toks))
                if out and end > nxt and i1 < len(words):
                    end = nxt
            weights = [len(t) + 1 for t in toks]
            total = sum(weights)
            t = start
            for tok, wgt in zip(toks, weights):
                d = (end - start) * wgt / total
                out.append({"text": tok, "start": round(t, 3), "end": round(t + d, 3), "prob": None})
                t += d
    # garante ordem e tempos não decrescentes
    for k in range(1, len(out)):
        if out[k]["start"] < out[k - 1]["start"]:
            out[k]["start"] = out[k - 1]["start"]
        if out[k]["end"] < out[k]["start"]:
            out[k]["end"] = out[k]["start"] + 0.05
    return out
