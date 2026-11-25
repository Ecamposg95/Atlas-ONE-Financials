"""Descarga los originales del SAT a un directorio FUERA del repo.

    python3 scripts/sat_catalogos/descargar.py /ruta/fuera/del/repo

Escribe cada archivo de ``fuentes.ARCHIVOS`` y un ``descargas.json`` con URL,
fecha de descarga, tamaño y sha256. Sólo usa la biblioteca estándar.
Los archivos descargados son datos no confiables: no se ejecutan ni se importan.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fuentes import ARCHIVOS  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destino", type=Path)
    args = parser.parse_args()
    destino: Path = args.destino.resolve()
    if destino == REPO or REPO in destino.parents:
        parser.error("el destino debe quedar fuera del repositorio")
    destino.mkdir(parents=True, exist_ok=True)

    registro = []
    for nombre, info in ARCHIVOS.items():
        req = urllib.request.Request(info["url"], headers={"User-Agent": "Mozilla/5.0 (catalogos-sat)"})
        with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 - URL fija del SAT
            contenido = resp.read()
        (destino / nombre).write_bytes(contenido)
        sha = hashlib.sha256(contenido).hexdigest()
        registro.append(
            {
                "archivo": nombre,
                "url": info["url"],
                "fecha_descarga": dt.date.today().isoformat(),
                "bytes": len(contenido),
                "sha256": sha,
            }
        )
        print(f"{nombre}: {len(contenido):,} bytes sha256={sha[:12]}…")
    (destino / "descargas.json").write_text(json.dumps(registro, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
