from fastapi import FastAPI, Request, Response
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 1. Inicializar el servidor MCP y la app de FastAPI
app = FastAPI(title="SECOP II MCP Server", version="1.0.0")
mcp_server = Server("secop-mcp-server")

# 2. Registrar las herramientas del servidor
@mcp_server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="buscar_procesos_secop",
            description="Busca y analiza procesos de contratación en SECOP II.",
            inputSchema={
                "type": "object",
                "properties": {
                    "termino": {
                        "type": "string",
                        "description": "Término o número de proceso a consultar",
                    }
                },
                "required": ["termino"],
            },
        )
    ]

@mcp_server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    if name == "buscar_procesos_secop":
        termino = arguments.get("termino", "") if arguments else ""
        return [types.TextContent(type="text", text=f"Resultados para el proceso: {termino}")]
    raise ValueError(f"Herramienta desconocida: {name}")

# 3. Configurar el transporte SSE
sse_transport = SseServerTransport("/mcp/sse")

@app.get("/")
async def raiz():
    return {"status": "activo", "servicio": "SECOP II MCP Server - Socrata API"}

# 4. Endpoint GET para el flujo SSE
@app.get("/mcp/sse")
async def handle_sse_connect(request: Request):
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0], streams[1], mcp_server.create_initialization_options()
        )
    return Response(status_code=200)

# 5. Endpoint POST para recibir los mensajes del cliente
@app.post("/mcp/sse")
async def handle_sse_messages(request: Request):
    await sse_transport.handle_post_message(
        request.scope, request.receive, request._send
    )
    return Response(status_code=200)
