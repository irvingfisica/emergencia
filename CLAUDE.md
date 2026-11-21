# emergencia

Inferir las reglas locales mínimas de agentes que reproducen patrones colectivos
observados. Primer caso: organización espacial del comercio (DENUE) sobre la red
de calles. El plan completo está en [README.md](README.md) y los datos en
[DATOS.md](DATOS.md).

- Repo **público**: no mencionar otros proyectos, clientes ni infraestructura privada
  (nombres de máquinas, rutas internas, servicios). Solo fuentes públicas.
- Todo en español y UTF-8. Entorno con `uv` (`uv sync`, `uv run ...`).
- Los datos no van en git (`datos/` está ignorada). Todo dato debe poder
  reconstruirse con los scripts del repo desde fuentes públicas.
- Restricción de diseño central: las reglas de los agentes solo usan información
  local. Ningún módulo del simulador debe exponer estadísticas globales a los agentes.
