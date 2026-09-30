"""REVISIONES_VENTAS sin Power BI.

Uso (desde la carpeta REVISIONES VENTAS):
  python -m rev_sync muestra      # diagnostico: guarda respuestas crudas de la API en cache\\muestra_api.json
  python -m rev_sync run          # genera Data\\VENTAS_REVISIONES.json y Dashboard\\Revisiones-Ventas-Report.html
  python -m rev_sync diagnostico  # igual que run, pero NO escribe nada: imprime conteos y avisos
  python -m rev_sync login        # solo si la sesion caduco (es la MISMA sesion de ISSUES_VENTAS)
  python -m rev_sync refrescar    # renueva la sesion

Credenciales: las mismas de los otros reportes (APS_CLIENT_ID / APS_CLIENT_SECRET).
"""
import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from .aps import APS, APSError
from .sesion import Sesion, SesionError

RAIZ = Path(__file__).resolve().parent.parent


def _ruta(v):
    p = Path(v)
    return p if p.is_absolute() else RAIZ / p


def _log_automation(msg):
    try:
        (RAIZ / "Automation").mkdir(exist_ok=True)
        with open(RAIZ / "Automation" / "rev_sync.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  REVSYNC  {msg}\n")
    except Exception:
        pass


def _credenciales():
    cid, sec = os.environ.get("APS_CLIENT_ID"), os.environ.get("APS_CLIENT_SECRET")
    if not cid or not sec:
        raise SystemExit("Falta APS_CLIENT_ID / APS_CLIENT_SECRET (las mismas variables que usan los otros reportes).")
    return cid, sec


def _sesion(cfg):
    cid, sec = _credenciales()
    return Sesion(cid, sec, cfg.get("callback_url", "http://localhost:8765/callback"))


def _aps(cfg):
    cid, sec = _credenciales()
    aps = APS(cid, sec)
    aps.sesion = _sesion(cfg)
    return aps


def muestra(cfg, n=6):
    """Descarga una muestra de cada endpoint de Reviews para conocer la forma real de los datos."""
    aps = _aps(cfg)
    pid = cfg["aps"]["project_id"]
    out = {"generado": datetime.now().isoformat(), "endpoints": {}}

    def intentar(nombre, fn):
        try:
            r = fn()
            out["endpoints"][nombre] = {"ok": True, "n": len(r) if isinstance(r, list) else None, "datos": r}
            print(f"  OK     {nombre}: {len(r) if isinstance(r, list) else 'objeto'}")
            return r
        except Exception as e:
            out["endpoints"][nombre] = {"ok": False, "error": str(e)[:400]}
            print(f"  ERROR  {nombre}: {str(e)[:200]}")
            return None

    print("Probando la API de Reviews en el proyecto de ACC...")
    revs = intentar("reviews", lambda: aps.reviews(pid)) or []
    intentar("workflows", lambda: aps.workflows(pid))
    usuarios = intentar("usuarios_proyecto", lambda: aps.usuarios_proyecto(pid))
    if usuarios:
        out["endpoints"]["usuarios_proyecto"]["datos"] = usuarios[:3]  # solo la forma, no todo el directorio

    print("Estados:", dict(Counter(str(r.get("status")) for r in revs)))
    # Muestra variada: algunas de cada estado
    elegidas, vistos = [], Counter()
    for r in revs:
        st = str(r.get("status"))
        if vistos[st] < 2:
            elegidas.append(r)
            vistos[st] += 1
        if len(elegidas) >= n:
            break
    for r in elegidas:
        rid = str(r.get("id"))
        intentar(f"progress::{rid}", lambda rid=rid: aps.progreso(pid, rid))
        intentar(f"versions::{rid}", lambda rid=rid: aps.versiones_review(pid, rid))

    destino = _ruta("cache/muestra_api.json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\nRevisiones en ACC: {len(revs)}. Muestra guardada en {destino}")


def main():
    ap = argparse.ArgumentParser(prog="rev_sync")
    ap.add_argument("cmd", choices=["muestra", "run", "diagnostico", "login", "refrescar"])
    ap.add_argument("--config", default=str(RAIZ / "config.json"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))

    if a.cmd in ("login", "refrescar"):
        try:
            s = _sesion(cfg)
            if a.cmd == "login":
                print(f"\nSesion iniciada y guardada en {s.login()}")
            else:
                s.refrescar()
                print("Sesion renovada.")
        except SesionError as e:
            _log_automation(f"SESION: {e}")
            print(f"\nERROR: {e}", file=sys.stderr)
            sys.exit(3)
        return

    if a.cmd == "muestra":
        muestra(cfg)
        return

    from .reporte import procesar
    try:
        estado = procesar(cfg, RAIZ, escribir_salida=(a.cmd == "run"))
    except SystemExit:
        raise
    except Exception as e:
        _log_automation(f"ERROR: {e}. Se conservan el JSON y el HTML anteriores.")
        print(f"\nERROR: {e}\nSe conservan el JSON y el HTML anteriores.", file=sys.stderr)
        sys.exit(2)
    print("\n" + estado)
    if a.cmd == "run":
        _log_automation(estado)


if __name__ == "__main__":
    main()
