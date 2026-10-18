"""Antes de abrir: aplica uma atualização copiada por cima (python -m app.update_check).

- Dependências Python: reinstala se o backend/requirements.txt mudou desde a última instalação.
- Interface: recompila (npm run build) se o código do frontend mudou desde a última compilação.

Assim, atualizar o ClipFlow é só copiar as pastas novas e abrir de novo.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
STAMP = Path(sys.prefix) / ".clipflow-requirements.sha256"
_FRONTEND_INPUTS = ("src", "index.html", "package.json", "vite.config.js", "vite.config.ts")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def requirements_outdated() -> bool:
    if not REQUIREMENTS.is_file():
        return False
    return not STAMP.is_file() or STAMP.read_text().strip() != _hash(REQUIREMENTS)


def frontend_hash(frontend: Path = FRONTEND) -> str:
    """Hash do código da interface (conteúdo, não datas: ZIPs extraídos não preservam datas confiáveis)."""
    h = hashlib.sha256()
    for name in _FRONTEND_INPUTS:
        p = frontend / name
        for f in sorted(p.rglob("*")) if p.is_dir() else [p]:
            if f.is_file():
                h.update(f.relative_to(frontend).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def _frontend_stamp(frontend: Path) -> Path:
    return frontend / "dist" / ".clipflow-source.sha256"


def frontend_outdated(frontend: Path = FRONTEND) -> bool:
    stamp = _frontend_stamp(frontend)
    if not (frontend / "dist" / "index.html").is_file() or not stamp.is_file():
        return True
    return stamp.read_text().strip() != frontend_hash(frontend)


def mark_frontend_built(frontend: Path = FRONTEND) -> None:
    _frontend_stamp(frontend).write_text(frontend_hash(frontend))


def _run(cmd: list[str], cwd: Path | None = None) -> bool:
    if os.name == "nt" and cmd[0].lower().endswith((".cmd", ".bat")):
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *cmd]
    return subprocess.run(cmd, cwd=cwd).returncode == 0


def main() -> int:
    ok = True
    if requirements_outdated():
        print("Atualizando dependências Python...")
        if _run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)]):
            STAMP.write_text(_hash(REQUIREMENTS))
        else:
            print("[AVISO] Falha ao instalar dependências. Rode setup-windows.bat.")
            ok = False
    if frontend_outdated():
        npm = shutil.which("npm")
        if not npm:
            print("[AVISO] A interface precisa ser recompilada, mas o Node.js (npm) não foi encontrado.")
            return 1
        print("Recompilando a interface (atualização detectada)...")
        ok = _run([npm, "install"], cwd=FRONTEND) and ok  # rápido quando nada mudou; pega pacotes novos
        if _run([npm, "run", "build"], cwd=FRONTEND):
            mark_frontend_built()
        else:
            print("[AVISO] Falha ao compilar a interface. Rode setup-windows.bat.")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
