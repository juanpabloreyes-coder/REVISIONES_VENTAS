"""Tabla de revisiones de VENTAS sin Power BI (replica GONVAUTO_REVIEWS del reporte original).

Por cada revision de ACC (Docs > Revisiones):
  - Initiator   = quien envio la revision (paso INITIATOR) y cuando.
  - Reviewer BIM = paso REVIEWER (p.ej. "Revision inicial 5D"): quien lo resolvio y cuando.
  - Resp. Final = paso APPROVER (p.ej. "Revision final"): quien lo resolvio y cuando.
  - Hrs->BIM y Hrs BIM->Final = horas LABORALES entre esos momentos (lun-vie 08:00-18:00, UTC-6).
  - Proyecto = carpeta de primer nivel dentro de Project Files del documento revisado (como ISSUES).
Los pasos se identifican por su TIPO en el flujo de ACC (INITIATOR / REVIEWER / APPROVER). Si un flujo
no los trae, se usan las mismas palabras clave que Power Query (INICIADOR, REVISION/BIM, FINAL...).

Solo cuentan las revisiones cuyo Initiator esta en el Excel de integrantes (solo_integrantes_listado).
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .aps import nombre_carpeta

log = logging.getLogger("rev_sync.revisiones")

PASO_HECHO = {"SUBMITTED", "APPROVED", "REJECTED", "COMPLETED", "COMPLETE", "DONE", "CLOSED", "FINISHED", "RETURNED"}
PAL_INITIATOR = ("INITIATOR", "INICIADOR", "INICIAR", "INICIO", "INITIAL REVIEW")
PAL_BIM = ("BIM", "REVIEWER", "REVISOR", "REVISION", "REVISIÓN", "ESPECIALIDAD")
PAL_FINAL = ("FINAL", "APPROVER", "APPROVAL", "APROBADOR", "APROBACION", "APROBACIÓN")


# ------------------------------------------------------------------ fechas / horas
def a_local(texto, tz):
    """ISO de Autodesk (UTC) -> datetime local SIN zona."""
    if not texto:
        return None
    s = str(texto).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s[:19] + "+00:00")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).replace(tzinfo=None, microsecond=0)


def horas_laborales(inicio, fin, h_ini=8, h_fin=18, dias=(0, 1, 2, 3, 4)):
    """Misma formula que fxHorasLaborales de Power Query: suma, por cada dia laborable entre las
    dos fechas, el traslape con la jornada. Sin feriados."""
    if inicio is None or fin is None or fin < inicio:
        return None
    total, d = 0.0, inicio.date()
    while d <= fin.date():
        if d.weekday() in dias:
            a = max(inicio, datetime(d.year, d.month, d.day, h_ini))
            b = min(fin, datetime(d.year, d.month, d.day, h_fin))
            if b > a:
                total += (b - a).total_seconds() / 3600
        d += timedelta(days=1)
    return round(total, 2)


def _txt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else None


# ------------------------------------------------------------------ personas
def _nombre(p):
    return (p or {}).get("name") if isinstance(p, dict) else None


def _candidatos(c):
    if not isinstance(c, dict):
        return []
    out = [u.get("name") for u in c.get("users") or [] if u.get("name")]
    out += [f"Rol: {r.get('name')}" for r in c.get("roles") or [] if r.get("name")]
    out += [f"Empresa: {r.get('name')}" for r in c.get("companies") or [] if r.get("name")]
    return out


# ------------------------------------------------------------------ pasos
def _tipo_por_palabras(nombre):
    t = str(nombre or "").upper()
    if any(p in t for p in PAL_INITIATOR):
        return "INITIATOR"
    if any(p in t for p in PAL_FINAL):
        return "APPROVER"
    if any(p in t for p in PAL_BIM):
        return "REVIEWER"
    return None


def clasificar_pasos(progreso, flujo):
    """-> (initiator, bim, final): cada uno es el dict del paso en 'progress' o None.
    Initiator = primer paso INITIATOR; BIM = primer REVIEWER; Final = ultimo APPROVER
    (igual que Power Query: First / First / Last)."""
    tipos = {s.get("id"): s.get("type") for s in (flujo or {}).get("steps") or []}
    ini, bim, fin = None, None, None
    for p in progreso or []:
        tipo = tipos.get(p.get("stepId")) or _tipo_por_palabras(p.get("stepName"))
        if tipo == "INITIATOR" and ini is None:
            ini = p
        elif tipo == "REVIEWER" and bim is None:
            bim = p
        elif tipo == "APPROVER":
            fin = p
    return ini, bim, fin


def _hecho(p):
    return p is not None and p.get("endTime") and str(p.get("status") or "").upper() in PASO_HECHO


def _quien(p):
    if p is None:
        return None
    return _nombre(p.get("actionBy")) or _nombre(p.get("claimedBy"))


# ------------------------------------------------------------------ documentos -> proyecto
def linaje(urn):
    s = str(urn or "")
    if "fs.file:vf." in s:
        return "urn:adsk.wipprod:dm.lineage:" + s.split("fs.file:vf.", 1)[1].split("?", 1)[0]
    if "dm.lineage:" in s:
        return s.split("?", 1)[0]
    return None


class Documentos:
    """Nombre y ProyectoConcurso de cada archivo revisado, con cache en disco (igual que ISSUES)."""

    def __init__(self, aps, project_id, raices, cache):
        self.aps, self.pid = aps, project_id
        self.raices = {r.strip().lower() for r in raices}
        self.cache = cache  # dict compartido con el cache de revisiones
        self.carpetas = {}

    def _carpeta(self, fid):
        if fid not in self.carpetas:
            j = self.aps.carpeta(self.pid, fid)
            d = (j or {}).get("data") or {}
            parent = (((d.get("relationships") or {}).get("parent") or {}).get("data") or {}).get("id")
            self.carpetas[fid] = {"nombre": nombre_carpeta(d).strip(), "parent": parent} if d else None
        return self.carpetas[fid]

    def resolver(self, lin):
        if lin in self.cache:
            return self.cache[lin]
        j = self.aps.item(self.pid, lin)
        d = (j or {}).get("data")
        if not d:
            return None
        nombre = (d.get("attributes") or {}).get("displayName")
        fid = (((d.get("relationships") or {}).get("parent") or {}).get("data") or {}).get("id")
        cadena, vistos = [], set()
        while fid and fid not in vistos:
            vistos.add(fid)
            c = self._carpeta(fid)
            if not c or c["nombre"].lower() in self.raices:
                break
            cadena.append(c["nombre"])
            fid = c["parent"]
        info = {"nombre": nombre, "proyecto": cadena[-1] if cadena else None}
        self.cache[lin] = info
        return info


# ------------------------------------------------------------------ construccion
def construir(revs, detalle, flujos, docs, personas, cfg, tz):
    """revs: lista de reviews; detalle: {review_id: {"progress": [...], "versions": [...]}};
    flujos: {workflow_id: workflow}. -> (filas, avisos)"""
    j = cfg.get("jornada") or {}
    h_ini = int(str(j.get("inicio", "08:00")).split(":")[0])
    h_fin = int(str(j.get("fin", "18:00")).split(":")[0])
    dias = tuple(j.get("dias", [0, 1, 2, 3, 4]))
    solo_listado = cfg.get("solo_integrantes_listado", True)

    filas, fuera, sin_proyecto = [], {}, 0
    for r in revs:
        det = detalle.get(r["id"]) or {}
        flujo = flujos.get(r.get("workflowId")) or {}
        ini, bim, fin = clasificar_pasos(det.get("progress"), flujo)
        estado = str(r.get("status") or "").upper()

        iniciador = _quien(ini) or _nombre(r.get("createdBy"))
        _, equipo = personas.resolver(iniciador) if iniciador else (None, "SIN EQUIPO")
        if solo_listado and equipo == "SIN EQUIPO":
            fuera[iniciador or "(sin iniciador)"] = fuera.get(iniciador or "(sin iniciador)", 0) + 1
            continue

        f_ini = a_local(ini.get("endTime"), tz) if _hecho(ini) else a_local(r.get("createdAt"), tz)
        f_bim = a_local(bim.get("endTime"), tz) if _hecho(bim) else None
        f_fin = a_local(fin.get("endTime"), tz) if _hecho(fin) else None
        if f_fin is None and estado == "CLOSED" and fin is not None:
            f_fin = a_local(r.get("finishedAt") or r.get("approvedAt"), tz)

        # Documentos -> proyecto (el mas frecuente entre los archivos de la revision)
        proyectos, archivos = {}, []
        for v in det.get("versions") or []:
            archivos.append(v.get("name"))
            info = docs.resolver(v.get("itemUrn") or linaje(v.get("urn")))
            if info and info.get("proyecto"):
                proyectos[info["proyecto"]] = proyectos.get(info["proyecto"], 0) + 1
        proyecto = max(proyectos, key=proyectos.get) if proyectos else None
        if not proyecto:
            sin_proyecto += 1

        # Etapa actual y a quien le toca
        if estado == "VOID":
            etapa = "Anulada"
        elif estado == "CLOSED":
            etapa = "Cerrada"
        elif bim is not None and not _hecho(bim):
            etapa = "En revision BIM"
        elif fin is not None and not _hecho(fin):
            etapa = "En revision final"
        else:
            etapa = "En proceso"
        actual = next((p for p in (bim, fin) if p is not None and not _hecho(p)), None) if etapa.startswith("En ") else None
        nab = r.get("nextActionBy") or {}
        reclamada = [_nombre(x) for x in nab.get("claimedBy") or [] if _nombre(x)]
        pendiente_de = ", ".join(reclamada or _candidatos(nab.get("candidates")) or _candidatos((actual or {}).get("candidates")))

        def persona(paso, hecho_fn=_hecho):
            if paso is None:
                return None
            q = _quien(paso)
            if q:
                return q
            return "Pendiente" if not hecho_fn(paso) else "Usuario no encontrado"

        filas.append({
            "Proyecto": proyecto or "(sin proyecto)",
            "Rev": r.get("sequenceId"),
            "ReviewId": r.get("id"),
            "Nombre": r.get("name"),
            "Estado": estado,
            "Etapa": etapa,
            "Flujo": flujo.get("name"),
            "Initiator": iniciador or "Usuario no encontrado",
            "Equipo": equipo,
            "FechaInitiator": _txt(f_ini),
            "PasoBIM": (bim or {}).get("stepName"),
            "ReviewerBIM": persona(bim),
            "EstadoPasoBIM": (bim or {}).get("status"),
            "FechaBIM": _txt(f_bim),
            "HrsBIM": horas_laborales(f_ini, f_bim, h_ini, h_fin, dias),
            "PasoFinal": (fin or {}).get("stepName"),
            "RespFinal": persona(fin),
            "EstadoPasoFinal": (fin or {}).get("status"),
            "FechaFinal": _txt(f_fin),
            "HrsFinal": horas_laborales(f_bim, f_fin, h_ini, h_fin, dias),
            "PendienteDe": pendiente_de or None,
            "Reclamada": bool(reclamada),
            "Creada": _txt(a_local(r.get("createdAt"), tz)),
            "Actualizada": _txt(a_local(r.get("updatedAt"), tz)),
            "Documentos": len(det.get("versions") or []),
            "Archivos": ", ".join(a for a in archivos if a)[:300] or None,
        })

    filas.sort(key=lambda f: (f["Creada"] or ""), reverse=True)
    avisos = []
    if fuera:
        avisos.append("Revisiones excluidas porque el iniciador no esta en el Excel de integrantes: " +
                      ", ".join(f"{n} ({c})" for n, c in sorted(fuera.items())))
    if sin_proyecto:
        avisos.append(f"{sin_proyecto} revisiones sin proyecto identificado (documentos borrados o fuera de Project Files).")
    return filas, avisos
