# Cinco fichas trazables (C-01)

**BORRADOR · requiere revisión**

> REVISIÓN PROVISIONAL DEL ASISTENTE, NO HUMANA (D-101): la rehace una persona en C-09. Todo es BORRADOR.

Las fichas salen de la corrida guardada en senales.duckdb (reglas 1.3, corte 2026-10-07T00:41:03Z). Si el ranking cambia (C-10), se vuelve a correr este comando: es otra corrida, no se rehace el trabajo; los CASO- anteriores se conservan (registro de solo agregar).

## Regla de selección (`config/fichas_trazables.yaml`)

- Se recorre el ranking oficial (posición 1 = mayor P) y se toman, por estado de evidencia, los primeros: suficiente 2, parcial 2, insuficiente 1.
- Mínimo 5 fichas, al menos 1 con evidencia insuficiente (PDF sección 5). Si un estado no alcanza su cupo, se completa con el ranking: sí.

## Las fichas

| Caso | Grupo | Posición | P | Estado de evidencia | Titular central | Revisión | Borrador | Comprobaciones | Fallos |
|---|---|---|---|---|---|---|---|---|---|
| CASO-002 | GRP-21ad932d54 | 1 | 90.45 | insuficiente | Minsa enciende alarmas por diagnósticos de cáncer de mama en hombres en Panamá | requiere evidencia · provisional (D-101) | sin borrador en la caché de generación (no se llamó a ningún proveedor) | 25/25 | 0 |
| CASO-003 | GRP-81a11a5998 | 13 | 81.25 | parcial | ¿Cómo se fija el precio del combustible en Panamá? El MEF explica la fórmula quincenal tras aprobarse nuevo subsidio | aprobado como borrador · provisional (D-101) | sin borrador en la caché de generación (no se llamó a ningún proveedor) | 65/65 | 0 |
| CASO-004 | GRP-e78a143f9a | 36 | 73.16 | parcial | Ejecutivo sanciona la Ley 552 del Presupuesto del Canal de Panamá por $5,555 millones | aprobado como borrador · provisional (D-101) | sin borrador en la caché de generación (no se llamó a ningún proveedor) | 32/32 | 0 |
| CASO-005 | GRP-da35c3dead | 47 | 65.13 | suficiente | Mulino viajará a Asia: suscribirá convenios bilaterales con Singapur y Vietnam | aprobado como borrador · provisional (D-101) | versión 1 | 39/39 | 0 |
| CASO-006 | GRP-0dfdd5a021 | 54 | 50.39 | suficiente | Trump streicht Europa - Hilfe, lenkt Millionen nach Lateinamerika | aprobado como borrador · provisional (D-101) | sin borrador en la caché de generación (no se llamó a ningún proveedor) | 102/102 | 0 |

## Comprobaciones (proporciones con n e IC 95 % de Wilson)

| Comprobación | ok / n | Proporción | IC 95 % |
|---|---|---|---|
| `afirmacion_con_cita` | 33 / 33 | 100% | [90%, 100%] |
| `cita_con_id_en_datos` | 45 / 45 | 100% | [92%, 100%] |
| `cita_con_campo_y_valor` | 45 / 45 | 100% | [92%, 100%] |
| `cifra_de_conteo_coincide` | 15 / 15 | 100% | [80%, 100%] |
| `declaracion_literal` | 20 / 20 | 100% | [84%, 100%] |
| `url_presente` | 50 / 50 | 100% | [93%, 100%] |
| `procedencias_y_estado` | 5 / 5 | 100% | [57%, 100%] |
| `leyenda_de_alcance` | 5 / 5 | 100% | [57%, 100%] |
| `marca_borrador` | 5 / 5 | 100% | [57%, 100%] |
| `cinco_partes` | 5 / 5 | 100% | [57%, 100%] |
| `sin_descripcion_rss` | 20 / 20 | 100% | [84%, 100%] |
| `sin_nombres_de_autor` | 5 / 5 | 100% | [57%, 100%] |
| `contrato_fichas_jsonl` | 5 / 5 | 100% | [57%, 100%] |
| `revision_provisional_visible` | 5 / 5 | 100% | [57%, 100%] |

Resultado: **todas las comprobaciones pasan** · detalle por cita en `outputs/fichas_trazables/trazabilidad.json`.
