import httpx
from fastapi import FastAPI, Request
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 1. Inicializar FastAPI y el Servidor MCP (versión compatible 1.x)
app = FastAPI(title="SECOP II MCP Server", version="1.0.0")
mcp_server = Server("SECOP-Colombia-Server")

SECOP_II_DATASET_ID = "p6dx-8zbt"
BASE_URL = f"https://www.datos.gov.co/resource/{SECOP_II_DATASET_ID}.json"

# 2. Registrar la herramienta de SECOP II
@mcp_server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="buscar_procesos_secop",
            description="Busca y analiza procesos de contratación en SECOP II de Colombia por palabra clave.",
            inputSchema={
                "type": "object",
                "properties": {
                    "termino": {
                        "type": "string",
                        "description": "Palabra clave a buscar en el objeto del proceso (ej. 'software', 'vigilancia')."
                    },
                    "departamento": {
                        "type": "string",
                        "description": "Opcional. Filtrar por departamento (ej. 'Bogotá D.C.', 'Antioquia')."
                    },
                    "limite": {
                        "type": "integer",
                        "description": "Cantidad máxima de registros a retornar (por defecto 5)."
                    }
                },
                "required": ["termino"]
            },
        )
    ]

@mcp_server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    if name != "buscar_procesos_secop":
        raise ValueError(f"Herramienta desconocida: {name}")
    
    args = arguments or {}
    termino = args.get("termino", "")
    departamento = args.get("departamento")
    limite = args.get("limite", 5)

    where_clause = f"(lower(nombre_de_la_entidad) like '%{termino.lower()}%' or lower(descripcion_del_procedimiento) like '%{termino.lower()}%')"
    if departamento:
        where_clause += f" and departamento = '{departamento.upper()}'"
        
    params = {
        "$where": where_clause,
        "$limit": limite,
        "$order": "fecha_de_publicacion_del_proceso DESC"
    }
    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(BASE_URL, params=params, headers=headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                return [types.TextContent(type="text", text=f"No se encontraron procesos recientes con el término '{termino}'.")]
            
            resultado = []
            for proceso in data:
                item = (
                    f"🏢 **Entidad:** {proceso.get('nombre_de_la_entidad', 'N/A')}\n"
                    f"🆔 **ID Proceso:** {proceso.get('id_del_proceso', 'N/A')}\n"
                    f"📝 **Objeto:** {proceso.get('descripcion_del_procedimiento', 'N/A')}\n"
                    f"💰 **Valor Estimado:** ${proceso.get('precio_base', 'No definido')}\n"
                    f"📌 **Fase:** {proceso.get('fase', 'N/A')} | **Estado:** {proceso.get('estado_del_procedimiento', 'N/A')}\n"
                    f"📅 **Publicación:** {proceso.get('fecha_de_publicacion_del_proceso', 'N/A')}\n"
                    f"{'-'*40}"
                )
                resultado.append(item)
                
            return [types.TextContent(type="text", text="\n\n".join(resultado))]
            
        except httpx.HTTPStatusError as e:
            return [types.TextContent(type="text", text=f"Error al consultar la API de Datos Abiertos: {e.response.status_code}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Ocurrió un error inesperado: {str(e)}")]

# 3. Configurar el transporte SSE apuntando a /sse
sse_transport = SseServerTransport("/sse")

@app.get("/")
async def raiz():
    return {"status": "activo", "servicio": "SECOP II MCP Server - SseServerTransport"}

@app.get("/sse")
async def handle_sse_connect(request: Request):
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0], streams[1], mcp_server.create_initialization_options()
        )

@app.post("/sse")
async def handle_sse_messages(request: Request):
    await sse_transport.handle_post_message(
        request.scope, request.receive, request._send
    )
