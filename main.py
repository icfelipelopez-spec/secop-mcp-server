import httpx
from fastapi import FastAPI, Request
from starlette.routing import Route
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# =========================================================
# SERVIDOR MCP Y HERRAMIENTAS
# =========================================================

server = Server("SECOP_FL")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="buscar_procesos_secop",
            description="Busca procesos de contratación pública en Colombia en la base de datos abierta de SECOP II.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entidad": {"type": "string", "description": "Nombre o parte del nombre de la entidad estatal"},
                    "objeto": {"type": "string", "description": "Palabra clave en la descripción del procedimiento"},
                    "modalidad": {"type": "string", "description": "Modalidad de contratación"},
                    "limite": {"type": "integer", "description": "Número máximo de resultados (1-100)", "default": 5}
                }
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "buscar_procesos_secop":
        raise ValueError(f"Herramienta desconocida: {name}")

    entidad = arguments.get("entidad")
    objeto = arguments.get("objeto")
    modalidad = arguments.get("modalidad")
    limite = arguments.get("limite", 5)

    if not isinstance(limite, int) or isinstance(limite, bool):
        return [types.TextContent(type="text", text="Error: el límite debe ser un número entero.")]
    limite = max(1, min(limite, 100))

    url = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
    filtros = []

    if entidad and entidad.strip():
        val = entidad.strip().upper().replace("'", "''")
        filtros.append(f"upper(entidad) like '%{val}%'")
    if objeto and objeto.strip():
        val = objeto.strip().upper().replace("'", "''")
        filtros.append(f"upper(descripci_n_del_procedimiento) like '%{val}%'")
    if modalidad and modalidad.strip():
        val = modalidad.strip().upper().replace("'", "''")
        filtros.append(f"upper(modalidad_de_contratacion) like '%{val}%'")

    parametros = {
        "$limit": limite,
        "$order": "fecha_de_publicacion_del DESC",
    }
    if filtros:
        parametros["$where"] = " AND ".join(filtros)

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as cliente:
        try:
            respuesta = await cliente.get(url, params=parametros)
            respuesta.raise_for_status()
            datos = respuesta.json()
        except Exception as e:
            error_msg = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else str(e)
            return [types.TextContent(type="text", text=f"Error al consultar la API de SECOP II: {error_msg}")]

    if not datos or not isinstance(datos, list):
        return [types.TextContent(type="text", text="No se encontraron procesos de contratación con los criterios especificados.")]

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

    return [types.TextContent(type="text", text="\n\n".join(resultados))]

# =========================================================
# TRANSPORTE Y RUTAS ASGI
# =========================================================

# Configurar transporte apuntando a /mcp/sse
sse = SseServerTransport("/mcp/sse")

async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

async def raiz(request: Request):
    return {"estado": "activo", "servicio": "SECOP II MCP Server"}

# Definición de la aplicación FastAPI con enrutamiento Starlette nativo
# para evitar conflictos de ciclo de vida ASGI en peticiones POST
app = FastAPI(
    title="SECOP II MCP Server",
    version="1.0.0",
    routes=[
        Route("/", raiz, methods=["GET"]),
        Route("/mcp/sse", handle_sse, methods=["GET"]),
        Route("/mcp/sse", sse.handle_post_message, methods=["POST"]),
    ]
)
