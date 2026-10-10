import httpx
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# 1. Inicializar FastMCP con el nombre de tu servidor
mcp = FastMCP("SECOP-Colombia-Server")

# ID oficial del Dataset de SECOP II en datos.gov.co
SECOP_II_DATASET_ID = "p6dx-8zbt"
BASE_URL = f"https://datos.gov.co{SECOP_II_DATASET_ID}.json"

# 2. Definición de la Herramienta (Tool) para el LLM
@mcp.tool()
async def buscar_procesos_secop(
    termino: str, 
    departamento: str = None, 
    limite: int = 5
) -> str:
    """
    Busca procesos de contratación en SECOP II de Colombia por palabra clave.
    
    :param termino: Palabra clave a buscar en el objeto del proceso (ej. 'software', 'vigilancia').
    :param departamento: Opcional. Filtrar por departamento (ej. 'Bogotá D.C.', 'Antioquia').
    :param limite: Cantidad máxima de registros a retornar (por defecto 5).
    """
    # Construcción de la consulta SoQL para la API de Socrata
    where_clause = f"(lower(nombre_de_la_entidad) like '%{termino.lower()}%' or lower(descripcion_del_procedimiento) like '%{termino.lower()}%')"
    
    if departamento:
        where_clause += f" and departamento = '{departamento.upper()}'"
        
    params = {
        "$where": where_clause,
        "$limit": limite,
        "$order": "fecha_de_publicacion_del_proceso DESC"
    }
    
    headers = {
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(BASE_URL, params=params, headers=headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                return f"No se encontraron procesos recientes con el término '{termino}'."
            
            resultado = []
            for proceso in data:
                item = (
                    f"🏢 **Entidad:** {proceso.get('nombre_de_la_entidad')}\n"
                    f"🆔 **ID Proceso:** {proceso.get('id_del_proceso')}\n"
                    f"📝 **Objeto:** {proceso.get('descripcion_del_procedimiento')}\n"
                    f"💰 **Valor Estimado:** ${proceso.get('precio_base', 'No definido')}\n"
                    f"📌 **Fase:** {proceso.get('fase', 'N/A')} | **Estado:** {proceso.get('estado_del_procedimiento')}\n"
                    f"📅 **Publicación:** {proceso.get('fecha_de_publicacion_del_proceso', 'N/A')}\n"
                    f"🔗 [Ver en SECOP](https://secop.gov.co{proceso.get('id_del_proceso')})\n"
                    f"{'-'*40}"
                )
                resultado.append(item)
                
            return "\n\n".join(resultado)
            
        except httpx.HTTPStatusError as e:
            return f"Error al consultar la API de Datos Abiertos: {e.response.status_code}"
        except Exception as e:
            return f"Ocurrió un error inesperado: {str(e)}"

# 3. EXPORTAR LA APLICACIÓN WEB PARA RENDER
# Esto genera automáticamente los endpoints internos correctos (GET /sse y POST /messages)
app = mcp.sse_app()
