import contextlib

import httpx

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer


# =========================================================
# 1. CONFIGURACIÓN DEL SERVIDOR MCP
# =========================================================

mcp = MCPServer(
    "SECOP_FL",
    version="1.0.0"
)

SECOP_API_URL = (
    "https://www.datos.gov.co/resource/p6dx-8zbt.json"
)


# =========================================================
# 2. FUNCIONES AUXILIARES
# =========================================================

def escapar_soql(valor: str) -> str:
    """
    Escapa comillas simples para utilizarlas
    en literales de texto SoQL.
    """
    return valor.replace("'", "''")


def construir_filtro(campo: str, valor: str) -> str:
    """
    Construye un filtro SoQL.

    Los nombres de campo deben proceder exclusivamente
    de constantes definidas en el código.
    """
    valor_seguro = escapar_soql(valor.strip().upper())

    return (
        f"upper({campo}) "
        f"like '%{valor_seguro}%'"
    )


# =========================================================
# 3. HERRAMIENTA DE BÚSQUEDA SECOP II
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
    entidad: nombre o fragmento del nombre de la entidad.
    objeto: palabras clave del objeto contractual.
    modalidad: modalidad de contratación.
    limite: número máximo de resultados, entre 1 y 100.
    """

    # -----------------------------------------------------
    # Validar límite
    # -----------------------------------------------------

    if isinstance(limite, bool) or not isinstance(limite, int):
        return "Error: el límite debe ser un número entero."

    limite = max(1, min(limite, 100))

    # -----------------------------------------------------
    # Construir filtros
    # -----------------------------------------------------

    filtros = []

    if entidad and entidad.strip():
        filtros.append(
            construir_filtro("entidad", entidad)
        )

    if objeto and objeto.strip():
        filtros.append(
            construir_filtro(
                "descripci_n_del_procedimiento",
                objeto
            )
        )

    if modalidad and modalidad.strip():
        filtros.append(
            construir_filtro(
                "modalidad_de_contratacion",
                modalidad
            )
        )

    # -----------------------------------------------------
    # Preparar consulta
    # -----------------------------------------------------

    parametros = {
        "$limit": limite,
        "$order": "fecha_de_publicacion_del DESC",
    }

    if filtros:
        parametros["$where"] = " AND ".join(filtros)

    # -----------------------------------------------------
    # Consultar datos abiertos
    # -----------------------------------------------------

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

    except httpx.TimeoutException:
        return (
            "Error: la consulta a SECOP II "
            "superó el tiempo máximo de espera."
        )

    except httpx.HTTPStatusError as exc:
        detalle = exc.response.text[:500]

        return (
            f"Error HTTP {exc.response.status_code} "
            f"al consultar SECOP II. "
            f"Respuesta: {detalle}"
        )

    except httpx.RequestError as exc:
        return (
            "Error de conexión con la API de SECOP II: "
            f"{str(exc)}"
        )

    except ValueError:
        return (
            "Error: SECOP II devolvió una respuesta "
            "que no contiene JSON válido."
        )

    # -----------------------------------------------------
    # Validar respuesta
    # -----------------------------------------------------

    if not isinstance(datos, list):
        return (
            "Error: la API devolvió un formato "
            "de respuesta inesperado."
        )

    if not datos:
        return (
            "No se encontraron procesos con "
            "los criterios especificados."
        )

    # -----------------------------------------------------
    # Formatear resultados
    # -----------------------------------------------------

    resultados = []

    for articulo in datos:

        url_proceso = articulo.get("urlproceso")

        if isinstance(url_proceso, dict):
            enlace = (
                url_proceso.get("url")
                or url_proceso.get("value")
            )
        else:
            enlace = url_proceso

        item = (
            f"ID del proceso: "
            f"{articulo.get('id_del_proceso', 'N/A')}\n"

            f"Entidad: "
            f"{articulo.get('entidad', 'N/A')}\n"

            f"Procedimiento: "
            f"{articulo.get('nombre_del_procedimiento', 'N/A')}\n"

            f"Objeto: "
            f"{articulo.get('descripci_n_del_procedimiento', 'N/A')}\n"

            f"Modalidad: "
            f"{articulo.get('modalidad_de_contratacion', 'N/A')}\n"

            f"Precio base: "
            f"${articulo.get('precio_base', 'N/A')}\n"

            f"Fase: "
            f"{articulo.get('fase', 'N/A')}\n"

            f"Fecha de publicación: "
            f"{articulo.get('fecha_de_publicacion_del', 'N/A')}\n"

            f"Enlace: {enlace or 'N/A'}"
        )

        resultados.append(item)

    return "\n\n".join(resultados)


# =========================================================
# 4. TRANSPORTE MCP STREAMABLE HTTP
# =========================================================

mcp_http_app = mcp.streamable_http_app()


# =========================================================
# 5. CICLO DE VIDA DE FASTAPI
# =========================================================

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):

    # Inicializar los recursos del servidor MCP.
    async with mcp.session_manager.run():
        yield


# =========================================================
# 6. APLICACIÓN WEB
# =========================================================

app = FastAPI(
    title="SECOP II MCP Server",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def raiz():
    return {
        "estado": "activo",
        "servicio": "SECOP II MCP Server",
        "mcp": "/mcp"
    }


# Montar el transporte MCP.
app.mount("/mcp", mcp_http_app)
