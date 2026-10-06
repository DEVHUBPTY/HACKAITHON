# Revisión de código

> No confundir con la **revisión editorial** del producto (etapa 7 del reto: estados de una ficha).
> Este documento es sobre revisar **cambios de código**.

## Paso 1 · Primera pasada de Claude Code

Pídele: *"Revisa el diff actual contra docs/REVISION.md y CLAUDE.md. Lista hallazgos por severidad."*

Checklist:

- [ ] Cumple todos los puntos de "Listo cuando" de la spec, con evidencia.
- [ ] `poetry run pytest -v` pasa completo.
- [ ] **Secretos:** ninguna clave, token o URL privada en código, tests, logs ni capturas; el filtro de redacción de logs sigue activo.
- [ ] **Costos:** el tope de costo del proveedor de pago sigue configurado.
- [ ] **Contrato de datos:** nombres de campos exactos; IDs con prefijo; fechas UTC; publicación ≠ detección.
- [ ] **Nulos:** ningún `fillna(0)` ni equivalente sobre valores de indicadores.
- [ ] **Citas:** toda afirmación generada pasa por el validador.
- [ ] **Inyección:** la evidencia sigue delimitada y separada de las instrucciones.
- [ ] **Configuración:** sin números mágicos ni `if modalidad` en `src/`; todo número nuevo está en `docs/parametros.md` con su origen.
- [ ] **Métricas:** toda proporción con n e intervalo de confianza.
- [ ] **Alcance:** nada de la lista "Lo que NUNCA se construye".
- [ ] **Benchmark reservado:** no se referencia en ningún lado.
- [ ] Dependencias nuevas agregadas con Poetry, justificadas, y `poetry.lock` actualizado en el commit.

## Paso 2 · Revisión independiente (D-78)

- Cada PR lo revisa un **agente revisor independiente, que no escribió el código**, contra la spec, `CLAUDE.md`, esta guía y las decisiones de Notion.
- Verifica la **intención**: ¿resuelve lo que pide la spec, o solo hace pasar el test?
- Prueba al menos un caso borde a mano (ejecutándolo, no solo leyendo el código).
- El **veredicto queda escrito** como comentario en el PR y en Notion (Backlog y Bitácora), con sus hallazgos.
- Solo con veredicto **favorable** el asistente integra el PR a `main`. Si hay observaciones, se corrigen (paso 3) y el PR se vuelve a revisar.
- El equipo sigue el trabajo por el chat y responde ahí las consultas.
- **Lo que el reto exige a personas lo sigue haciendo una persona**; el agente revisor no lo reemplaza: las etiquetas de evaluación las revisa y aprueba una persona del equipo (D-85), igual que las etiquetas del benchmark de desarrollo (E0-06), la revisión de validez de sustento (`docs/protocolo_evaluacion.md`, sección 4) y la revisión editorial de las fichas (etapa 7).

## Paso 3 · Si algo falla

1. Registrar la prueba fallida en Notion (base *Pruebas*, estado **Falla**) **antes** de corregir.
2. Corregir.
3. Cambiar el estado a **Corregido** y describir la corrección.

Así se puede responder la pregunta del jurado: *"Muéstrame una decisión, una prueba fallida y su corrección."*
