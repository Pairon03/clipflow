"""Gera os ícones das animações (app/assets/icons/*.png) a partir do pacote Lucide (licença ISC).

Roda só no desenvolvimento, uma vez (precisa do Node e do frontend instalado):
    python -m app.tools.build_icons

Cada ícone vira uma máscara branca com fundo transparente (256 px); o render pinta na cor do tema.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import config

ICONS = """trophy medal star crown shield flag users user-round heart heart-crack brain dollar-sign banknote wallet
piggy-bank trending-up trending-down chart-column calendar clock hourglass house car plane bus map-pin globe smartphone
tv mic music camera film book-open graduation-cap briefcase building-2 hospital stethoscope pill dumbbell utensils
coffee beer wine baby dog cat gift shopping-cart store gamepad-2 laptop message-circle megaphone lightbulb target
rocket zap flame skull siren scale gavel lock key sun moon mountain check x triangle-alert thumbs-up thumbs-down
handshake church volleyball goal footprints party-popper sparkles ticket bed""".split()

SRC = config.PROJECT_ROOT / "frontend" / "node_modules" / "lucide-vue-next"
OUT = config.ASSETS_DIR / "icons"


def svg_snippets() -> dict[str, str]:
    script = r"""
const fs = require("fs"); const out = {};
for (const n of process.argv.slice(1)) {
  const s = fs.readFileSync(process.env.ICON_DIR + "/" + n + ".js", "utf8");
  const a = s.slice(s.indexOf("createLucideIcon("));
  const nodes = eval("(" + a.slice(a.indexOf("["), a.lastIndexOf("]") + 1) + ")");
  out[n] = nodes.map(([tag, at]) => "<" + tag + " " + Object.entries(at).filter(([k]) => k != "key")
    .map(([k, v]) => k + '="' + v + '"').join(" ") + "/>").join("");
}
process.stdout.write(JSON.stringify(out));
"""
    env = {"ICON_DIR": str(SRC / "dist" / "esm" / "icons"), "PATH": "/usr/bin:/bin:/usr/local/bin"}
    res = subprocess.run(["node", "-e", script, *ICONS], capture_output=True, text=True, env=env, check=True)
    return json.loads(res.stdout)


def main() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    snippets = svg_snippets()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        pg = b.new_page(viewport={"width": 256, "height": 256})
        for name, inner in snippets.items():
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="256" height="256" fill="none" '
                   f'stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>')
            pg.set_content(f'<html><body style="margin:0;background:transparent">{svg}</body></html>')
            pg.screenshot(path=str(OUT / f"{name}.png"), omit_background=True)
        b.close()
    lic = SRC / "LICENSE"
    (OUT / "LICENSE-lucide.txt").write_text(lic.read_text() if lic.exists() else "ISC License — Lucide Contributors")
    print(f"{len(snippets)} ícones em {OUT}")


if __name__ == "__main__":
    main()
