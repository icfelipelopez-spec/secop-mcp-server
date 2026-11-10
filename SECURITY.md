# Seguridad del servidor MCP SECOP

## Autenticación

El transporte MCP (`/mcp` y sus rutas subordinadas) requiere una API Key enviada como cabecera HTTP:

```http
Authorization: Bearer <MCP_API_KEY>
```

La clave se lee exclusivamente desde la variable de entorno `MCP_API_KEY`. No debe guardarse en el repositorio, en archivos de configuración versionados, ni en logs. La comparación se realiza con `hmac.compare_digest`.

- Sin `MCP_API_KEY` configurada, el transporte MCP responde `503` (fail closed).
- Sin credencial o con credencial inválida, responde `401` y `WWW-Authenticate: Bearer`.
- `/health` permanece público para el health check de Render y no revela la clave.
- La autenticación se aplica al transporte MCP; no sustituye TLS, controles de acceso de la plataforma ni la rotación de secretos.

## Configuración de Render

1. Generar una clave aleatoria robusta (mínimo 32 bytes), por ejemplo con `openssl rand -hex 32`.
2. En el servicio `secop-mcp-server`, abrir **Environment** y crear `MCP_API_KEY` con el valor generado.
3. Guardar el secreto en el gestor de secretos; no copiarlo en GitHub ni en mensajes.
4. Desplegar primero esta rama en un entorno de pruebas. No desplegar sobre producción hasta verificar las pruebas descritas abajo y configurar el cliente MCP con el mismo secreto.

## Configuración del cliente MCP

El cliente debe enviar `Authorization: Bearer <MCP_API_KEY>` en cada solicitud HTTP al endpoint `https://secop-mcp-server-sxyq.onrender.com/mcp`. La configuración exacta del esquema `API_KEY` en Composio debe corresponder a este formato de cabecera y prefijo Bearer. No registrar el toolkit con `NO_AUTH`.

## Pruebas locales

```bash
python -m unittest discover -s tests -v
```

Pruebas de integración recomendadas después del despliegue de staging:

1. `GET /health` sin credenciales: `200`.
2. `POST /mcp` sin credenciales: `401`.
3. `POST /mcp` con clave incorrecta: `401`.
4. `POST /mcp` con `Authorization: Bearer <clave correcta>`: respuesta MCP, no `401`.
5. `initialize` seguido de `tools/list`: aparecen `buscar_procesos_secop`, `radar_oportunidades` y `detalle_proceso`.
