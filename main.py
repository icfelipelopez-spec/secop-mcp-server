import contextlib
import os

import httpx
import uvicorn

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP


# =====================================================
# 1. CONFIGURACIÓN DEL SERVIDOR MCP
# =====================================================

mcp = FastMCP(
    "SECOP-Colombia-Server",
    stateless_http=True,   # 🔑 Clave para clientes como Composio
)

SECOP_DATASET_URL = "https://www.datos.gov.co/resource/p6dx-8zbt.json"


# =====================================================
# 2. FUNCIONES AUXILIARES
# =====================================================

def escapar_soql(valor: str) -> str:
    """Escapa comillas simples en valores de texto SoQL."""
    return valor.replace("'", "''")


def construir_filtro(campo: str, valor: str) -> str:
    """Construye un filtro de búsqueda SoQL."""
    valor_seguro = escapar_soql(valor.strip().upper())
    return f"upper({campo}) like '%{valor_seguro}%'"


# =====================================================
# 3. HERRAMIENTA MCP: BÚSQUEDA DE PROCESOS SECOP II
# =====================================================

@mcp.tool()
async def buscar_procesos_secop(
    termino: str,
    departamento: str | None = None,
    limite: int = 5,
) -> str:
    """
    Busca procesos de contratación pública en SECOP II.

    Parámetros:
        termino:
            Palabra clave del objeto contractual o de la entidad.
        departamento:
            Departamento de la entidad contratante.
            Ejemplos: Bogotá D.C., Antioquia, Tolima.
        limite:
            Cantidad máxima de resultados, entre 1 y 100.
    """

    # -------------------------------------------------
    # VALIDACIÓN DE ENTRADAS
    # -------------------------------------------------

    if not termino or not termino.strip():
        return "Error: debes proporcionar una palabra clave."

    if isinstance(limite, bool) or not isinstance(limite, int):
        return "Error: el límite debe ser un número entero."

    limite = max(1, min(limite, 100))

    # -------------------------------------------------
    # CONSTRUCCIÓN DE LA CONSULTA
    # -------------------------------------------------

    palabra = termino.strip()

    filtros = [
        "("
        + construir_filtro("entidad", palabra)
        + " OR "
        + construir_filtro("descripci_n_del_procedimiento", palabra)
        + ")"
    ]

    if departamento and departamento.strip():
        filtros.append(
            construir_filtro("departamento_entidad", departamento)
        )

    parametros = {
        "$where": " AND ".join(filtros),
        "$limit": limite,
        "$order": "fecha_de_publicacion_del DESC",
    }

    # -------------------------------------------------
    # CONSULTA A DATOS ABIERTOS
    # -------------------------------------------------

    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
        ) as cliente:

            respuesta = await cliente.get(
                SECOP_DATASET_URL,
                params=parametros,
                headers={"Accept": "application/json"},
            )

            respuesta.raise_for_status()
            datos = respuesta.json()

    except httpx.TimeoutException:
        return (
            "Error: la consulta a SECOP II "
            "superó el tiempo máximo de espera."
        )

    except httpx.HTTPStatusError as error:
        return (
            f"Error HTTP {error.response.status_code} "
            "al consultar Datos Abiertos. "
            f"Detalle: {error.response.text[:400]}"
        )

    except httpx.RequestError as error:
        return f"Error de conexión con Datos Abiertos: {str(error)}"

    except ValueError:
        return "Error: la API no devolvió JSON válido."

    # -------------------------------------------------
    # VALIDACIÓN DE LA RESPUESTA
    # -------------------------------------------------

    if not isinstance(datos, list):
        return "Error: la API devolvió un formato inesperado."

    if not datos:
        return (
            f"No se encontraron procesos para "
            f"el término '{palabra}'."
        )

    # -------------------------------------------------
    # FORMATEO DE RESULTADOS
    # -------------------------------------------------

    resultados = []

    for proceso in datos:

        enlace = proceso.get("urlproceso")
        if isinstance(enlace, dict):
            enlace = enlace.get("url") or enlace.get("value")

        item = (
            f"ENTIDAD: {proceso.get('entidad', 'N/A')}\n"
            f"ID DEL PROCESO: {proceso.get('id_del_proceso', 'N/A')}\n"
            f"PROCEDIMIENTO: {proceso.get('nombre_del_procedimiento', 'N/A')}\n"
            f"OBJETO: {proceso.get('descripci_n_del_procedimiento', 'N/A')}\n"
            f"DEPARTAMENTO: {proceso.get('departamento_entidad', 'N/A')}\n"
            f"MODALIDAD: {proceso.get('modalidad_de_contratacion', 'N/A')}\n"
            f"PRECIO BASE: ${proceso.get('precio_base', 'N/A')}\n"
            f"FASE: {proceso.get('fase', 'N/A')}\n"
            f"FECHA DE PUBLICACIÓN: "
            f"{proceso.get('fecha_de_publicacion_del', 'N/A')}\n"
            f"URL DEL PROCESO: {enlace or 'N/A'}"
        )

        resultados.append(item)

    return "\n\n".join(resultados)


# =====================================================
# 4. TRANSPORTE STREAMABLE HTTP
# =====================================================
# path="/" hace que la sub-app MCP responda en su raíz.
# Al montarla en /mcp, la ruta final es /mcp (sin redirect).

mcp_http_app = mcp.streamable_http_app(path="/")


# =====================================================
# 5. CICLO DE VIDA DEL SERVIDOR
# =====================================================

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


# =====================================================
# 6. APLICACIÓN FASTAPI
# =====================================================

app = FastAPI(
    title="SECOP Colombia MCP Server",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Endpoint de salud para Render."""
    return {
        "estado": "activo",
        "servicio": "SECOP Colombia MCP Server",
        "transporte": "Streamable HTTP",
        "endpoint_mcp": "/mcp",
        "herramientas": ["buscar_procesos_secop"],
    }


# =====================================================
# 7. MONTAR MCP EN FASTAPI
# =====================================================

app.mount("/mcp", mcp_http_app)


# =====================================================
# 8. ENTRYPOINT (respeta PORT de Render)
# =====================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
