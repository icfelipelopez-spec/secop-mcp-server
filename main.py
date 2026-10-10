import httpx
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# =========================================================
# CONFIGURACIÓN
# =========================================================

mcp = FastMCP("SECOP_FL")

SECOP_API_URL = "https://www.datos.gov.co/resource/p6dx-8zbt.json"


# =========================================================
# UTILIDADES
# =========================================================

def escapar_soql(valor: str) -> str:
    """Escapa comillas simples para literales SoQL."""
    return valor.replace("'", "''")


def construir_filtro(campo: str, valor: str) -> str:
    """Construye un filtro LIKE con el valor escapado."""
    valor_seguro = escapar_soql(valor.upper())
    return f"upper({campo}) like '%{valor_seguro}%'"


# =========================================================
# HERRAMIENTA MCP
# =========================================================

@mcp.tool()
async def buscar_procesos_secop(
    entidad: str | None = None,
    objeto: str | None = None,
    modalidad: str | None = None,
    limite: int = 5
) -> str:
    """
    Busca procesos de contratación pública en SECOP II.

    Parámetros:
    - entidad: nombre o fragmento del nombre de la entidad.
    - objeto: texto que identifica el objeto del proceso.
    - modalidad: modalidad de contratación.
    - limite: cantidad máxima de resultados, entre 1 y 100.
    """

    if not isinstance(limite, int) or isinstance(limite, bool):
        return "Error: el límite debe ser un número entero."

    limite = max(1, min(limite, 100))
    filtros = []

    if entidad and entidad.strip():
        filtros.append(construir_filtro("entidad", entidad.strip()))

    if objeto and objeto.strip():
        filtros.append(construir_filtro("descripci_n_del_procedimiento", objeto.strip()))

    if modalidad and modalidad.strip():
        filtros.append(construir_filtro("modalidad_de_contratacion", modalidad.strip()))

    parametros = {
        "$limit": limite,
        "$order": "fecha_de_publicacion_del DESC",
    }

    if filtros:
        parametros["$where"] = " AND ".join(filtros)

    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True
        ) as cliente:
            respuesta = await cliente.get(
                SECOP_API_URL,
                params=parametros
            )
            respuesta.raise_for_status()
            datos = respuesta.json()

            if not isinstance(datos, list):
                return "Error: la API de SECOP II devolvió una respuesta inesperada."

    except httpx.TimeoutException:
        return "Error: la consulta a SECOP II superó el tiempo máximo de espera."

    except httpx.HTTPStatusError as exc:
        return f"Error HTTP al consultar SECOP II: {exc.response.status_code}. Verifica los filtros."

    except httpx.RequestError as exc:
        return f"Error de conexión con SECOP II: {str(exc)}"

    except ValueError:
        return "Error: la respuesta de SECOP II no contiene JSON válido."

    if not datos:
        return "No se encontraron procesos con los criterios especificados."

    resultados = []
    for articulo in datos:
        url_proceso = articulo.get("urlproceso")
        if isinstance(url_proceso, dict):
            enlace = url_proceso.get("url") or url_proceso.get("value")
        else:
            enlace = url_proceso

        item = (
            f"ID del proceso: {articulo.get('id_del_proceso', 'N/A')}\n"
            f"Entidad: {articulo.get('entidad', 'N/A')}\n"
            f"Procedimiento: {articulo.get('nombre_del_procedimiento', 'N/A')}\n"
            f"Objeto: {articulo.get('descripci_n_del_procedimiento', 'N/A')}\n"
            f"Modalidad: {articulo.get('modalidad_de_contratacion', 'N/A')}\n"
            f"Precio base: ${articulo.get('precio_base', 'N/A')}\n"
            f"Fase: {articulo.get('fase', 'N/A')}\n"
            f"Fecha de publicación: {articulo.get('fecha_de_publicacion_del', 'N/A')}\n"
            f"Enlace: {enlace or 'N/A'}"
        )
        resultados.append(item)

    return "\n\n".join(resultados)


# =========================================================
# APLICACIÓN FASTAPI
# =========================================================

app = FastAPI(
    title="SECOP II MCP Server",
    version="1.0.0"
)


@app.get("/")
async def raiz():
    return {
        "estado": "activo",
        "servicio": "SECOP II MCP Server"
    }


# Montar las rutas nativas SSE que FastMCP maneja internamente
app.mount("/mcp", mcp.sse_app())
