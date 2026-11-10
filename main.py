import contextlib
import os
import unicodedata
from datetime import datetime, timedelta, timezone

import httpx
import uvicorn

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from auth import api_key_autorizada
from mcp.server.transport_security import TransportSecuritySettings

# =====================================================
# 1. CONFIGURACIÓN DEL SERVIDOR MCP
# =====================================================

_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
_extra = os.environ.get("MCP_ALLOWED_HOSTS", "")
HOSTS_PERMITIDOS = [
    h.strip()
    for h in [_render_host, *_extra.split(","), "localhost:*", "127.0.0.1:*"]
    if h and h.strip()
]

mcp = FastMCP(
    "SECOP-Colombia-Server",
    stateless_http=True,  # Clave para Composio (sin sesión persistente)
    json_response=True,  # Respuestas JSON simples (sin SSE)
    streamable_http_path="/",  # La sub-app responde en su raíz
    transport_security=TransportSecuritySettings(
        # Protección DNS rebinding ACTIVA; solo se autorizan los hosts
        # propios. Render define RENDER_EXTERNAL_HOSTNAME automáticamente
        # (p. ej. secop-mcp-server.onrender.com). Sin esto: 421.
        enable_dns_rebinding_protection=True,
        allowed_hosts=HOSTS_PERMITIDOS,
        allowed_origins=[f"https://{h}" for h in HOSTS_PERMITIDOS],
    ),
)

# Dataset "SECOP II - Procesos de Contratación" (Colombia Compra Eficiente).
SECOP_DATASET_URL = "https://www.datos.gov.co/resource/p6dx-8zbt.json"

# Token opcional de Socrata: sin él, las consultas anónimas tienen límite
# de frecuencia. Se crea gratis en datos.gov.co y se define en Render.
SOCRATA_APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN", "").strip()

# Colombia no tiene horario de verano: UTC-5 fijo.
ZONA_CO = timezone(timedelta(hours=-5))

TIMEOUT_SEGUNDOS = 45.0

# =====================================================
# 2. CRITERIOS DEL RADAR (heredados del Scout SECOP v30)
# =====================================================
# Las palabras se escriben sin tildes; la consulta tolera tildes y eñes
# (ver variantes_sin_tilde). Use raíces ("PAVIMENT") para cubrir
# pavimento / pavimentación / pavimentar con un solo filtro.

SECTORES = {
    "interventoria": ["INTERVENTOR"],
    "agua": ["ACUEDUCTO", "ALCANTARILLAD", "AGUA POTABLE", "SANEAMIENTO"],
    "vial": ["VIAL", "CARRETER", "PAVIMENT", "TRANSPORTE", "SENALIZACION"],
    "social": [
        "COLEGIO", "HOSPITAL", "EDUCACION", "INFRAESTRUCTURA SOCIAL",
    ],
    "catastro": ["CATASTR"],
    "obra": [
        "CONSTRUCCION", "OBRA", "INFRAESTRUCTURA", "REMODELACION",
        "ADECUACION", "MANTENIMIENTO",
    ],
    "fortalecimiento": [
        "FORTALECIMIENTO", "CAPACITACION", "FORMACION", "CHARLA",
        "TALLER", "CURSO", "ASISTENCIA TECNICA", "CONSULTORIA TECNICA",
        "TRANSFERENCIA DE CONOCIMIENTO", "PROGRAMA DE FORMACION",
    ],
}

# Valores EXACTOS del campo modalidad_de_contratacion (verificados en el
# esquema del dataset). El Scout comparaba subcadenas en minúscula.
MODALIDADES_EXCLUIDAS = [
    "Enajenación de bienes con subasta",
    "Enajenación de bienes con sobre cerrado",
    "Subasta de prueba",
    "Solicitud de información a los Proveedores",
    "Licitación Pública Acuerdo Marco de Precios",
]

# Contratación directa sin ofertas: el contratista ya está definido.
# "Contratación Directa (con ofertas)" y "régimen especial (con ofertas)"
# sí reciben ofertas y NO se excluyen.
MODALIDADES_SIN_COMPETENCIA = [
    "Contratación directa",
    "Contratación régimen especial",
]

# Estados del procedimiento que admiten ofertas. El dataset solo usa:
# Seleccionado, Publicado, Evaluación, Cancelado, Borrador, Abierto,
# Aprobado, En aprobación, Suspendido. No existen "desierto",
# "liquidado", "terminado", "revocado" ni "anulado".
ESTADOS_ABIERTOS = ["Publicado", "Abierto"]

# Alias para departamentos cuyo nombre en el dataset difiere del habitual.
# El filtro de departamento es por coincidencia EXACTA (tolerante a
# tildes): con "%SANTANDER%" se colaba "Norte de Santander".
ALIAS_DEPARTAMENTO = {
    "BOGOTA": "DISTRITO CAPITAL DE BOGOTA",
    "BOGOTA DC": "DISTRITO CAPITAL DE BOGOTA",
    "BOGOTA D C": "DISTRITO CAPITAL DE BOGOTA",
    "SANTAFE DE BOGOTA": "DISTRITO CAPITAL DE BOGOTA",
    "DISTRITO CAPITAL": "DISTRITO CAPITAL DE BOGOTA",
    "SAN ANDRES": "SAN ANDRES, PROVIDENCIA Y SANTA CATALINA",
    "SAN ANDRES Y PROVIDENCIA": "SAN ANDRES, PROVIDENCIA Y SANTA CATALINA",
    "NORTE SANTANDER": "NORTE DE SANTANDER",
    "N DE SANTANDER": "NORTE DE SANTANDER",
    "VALLE": "VALLE DEL CAUCA",
    "GUAJIRA": "LA GUAJIRA",
}


class ErrorConsulta(Exception):
    """Error controlado al consultar Datos Abiertos."""


# =====================================================
# 3. FUNCIONES AUXILIARES
# =====================================================

def escapar_soql(valor: str) -> str:
    """Escapa comillas simples en valores de texto SoQL."""
    return valor.replace("'", "''")


def quitar_tildes(texto: str) -> str:
    """Quita tildes y diéresis; convierte Ñ en N. Devuelve en mayúsculas."""
    normal = unicodedata.normalize("NFKD", texto.upper())
    limpio = "".join(c for c in normal if not unicodedata.combining(c))
    return " ".join(limpio.replace(".", " ").split())


def variantes_sin_tilde(termino: str) -> list[str]:
    """
    Genera las variantes de un término con y sin tilde.

    SoQL no tiene una función para ignorar tildes. En español la tilde
    cae en una de las tres últimas sílabas, así que basta con la forma
    sin tilde, la tilde en cada una de las tres últimas vocales y la Ñ
    en cada N. Menos variantes = consulta más rápida.
    Ej.: VIA -> VIA, VÍA, VIÁ.
    """
    base = quitar_tildes(termino)
    tildes = {"A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú"}
    variantes = [base]
    vocales = [i for i, c in enumerate(base) if c in tildes][-3:]
    for i in vocales:
        variantes.append(base[:i] + tildes[base[i]] + base[i + 1:])
    for i, letra in enumerate(base):
        if letra == "N":
            variantes.append(base[:i] + "Ñ" + base[i + 1:])
    # Sin duplicados, conservando el orden.
    return list(dict.fromkeys(variantes))


def filtro_texto(campos: list[str], termino: str) -> str:
    """
    Arma un filtro OR que busca el término en varios campos,
    tolerando tildes. Para términos largos usa el comodín "_"
    en las vocales (verificado contra la API) y evita una cláusula
    demasiado extensa.
    """
    base = quitar_tildes(termino)
    if len(base) >= 9:
        patron = "".join("_" if c in "AEIOU" else c for c in base)
        patrones = [patron]
    else:
        patrones = variantes_sin_tilde(base)

    condiciones = [
        f"upper({campo}) like '%{escapar_soql(p)}%'"
        for campo in campos
        for p in patrones
    ]
    return "(" + " OR ".join(condiciones) + ")"


# Sílabas de las palabras del radar que en los datos aparecen con tilde
# o eñe. El "_" de SoQL acepta un carácter cualquiera en esa posición.
_SILABAS_CON_TILDE = {
    "CION": "CI_N",          # construcción, adecuación, capacitación...
    "TECNICA": "T_CNICA",    # asistencia técnica
    "CONSULTORIA": "CONSULTOR_A",
    "SENALIZ": "SE_ALIZ",    # señalización
}


def patron_sector(palabra: str) -> str:
    """Patrón LIKE de una palabra del radar, tolerante a su tilde."""
    patron = palabra
    for sin_tilde, comodin in _SILABAS_CON_TILDE.items():
        patron = patron.replace(sin_tilde, comodin)
    return patron


def normalizar_departamento(departamento: str) -> str:
    """Traduce alias habituales al nombre usado en el dataset."""
    clave = quitar_tildes(departamento)
    return ALIAS_DEPARTAMENTO.get(clave, clave)


def filtro_departamento(departamento: str) -> str:
    """
    Coincidencia exacta del departamento, tolerante a tildes y eñes.
    "Santander" ya no trae "Norte de Santander" (verificado en la API).
    """
    nombre = normalizar_departamento(departamento)
    if len(nombre) >= 9:
        patrones = ["".join("_" if c in "AEIOUN" else c for c in nombre)]
    else:
        patrones = variantes_sin_tilde(nombre)
    condiciones = [
        f"upper(departamento_entidad) like '{escapar_soql(p)}'"
        for p in patrones
    ]
    return "(" + " OR ".join(condiciones) + ")"


# Sinónimos de búsqueda: en el dataset unas gobernaciones figuran como
# "DEPARTAMENTO DEL ARAUCA" y otras como "GOBERNACIÓN DEL CAUCA"
# (verificado en la API). La palabra se busca en cualquiera de sus formas.
SINONIMOS = {
    "GOBERNACION": ["GOBERNACION", "DEPARTAMENTO"],
    "ALCALDIA": ["ALCALDIA", "MUNICIPIO"],
}


# Palabras que no aportan a la búsqueda y la hacen más lenta.
PALABRAS_VACIAS = {
    "DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "E", "EN", "A", "AL",
    "PARA", "POR", "CON", "SIN", "O", "U",
}


def filtro_frase(campos: list[str], frase: str) -> str:
    """
    Parte la frase en palabras y exige TODAS (AND), cada una en
    cualquiera de los campos (OR). Evita el like '%frase completa%'
    que fallaba con frases de varias palabras.
    """
    palabras = [
        p for p in quitar_tildes(frase).split()
        if p not in PALABRAS_VACIAS and len(p) >= 2
    ] or [quitar_tildes(frase)]
    grupos = []
    for palabra in palabras:
        formas = SINONIMOS.get(palabra, [palabra])
        if len(formas) == 1:
            grupos.append(filtro_texto(campos, palabra))
        else:
            grupos.append(
                "(" + " OR ".join(filtro_texto(campos, f) for f in formas) + ")"
            )
    return " AND ".join(grupos)


def es_identificador(texto: str) -> bool:
    """CO1.REQ.123 (proceso) o CO1.BDOS.123 (portafolio)."""
    t = texto.strip().upper()
    return t.startswith("CO1.REQ.") or t.startswith("CO1.BDOS.")


def validar_fecha(fecha: str | None, defecto: str) -> str:
    """Valida una fecha AAAA-MM-DD; si viene vacía usa el valor por defecto."""
    if not fecha or not fecha.strip():
        return defecto
    try:
        return datetime.strptime(fecha.strip()[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ErrorConsulta(
            f"la fecha '{fecha}' no es válida. Use el formato AAAA-MM-DD."
        )


def lista_soql(valores: list[str]) -> str:
    """Convierte una lista de textos en ('a','b',...) para IN / NOT IN."""
    return "(" + ",".join(f"'{escapar_soql(v)}'" for v in valores) + ")"


def hoy_colombia() -> datetime:
    return datetime.now(ZONA_CO)


async def consultar_secop(parametros: dict) -> list[dict]:
    """Consulta el dataset y devuelve la lista de registros."""
    encabezados = {"Accept": "application/json"}
    if SOCRATA_APP_TOKEN:
        encabezados["X-App-Token"] = SOCRATA_APP_TOKEN

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SEGUNDOS,
            follow_redirects=True,
        ) as cliente:
            respuesta = await cliente.get(
                SECOP_DATASET_URL,
                params=parametros,
                headers=encabezados,
            )
            respuesta.raise_for_status()
            datos = respuesta.json()

    except httpx.TimeoutException:
        raise ErrorConsulta(
            "la consulta a SECOP II superó el tiempo máximo de espera. "
            "Reduzca el rango de fechas o el número de sectores."
        )
    except httpx.HTTPStatusError as error:
        raise ErrorConsulta(
            f"HTTP {error.response.status_code} al consultar Datos "
            f"Abiertos. Detalle: {error.response.text[:400]}"
        )
    except httpx.RequestError as error:
        raise ErrorConsulta(f"conexión con Datos Abiertos: {error}")
    except ValueError:
        raise ErrorConsulta("la API no devolvió JSON válido.")

    if not isinstance(datos, list):
        raise ErrorConsulta("la API devolvió un formato inesperado.")
    return datos


FILAS_POR_PAGINA = 1000
MAX_PAGINAS = 5  # tope de seguridad: 5.000 filas por consulta del radar


async def consultar_paginado(where: str) -> list[dict]:
    """
    Recorre las páginas de la consulta con $offset. El orden incluye
    :id para que la paginación sea estable entre peticiones.
    """
    todos: list[dict] = []
    for pagina in range(MAX_PAGINAS):
        lote = await consultar_secop(
            {
                "$where": where,
                "$limit": FILAS_POR_PAGINA,
                "$offset": pagina * FILAS_POR_PAGINA,
                "$order": "fecha_de_publicacion_del DESC, :id",
            }
        )
        todos.extend(lote)
        if len(lote) < FILAS_POR_PAGINA:
            break
    return todos


def sin_duplicados(datos: list[dict]) -> list[dict]:
    """
    Deja un registro por proceso. El dataset repite filas de dos formas:
      - la misma fila varias veces (lotes o recargas);
      - una fila por FASE (observaciones, manifestación de interés,
        presentación de oferta), cada una con su propio id_del_proceso
        pero con el mismo id_del_portafolio (CO1.BDOS). Verificado en la
        API: un portafolio llegó a tener 4 registros.
    Conserva la fase con la última publicación más reciente y respeta
    el orden en que llegaron los datos.
    """
    elegido: dict[str, dict] = {}
    orden: list[str] = []
    for proceso in datos:
        clave = (
            proceso.get("id_del_portafolio")
            or proceso.get("id_del_proceso")
            or proceso.get("referencia_del_proceso")
            or str(id(proceso))
        )
        actual = elegido.get(clave)
        if actual is None:
            elegido[clave] = proceso
            orden.append(clave)
        elif (proceso.get("fecha_de_ultima_publicaci") or "") > (
            actual.get("fecha_de_ultima_publicaci") or ""
        ):
            elegido[clave] = proceso
    return [elegido[c] for c in orden]


def a_numero(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def formato_pesos(valor) -> str:
    """1234567 -> $1.234.567"""
    numero = a_numero(valor)
    if numero <= 0:
        return "No disponible"
    return "$" + f"{round(numero):,}".replace(",", ".")


def formato_fecha(valor) -> str:
    """'2026-11-12T00:00:00.000' -> '2026-11-12'"""
    return valor[:10] if isinstance(valor, str) and valor else "—"


def obtener_enlace(proceso: dict) -> str:
    enlace = proceso.get("urlproceso")
    if isinstance(enlace, dict):
        enlace = enlace.get("url") or enlace.get("value")
    return enlace or "N/A"


def dias_restantes(proceso: dict) -> int | None:
    """Días hasta la fecha de recepción de ofertas (None si no hay)."""
    fecha = proceso.get("fecha_de_recepcion_de")
    if not fecha:
        return None
    try:
        cierre = datetime.fromisoformat(fecha[:10]).date()
    except ValueError:
        return None
    return (cierre - hoy_colombia().date()).days


def texto_dias(dias: int | None) -> str:
    if dias is None:
        return "Sin fecha de cierre publicada"
    if dias < 0:
        return "VENCIDO"
    if dias == 0:
        return "Cierra HOY"
    return f"{dias} día(s)"


def detectar_sector(proceso: dict) -> str:
    """Mismo orden de prioridad que el Scout SECOP v30."""
    texto = quitar_tildes(
        (proceso.get("nombre_del_procedimiento") or "")
        + " "
        + (proceso.get("descripci_n_del_procedimiento") or "")
    )
    reglas = [
        ("Interventoría", ["INTERVENTOR"]),
        ("Agua y saneamiento",
         ["ACUEDUCTO", "ALCANTARILL", "AGUA POTABLE", "SANEAMIENTO"]),
        ("Infraestructura vial",
         ["VIAL", "CARRETER", "PAVIMENT", "TRANSPORTE", "VIAS"]),
        ("Gestión catastral", ["CATASTR"]),
        ("Infraestructura social",
         ["COLEGIO", "HOSPITAL", "EDUCAC", "SALUD", "SOCIAL"]),
        ("Mantenimiento", ["MANTENIMIENTO"]),
        ("Señalización", ["SENALIZ"]),
        ("Fortalecimiento / Capacitación",
         ["FORTALECIMIENTO", "CAPACITACI", "FORMACI", "TALLER", "CHARLA",
          "CURSO", "ASISTENCIA TECNICA", "TRANSFERENCIA DE CONOCIMIENTO"]),
    ]
    for sector, claves in reglas:
        if any(clave in texto for clave in claves):
            return sector
    return "Obra civil general"


def calcular_relevancia(precio: float) -> str:
    if precio >= 1_000_000_000:
        return "ALTA"
    if precio >= 200_000_000:
        return "MEDIA"
    if precio >= 28_000_000:
        return "BAJA"
    return "MUY BAJA"


def calcular_accion(proceso: dict, precio: float) -> str:
    adjudicado = (proceso.get("adjudicado") or "").strip().lower() == "si"
    estado = (proceso.get("estado_del_procedimiento") or "").lower()
    resumen = (proceso.get("estado_resumen") or "").lower()
    if (
        adjudicado
        or estado in ("cancelado", "seleccionado", "suspendido")
        or "adjudicado" in resumen
    ):
        return "DESCARTAR"
    if precio >= 500_000_000:
        return "ANALIZAR CON CLAUDE"
    if precio >= 100_000_000:
        return "EVALUAR"
    return "MONITOREAR"


def validar_limite(limite, maximo: int = 100) -> int:
    if isinstance(limite, bool) or not isinstance(limite, int):
        raise ErrorConsulta("el límite debe ser un número entero.")
    return max(1, min(limite, maximo))


# =====================================================
# 4. HERRAMIENTA MCP: BÚSQUEDA DE PROCESOS SECOP II
# =====================================================

@mcp.tool()
async def buscar_procesos_secop(
    termino: str = "",
    departamento: str | None = None,
    solo_abiertos: bool = False,
    desde: str | None = None,
    id_proceso: str | None = None,
    limite: int = 10,
) -> str:
    """
    Busca procesos de contratación pública en SECOP II.

    Busca cada palabra del término (todas deben aparecer) en el nombre,
    la descripción del objeto y la entidad. Ignora tildes y mayúsculas:
    "interventoria" encuentra "INTERVENTORÍA". Muestra un registro por
    proceso (la fase vigente), los más recientes primero.

    Parámetros:
        termino: Palabras clave del objeto o de la entidad
            (ej.: "mejoramiento vía", "Gobernación de Arauca").
            Si es un ID CO1.REQ.### o CO1.BDOS.### busca ese proceso.
        departamento: Departamento de la entidad (ej.: Arauca, Bogotá,
            Bogotá D.C., Santander, Norte de Santander, San Andrés).
        solo_abiertos: True para ver solo procesos en estado Publicado o
            Abierto y con fecha de cierre no vencida.
        desde: Fecha mínima de publicación AAAA-MM-DD. Por defecto,
            los últimos 180 días (búsquedas más amplias tardan más).
        id_proceso: ID exacto del proceso (CO1.REQ.###) o del portafolio
            (CO1.BDOS.###). Si se envía, ignora los demás filtros.
        limite: Cantidad máxima de resultados, entre 1 y 100.
    """
    identificador = (id_proceso or "").strip()
    if not identificador and es_identificador(termino or ""):
        identificador = termino.strip()

    if identificador:
        return await detalle_proceso(identificador)

    if not termino or not termino.strip():
        return "Error: debes proporcionar una palabra clave o un id_proceso."

    try:
        limite = validar_limite(limite)
        hoy = hoy_colombia().date()
        fecha_desde = validar_fecha(
            desde, (hoy - timedelta(days=180)).isoformat()
        )

        # Primero los filtros baratos (fecha, departamento, estado) y al
        # final el texto: así la API no recorre los 8,7 millones de filas.
        filtros = [f"fecha_de_publicacion_del >= '{fecha_desde}'"]

        if departamento and departamento.strip():
            filtros.append(filtro_departamento(departamento))

        if solo_abiertos:
            filtros.append(
                f"estado_del_procedimiento in {lista_soql(ESTADOS_ABIERTOS)}"
            )
            filtros.append(
                f"(fecha_de_recepcion_de IS NULL OR "
                f"fecha_de_recepcion_de >= '{hoy.isoformat()}')"
            )

        filtros.append(
            filtro_frase(
                [
                    "nombre_del_procedimiento",
                    "descripci_n_del_procedimiento",
                    "entidad",
                ],
                termino,
            )
        )

        # Se piden filas de más porque cada fase es un registro aparte.
        parametros = {
            "$where": " AND ".join(filtros),
            "$limit": min(limite * 4, 1000),
            "$order": "fecha_de_publicacion_del DESC, :id",
        }

        datos = sin_duplicados(await consultar_secop(parametros))[:limite]

    except ErrorConsulta as error:
        return f"Error: {error}"

    if not datos:
        sugerencia = ""
        if departamento:
            sugerencia = (
                " Verifique el nombre del departamento o pruebe sin él."
            )
        return (
            f"No se encontraron procesos para '{termino.strip()}' "
            f"publicados desde {fecha_desde}.{sugerencia}"
        )

    resultados = [ficha_corta(p) for p in datos]
    return (
        f"{len(datos)} proceso(s) encontrados (publicados desde "
        f"{fecha_desde}).\n\n" + "\n\n".join(resultados)
    )


def ficha_corta(proceso: dict) -> str:
    """Ficha de un proceso para los listados."""
    return (
        f"ENTIDAD: {proceso.get('entidad', 'N/A')} "
        f"(NIT {proceso.get('nit_entidad', 'N/A')})\n"
        f"ID DEL PROCESO: {proceso.get('id_del_proceso', 'N/A')} | "
        f"PORTAFOLIO: {proceso.get('id_del_portafolio', 'N/A')}\n"
        f"REFERENCIA: {proceso.get('referencia_del_proceso', 'N/A')}\n"
        f"OBJETO: {proceso.get('descripci_n_del_procedimiento') or proceso.get('nombre_del_procedimiento', 'N/A')}\n"
        f"DEPARTAMENTO / MUNICIPIO: {proceso.get('departamento_entidad', 'N/A')} / {proceso.get('ciudad_entidad', 'N/A')}\n"
        f"MODALIDAD: {proceso.get('modalidad_de_contratacion', 'N/A')}\n"
        f"PRECIO BASE: {formato_pesos(proceso.get('precio_base'))}\n"
        f"ESTADO: {proceso.get('estado_del_procedimiento', 'N/A')} | "
        f"FASE: {proceso.get('fase', 'N/A')}\n"
        f"PUBLICACIÓN: {formato_fecha(proceso.get('fecha_de_publicacion_del'))}"
        f" | CIERRE DE OFERTAS: {formato_fecha(proceso.get('fecha_de_recepcion_de'))}"
        f" ({texto_dias(dias_restantes(proceso))})\n"
        f"URL DEL PROCESO: {obtener_enlace(proceso)}"
    )


# =====================================================
# 5. HERRAMIENTA MCP: RADAR DE OPORTUNIDADES (Scout)
# =====================================================

@mcp.tool()
async def radar_oportunidades(
    sectores: list[str] | None = None,
    departamento: str | None = None,
    presupuesto_minimo: int = 1_000_000,
    presupuesto_maximo: int = 10_000_000_000,
    dias_publicacion: int = 15,
    incluir_contratacion_directa: bool = False,
    limite: int = 25,
) -> str:
    """
    Radar de oportunidades abiertas en SECOP II con los criterios del
    Scout SECOP de LICITACIONES PRO. Solo devuelve procesos que todavía
    reciben ofertas.

    Filtros aplicados:
        - Estado Publicado o Abierto y fecha de cierre no vencida.
        - Presupuesto entre presupuesto_minimo y presupuesto_maximo (COP).
        - Publicados en los últimos dias_publicacion días.
        - Excluye enajenaciones, subastas de prueba, solicitudes de
          información y acuerdos marco; por defecto también la
          contratación directa sin ofertas.
        - Palabras clave del sector en el nombre o la descripción.

    Cada proceso trae sector, relevancia, días al cierre, acción
    sugerida (ANALIZAR CON CLAUDE / EVALUAR / MONITOREAR) y enlace
    directo. Ordena por cierre más próximo.

    Parámetros:
        sectores: Lista con uno o varios de: interventoria, agua, vial,
            social, catastro, obra, fortalecimiento. Vacío = todos.
        departamento: Departamento de la entidad (opcional).
        presupuesto_minimo: Valor mínimo en pesos. Por defecto 1.000.000.
        presupuesto_maximo: Valor máximo en pesos. Por defecto 10.000 millones.
        dias_publicacion: Antigüedad máxima de publicación (1 a 90 días).
        incluir_contratacion_directa: True para incluir contratación
            directa y régimen especial sin ofertas.
        limite: Cantidad máxima de procesos, entre 1 y 100.
    """
    try:
        limite = validar_limite(limite)

        if isinstance(dias_publicacion, bool) or not isinstance(
            dias_publicacion, int
        ):
            raise ErrorConsulta("dias_publicacion debe ser un número entero.")
        dias_publicacion = max(1, min(dias_publicacion, 90))

        if presupuesto_minimo < 0 or presupuesto_maximo < presupuesto_minimo:
            raise ErrorConsulta(
                "el rango de presupuesto no es válido "
                "(mínimo ≥ 0 y máximo ≥ mínimo)."
            )

        # ---- Sectores ----
        if sectores:
            claves = [quitar_tildes(s).lower() for s in sectores]
            desconocidos = [c for c in claves if c not in SECTORES]
            if desconocidos:
                raise ErrorConsulta(
                    f"sector(es) no reconocido(s): {', '.join(desconocidos)}. "
                    f"Use: {', '.join(SECTORES)}."
                )
        else:
            claves = list(SECTORES)

        palabras = list(
            dict.fromkeys(p for c in claves for p in SECTORES[c])
        )

        # ---- Filtros ----
        hoy = hoy_colombia().date()
        desde = (hoy - timedelta(days=dias_publicacion)).isoformat()

        excluidas = list(MODALIDADES_EXCLUIDAS)
        if not incluir_contratacion_directa:
            excluidas += MODALIDADES_SIN_COMPETENCIA

        campos_texto = [
            "nombre_del_procedimiento",
            "descripci_n_del_procedimiento",
        ]
        filtro_sector = (
            "("
            + " OR ".join(
                f"upper({campo}) like '%{escapar_soql(patron_sector(p))}%'"
                for p in palabras
                for campo in campos_texto
            )
            + ")"
        )

        filtros = [
            f"estado_del_procedimiento in {lista_soql(ESTADOS_ABIERTOS)}",
            f"precio_base between {int(presupuesto_minimo)} "
            f"and {int(presupuesto_maximo)}",
            f"fecha_de_publicacion_del >= '{desde}'",
            f"(fecha_de_recepcion_de IS NULL OR "
            f"fecha_de_recepcion_de >= '{hoy.isoformat()}')",
            f"modalidad_de_contratacion not in {lista_soql(excluidas)}",
            filtro_sector,
        ]

        if departamento and departamento.strip():
            filtros.append(filtro_departamento(departamento))

        # Con todos los sectores y 15 días hay más de 1.000 filas
        # (verificado: 1.316 el 26-oct-2026), así que se pagina.
        datos = sin_duplicados(
            await consultar_paginado(" AND ".join(filtros))
        )

    except ErrorConsulta as error:
        return f"Error: {error}"

    if not datos:
        return (
            "No hay oportunidades abiertas con esos criterios en los "
            f"últimos {dias_publicacion} días."
        )

    # Los de cierre más próximo primero; sin fecha de cierre al final.
    datos.sort(
        key=lambda p: (
            dias_restantes(p) is None,
            dias_restantes(p) if dias_restantes(p) is not None else 0,
        )
    )
    total = len(datos)
    datos = datos[:limite]

    conteo_sector: dict[str, int] = {}
    fichas = []
    for i, proceso in enumerate(datos, start=1):
        precio = a_numero(proceso.get("precio_base"))
        sector = detectar_sector(proceso)
        conteo_sector[sector] = conteo_sector.get(sector, 0) + 1
        dias = dias_restantes(proceso)
        urgente = " ⚠ URGENTE" if dias is not None and dias <= 5 else ""

        fichas.append(
            f"{i}. [{calcular_accion(proceso, precio)}]{urgente} "
            f"{proceso.get('descripci_n_del_procedimiento') or proceso.get('nombre_del_procedimiento', 'Sin descripción')}\n"
            f"   Entidad: {proceso.get('entidad', '—')} (NIT {proceso.get('nit_entidad', '—')})\n"
            f"   Ubicación: {proceso.get('departamento_entidad', '—')} — {proceso.get('ciudad_entidad', '—')}\n"
            f"   Presupuesto: {formato_pesos(precio)} | Relevancia: {calcular_relevancia(precio)}\n"
            f"   Modalidad: {proceso.get('modalidad_de_contratacion', '—')}\n"
            f"   Sector: {sector}\n"
            f"   Publicado: {formato_fecha(proceso.get('fecha_de_publicacion_del'))}"
            f" | Cierre de ofertas: {formato_fecha(proceso.get('fecha_de_recepcion_de'))}"
            f" ({texto_dias(dias)})\n"
            f"   ID: {proceso.get('id_del_proceso', '—')} | Referencia: {proceso.get('referencia_del_proceso', '—')}\n"
            f"   Enlace: {obtener_enlace(proceso)}"
        )

    resumen_sector = ", ".join(
        f"{s}: {n}" for s, n in sorted(
            conteo_sector.items(), key=lambda x: -x[1]
        )
    )
    encabezado = (
        f"RADAR SECOP II — {hoy.isoformat()}\n"
        f"Oportunidades abiertas encontradas: {total}"
        f"{f' (se muestran {limite})' if total > limite else ''}\n"
        f"Filtro: {formato_pesos(presupuesto_minimo)} a "
        f"{formato_pesos(presupuesto_maximo)} | publicados desde {desde}"
        f" | sectores: {', '.join(claves)}"
        f"{f' | departamento: {departamento}' if departamento else ''}\n"
        f"Por sector (mostrados): {resumen_sector}"
    )
    return encabezado + "\n\n" + "\n\n".join(fichas)


# =====================================================
# 6. HERRAMIENTA MCP: DETALLE DE UN PROCESO
# =====================================================

@mcp.tool()
async def detalle_proceso(identificador: str) -> str:
    """
    Devuelve la ficha completa de un proceso de SECOP II.

    Parámetros:
        identificador: ID del proceso (CO1.REQ.###), ID del portafolio
            (CO1.BDOS.###) o la referencia asignada por la entidad
            (ej.: FDLSUBA-LP-010-2026).

    Incluye fechas clave, estado, número de oferentes, código UNSPSC,
    el adjudicatario y el valor adjudicado si existen, y la lista de
    fases del proceso (cada fase es un registro aparte en SECOP II).
    """
    if not identificador or not identificador.strip():
        return "Error: debes proporcionar el ID o la referencia del proceso."

    valor = identificador.strip()
    clave = valor.upper()
    if clave.startswith("CO1.REQ."):
        where = f"id_del_proceso = '{escapar_soql(clave)}'"
    elif clave.startswith("CO1.BDOS."):
        where = f"id_del_portafolio = '{escapar_soql(clave)}'"
    else:
        where = (
            f"upper(referencia_del_proceso) like "
            f"'%{escapar_soql(clave)}%'"
        )

    try:
        datos = await consultar_secop(
            {
                "$where": where,
                "$limit": 50,
                "$order": "fecha_de_ultima_publicaci DESC",
            }
        )

        # Trae todas las fases del mismo portafolio para mostrar la
        # vigente y el historial (búsqueda exacta, rápida).
        portafolios = list(dict.fromkeys(
            p["id_del_portafolio"] for p in datos if p.get("id_del_portafolio")
        ))[:10]
        fases = []
        if portafolios:
            fases = await consultar_secop(
                {
                    "$where": f"id_del_portafolio in {lista_soql(portafolios)}",
                    "$limit": 200,
                    "$order": "fecha_de_ultima_publicaci DESC",
                }
            )
    except ErrorConsulta as error:
        return f"Error: {error}"

    if not datos:
        return f"No se encontró ningún proceso con '{valor}'."

    unicos = sin_duplicados(fases or datos)
    if len(unicos) > 1:
        lista = "\n".join(
            f"- {p.get('id_del_proceso')} | {p.get('referencia_del_proceso') or '—'}"
            f" | {p.get('entidad') or '—'}"
            for p in unicos[:10]
        )
        return (
            f"'{valor}' coincide con {len(unicos)} procesos distintos. "
            f"Consulte de nuevo con el ID exacto:\n{lista}"
        )

    p = unicos[0]
    precio = a_numero(p.get("precio_base"))
    dias = dias_restantes(p)

    adjudicacion = "No adjudicado"
    if (p.get("adjudicado") or "").strip().lower() == "si":
        adjudicacion = (
            f"{p.get('nombre_del_proveedor', '—')} "
            f"(NIT {p.get('nit_del_proveedor_adjudicado', '—')}) — "
            f"{formato_pesos(p.get('valor_total_adjudicacion'))} — "
            f"{formato_fecha(p.get('fecha_adjudicacion'))}"
        )

    return (
        f"FICHA DEL PROCESO {p.get('id_del_proceso', '—')}\n"
        f"Referencia: {p.get('referencia_del_proceso', '—')}\n"
        f"Entidad: {p.get('entidad', '—')} (NIT {p.get('nit_entidad', '—')}, "
        f"orden {p.get('ordenentidad', '—')})\n"
        f"Ubicación: {p.get('departamento_entidad', '—')} — {p.get('ciudad_entidad', '—')}\n"
        f"Unidad de contratación: {p.get('nombre_de_la_unidad_de', '—')}\n\n"
        f"Nombre: {p.get('nombre_del_procedimiento', '—')}\n"
        f"Objeto: {p.get('descripci_n_del_procedimiento', '—')}\n\n"
        f"Modalidad: {p.get('modalidad_de_contratacion', '—')}\n"
        f"Justificación: {p.get('justificaci_n_modalidad_de', '—')}\n"
        f"Tipo de contrato: {p.get('tipo_de_contrato', '—')}\n"
        f"Presupuesto oficial: {formato_pesos(precio)} "
        f"(relevancia {calcular_relevancia(precio)})\n"
        f"Plazo: {p.get('duracion', '—')} {p.get('unidad_de_duracion', '')}\n"
        f"Código UNSPSC principal: {p.get('codigo_principal_de_categoria', '—')}\n\n"
        f"Estado: {p.get('estado_del_procedimiento', '—')} | "
        f"Fase: {p.get('fase', '—')} | Resumen: {p.get('estado_resumen', '—')}\n"
        f"Publicación: {formato_fecha(p.get('fecha_de_publicacion_del'))}\n"
        f"Cierre de ofertas: {formato_fecha(p.get('fecha_de_recepcion_de'))} "
        f"({texto_dias(dias)})\n"
        f"Apertura de ofertas: {formato_fecha(p.get('fecha_de_apertura_de_respuesta'))}\n\n"
        f"Proveedores con respuesta: {p.get('proveedores_unicos_con', '—')} | "
        f"Respuestas: {p.get('respuestas_al_procedimiento', '—')} | "
        f"Lotes: {p.get('numero_de_lotes', '—')}\n"
        f"Adjudicación: {adjudicacion}\n"
        f"Acción sugerida: {calcular_accion(p, precio)}\n\n"
        f"Enlace: {obtener_enlace(p)}"
        f"{historial_fases(p, fases)}"
    )


def historial_fases(vigente: dict, fases: list[dict]) -> str:
    """Lista las fases del portafolio, de la más reciente a la más antigua."""
    vistas = {}
    for f in fases:
        clave = f.get("id_del_proceso")
        if clave and clave not in vistas:
            vistas[clave] = f
    if len(vistas) <= 1:
        return ""
    lineas = [
        f"- {f.get('id_del_proceso')} | {f.get('fase', '—')} | "
        f"{f.get('estado_del_procedimiento', '—')} | última publicación "
        f"{formato_fecha(f.get('fecha_de_ultima_publicaci'))}"
        f"{'  <- vigente' if f.get('id_del_proceso') == vigente.get('id_del_proceso') else ''}"
        for f in vistas.values()
    ]
    return (
        f"\n\nFases del proceso (portafolio {vigente.get('id_del_portafolio', '—')}):\n"
        + "\n".join(lineas)
    )


# =====================================================
# 7. TRANSPORTE STREAMABLE HTTP
# =====================================================
# streamable_http_path="/" (arriba) hace que la sub-app responda en su raíz.
# Se monta en /mcp; el middleware de abajo evita el redirect 307 /mcp -> /mcp/.

mcp_http_app = mcp.streamable_http_app()

# =====================================================
# 8. CICLO DE VIDA DEL SERVIDOR
# =====================================================

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield

# =====================================================
# 9. APLICACIÓN FASTAPI
# =====================================================

app = FastAPI(
    title="SECOP Colombia MCP Server",
    version="2.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Endpoint de salud para Render."""
    return {
        "estado": "activo",
        "servicio": "SECOP Colombia MCP Server",
        "version": "2.1.0",
        "transporte": "Streamable HTTP",
        "endpoint_mcp": "/mcp",
        "herramientas": [
            "buscar_procesos_secop",
            "radar_oportunidades",
            "detalle_proceso",
        ],
        "token_socrata": bool(SOCRATA_APP_TOKEN),
    }

# =====================================================
# 10. MONTAR MCP EN FASTAPI
# =====================================================

@app.middleware("http")
async def sin_redirect_mcp(request, call_next):
    """Autentica el transporte MCP y evita el redirect 307 de /mcp."""
    if request.scope["path"] == "/mcp":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"

    ruta = request.scope["path"]
    if ruta == "/mcp/" or ruta.startswith("/mcp/"):
        clave_configurada = os.environ.get("MCP_API_KEY", "").strip()
        if not clave_configurada:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "MCP_API_KEY no está configurada en el servidor."
                },
            )

        if not api_key_autorizada(
            request.headers.get("authorization"), clave_configurada
        ):
            return JSONResponse(
                status_code=401,
                content={"error": "Autenticación MCP requerida o inválida."},
                headers={"WWW-Authenticate": "Bearer"},
            )

    return await call_next(request)

app.mount("/mcp", mcp_http_app)

# =====================================================
# 11. ENTRYPOINT (respeta PORT de Render)
# =====================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
