"""Organização de arquivos em disco e proteção contra acesso indevido.

Estrutura (cada projeto tem sua própria subpasta em cada área):

    ClipFlowStudio/
      projects/<id>/project.json     metadados + registro de origem/autorização
      downloads/<id>/source.<ext>    vídeo original
      transcripts/<id>/              transcrição (json, srt) e áudio de análise
      clips/<id>/                    arquivos intermediários dos cortes
      subtitles/<id>/                legendas .ass/.srt de cada corte
      exports/<id>/                  MP4 finais + miniaturas
      concat/<id>/<corte>/           projetos do editor Concat (opcional)
      logs/<id>.log                  log de processamento do projeto
      tmp/                           arquivos temporários (ZIPs etc.)
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import config

AREAS = ("projects", "downloads", "transcripts", "clips", "subtitles", "exports", "concat")
_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class UnsafePathError(ValueError):
    pass


def root() -> Path:
    return config.data_dir()


def ensure_layout() -> None:
    r = root()
    for area in (*AREAS, "logs", "tmp"):
        (r / area).mkdir(parents=True, exist_ok=True)


def check_id(project_id: str) -> str:
    if not isinstance(project_id, str) or not _ID_RE.match(project_id):
        raise UnsafePathError("Identificador de projeto inválido")
    return project_id


def area_dir(area: str, project_id: str, create: bool = True) -> Path:
    if area not in AREAS:
        raise UnsafePathError(f"Área desconhecida: {area}")
    d = root() / area / check_id(project_id)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def log_path(project_id: str) -> Path:
    return root() / "logs" / f"{check_id(project_id)}.log"


def safe_join(base: Path, *parts: str) -> Path:
    """Junta caminhos garantindo que o resultado continue dentro de `base`."""
    base = base.resolve()
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        raise UnsafePathError("Caminho fora da área permitida")
    return target


def ensure_inside_root(path: Path | str) -> Path:
    """Valida que um caminho salvo no banco ainda aponta para dentro da pasta de dados."""
    p = Path(path).resolve()
    r = root()
    if r not in p.parents:
        raise UnsafePathError("Arquivo fora da pasta de dados")
    return p


def write_project_json(project_id: str, data: dict) -> None:
    p = area_dir("projects", project_id) / "project.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


def remove_project_files(project_id: str) -> None:
    check_id(project_id)
    for area in AREAS:
        d = area_dir(area, project_id, create=False)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    lp = log_path(project_id)
    if lp.exists():
        lp.unlink(missing_ok=True)


def remove_quietly(*paths: Path | str | None) -> None:
    for p in paths:
        if not p:
            continue
        p = Path(p)
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()
        except OSError:
            pass


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def usage_by_area() -> dict[str, int]:
    r = root()
    return {area: dir_size(r / area) for area in (*AREAS, "logs", "tmp")}
