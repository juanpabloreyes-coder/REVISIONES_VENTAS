"""Lee ACC, arma la tabla de revisiones y escribe Data\\VENTAS_REVISIONES.json + el dashboard HTML."""
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .aps import APS
from .personas import Personas, leer_equipos
from .revisiones import Documentos, construir

log = logging.getLogger("rev_sync.reporte")
FUENTE = "APS (ACC Reviews)"
MARCADOR = '<script id="revisiones-data" type="application/json"></script>'


def _leer_cache(p):
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        return {"reviews": d.get("reviews") or {}, "documentos": d.get("documentos") or {}}
    except Exception:
        return {"reviews": {}, "documentos": {}}


def procesar(cfg, raiz, escribir_salida=True):
    from .__main__ import _aps
    ruta = lambda v: Path(v) if Path(v).is_absolute() else Path(raiz) / v
    tz = timezone(timedelta(hours=cfg.get("zona_horaria_utc", -6)))
    aps = _aps(cfg)
    pid = cfg["aps"]["project_id"]

    log.info("Leyendo revisiones y flujos de ACC...")
    revs = aps.reviews(pid)
    flujos = {w.get("id"): w for w in aps.workflows(pid)}

    # Detalle (pasos + documentos) con cache: las revisiones CERRADAS o ANULADAS que no cambiaron
    # no se vuelven a pedir; las abiertas siempre se actualizan.
    cache_p = ruta(cfg.get("cache", "cache/revisiones.json"))
    cache = _leer_cache(cache_p)
    detalle, pedidas = {}, 0
    for r in revs:
        c = cache["reviews"].get(r["id"])
        vigente = (c and c.get("updatedAt") == r.get("updatedAt")
                   and str(r.get("status")).upper() in ("CLOSED", "VOID"))
        if not vigente:
            pedidas += 1
            c = {"updatedAt": r.get("updatedAt"),
                 "progress": aps.progreso(pid, r["id"]),
                 "versions": aps.versiones_review(pid, r["id"])}
            cache["reviews"][r["id"]] = c
        detalle[r["id"]] = c
    log.info("ACC: %d revisiones (%d consultadas, %d del cache), %d flujos", len(revs), pedidas, len(revs) - pedidas, len(flujos))

    xlsx = ruta(cfg["equipos_xlsx"])
    avisos, roster = [], []
    if xlsx.exists():
        equipos = leer_equipos(xlsx, cfg.get("equipos_hoja", "Integrantes"))
        personas = Personas(equipos, cfg.get("alias_personas"))
        por_equipo = {}
        for e in equipos:
            por_equipo.setdefault(e["equipo"], []).append(e["integrante"])
        roster = [{"equipo": k, "integrantes": v} for k, v in por_equipo.items()]
    else:
        avisos.append(f"No se encontro el Excel de equipos: {xlsx}. Todos quedan SIN EQUIPO.")
        personas = Personas([], cfg.get("alias_personas"))

    docs = Documentos(aps, pid, cfg.get("raiz_nombres", ["Project Files"]), cache["documentos"])
    filas, av = construir(revs, detalle, flujos, docs, personas, cfg, tz)
    avisos += av

    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache_p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    print(f"Revisiones en ACC: {len(revs)}  ->  en el reporte: {len(filas)}")
    print("Por estado:", dict(Counter(f["Estado"] for f in filas)))
    print("Por etapa:", dict(Counter(f["Etapa"] for f in filas)))
    print("Por proyecto:", dict(Counter(f["Proyecto"] for f in filas)))
    for a in avisos:
        print("AVISO:", a)

    if not escribir_salida:
        return "DIAGNOSTICO: no se escribio ningun archivo."
    return escribir(filas, cfg, ruta, roster)


def escribir(filas, cfg, ruta, roster=None):
    json_path = ruta(cfg.get("json", "Data/VENTAS_REVISIONES.json"))
    html_path = ruta(cfg.get("html", "Dashboard/Revisiones-Ventas-Report.html"))
    plantilla = ruta(cfg.get("plantilla", "Dashboard/Revisiones-Ventas-Report.template.html"))
    j = cfg.get("jornada") or {}
    meta = {"zona": cfg.get("zona_horaria_utc", -6), "inicio": j.get("inicio", "08:00"),
            "fin": j.get("fin", "18:00"), "dias": j.get("dias", [0, 1, 2, 3, 4]),
            "proyectoAcc": cfg.get("proyecto_acc", "VENTAS GCP"), "roster": roster or []}

    # Sin cambios en los datos: no se reescribe (el HTML recalcula las horas activas al abrirse)
    try:
        prev = json.loads(json_path.read_text(encoding="utf-8-sig"))
        plantilla_nueva = html_path.exists() and plantilla.stat().st_mtime > html_path.stat().st_mtime
        if (prev.get("source") == FUENTE and prev.get("rows") == filas and prev.get("meta") == meta
                and html_path.exists() and not plantilla_nueva):
            return f"SIN CAMBIOS: {len(filas)} revisiones. Se conservan el JSON y el HTML existentes."
    except Exception:
        pass

    snapshot = {"generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"), "source": FUENTE,
                "meta": meta, "rowCount": len(filas), "rows": filas}
    txt = json.dumps(snapshot, ensure_ascii=False, indent=1)
    template = plantilla.read_text(encoding="utf-8")
    if MARCADOR not in template:
        raise ValueError(f"La plantilla no tiene el marcador {MARCADOR}")
    seguro = txt.replace("</", "<\\/")
    html = template.replace(MARCADOR, '<script id="revisiones-data" type="application/json">' + seguro + '</script>')
    for destino, contenido in ((json_path, txt), (html_path, html)):
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(destino.suffix + ".tmp")
        tmp.write_text(contenido, encoding="utf-8")
        tmp.replace(destino)
    return f"EXPORTACION COMPLETADA: {len(filas)} revisiones." + ("" if filas else " (ninguna cumple los filtros; el reporte queda vacio)")
