# REVISIONES VENTAS (sin Power BI)

Reporte de tiempos de las **revisiones de documentos de ACC** (Docs > Revisiones) del proyecto
**VENTAS GCP**. Reemplaza el modelo de Power BI (conector de ACC / Data Connector) por la API de Reviews.

## Uso
```
python -m rev_sync run           # genera Data\VENTAS_REVISIONES.json y Dashboard\Revisiones-Ventas-Report.html
python -m rev_sync diagnostico   # no escribe nada: muestra conteos y avisos
python -m rev_sync muestra       # guarda respuestas crudas de la API en cache\muestra_api.json (para revisar datos)
```
O doble clic en `Generar-Reporte-REVISIONES.cmd` (genera y abre el reporte).

Automatico: `programar_tarea.bat` (una sola vez) crea la tarea **RevisionesSync_VENTAS_Mensual**:
todos los dias a las 23:45; genera el reporte el ultimo dia del mes, o al encender la PC si ese dia estuvo apagada.

## Sesion de Autodesk
La API de Reviews exige sesion de usuario (como Issues). Se usa **la misma sesion de ISSUES_VENTAS**
(`%LOCALAPPDATA%\issues_sync\sesion.json`): no hay que iniciar sesion aparte. Si algun dia caduca
(mas de ~2 semanas sin encender la PC): `python -m rev_sync login` (sirve para los dos reportes).

## Reglas
- Pasos del flujo por su TIPO en ACC: **Iniciador** (INITIATOR) -> **Revision BIM** (primer REVIEWER, p.ej.
  "Revision inicial 5D") -> **Revision final** (APPROVER). Si un flujo no los trae, palabras clave como en Power Query.
- **Hrs->BIM** = horas laborales entre el envio del iniciador y la revision BIM.
  **Hrs BIM->Final** = entre la revision BIM y la final. Horas laborales: lun-vie 08:00-18:00, UTC-6, sin feriados
  (misma formula `fxHorasLaborales` del Power Query). Configurable en `config.json` > `jornada`.
- **Seguimiento activo**: revisiones abiertas esperando BIM o final; las horas se recalculan al abrir el HTML.
- **Proyecto** = carpeta de primer nivel dentro de Project Files del documento revisado (como ISSUES).
- Solo cuentan revisiones cuyo **iniciador** esta en `Equipos e integrantes - VENTAS.xlsx`
  (`solo_integrantes_listado`). Revisores BIM y responsables finales se muestran aunque no esten en el Excel.
- Estados: CLOSED = cerrada, OPEN = abierta, VOID = anulada. % cerradas = cerradas / total.

## Cache
`cache\revisiones.json`: pasos y documentos de cada revision. Las cerradas/anuladas sin cambios no se
vuelven a pedir; las abiertas se actualizan siempre. Borrarlo solo hace que la siguiente corrida tarde mas.
