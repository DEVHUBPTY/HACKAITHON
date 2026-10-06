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

## Paso 2 · Aprobación humana

- Aprueba **una persona distinta al autor** del cambio.
- Verifica la **intención**: ¿resuelve lo que pide la spec, o solo hace pasar el test?
- Prueba al menos un caso borde a mano.

## Paso 3 · Si algo falla

1. Registrar la prueba fallida en Notion (base *Pruebas*, estado **Falla**) **antes** de corregir.
2. Corregir.
3. Cambiar el estado a **Corregido** y describir la corrección.

Así se puede responder la pregunta del jurado: *"Muéstrame una decisión, una prueba fallida y su corrección."*
