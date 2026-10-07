# Cinco fichas trazables (C-01)

**BORRADOR · requiere revisión**

> REVISIÓN PROVISIONAL DEL ASISTENTE, NO HUMANA (D-101): la rehace una persona en C-09. Todo es BORRADOR.

Las fichas salen de la corrida guardada en senales.duckdb (reglas 1.3, corte 2026-10-07T00:41:03Z). Si el ranking cambia (C-10), se vuelve a correr este comando: es otra corrida, no se rehace el trabajo; los CASO- anteriores se conservan (registro de solo agregar).

## Regla de selección (`config/fichas_trazables.yaml`, D-118)

- Una ficha por caso de uso del reto (PDF sección 4), en orden y sobre el ranking oficial (posición 1 = mayor P). Un grupo no se repite entre casos de uso.
- Mínimo 5 fichas, al menos 1 con evidencia insuficiente (PDF sección 5); si no hubiera ninguna, CU-04 se vuelve a elegir como insuficiente.

| Caso de uso | Pregunta | Criterio (en orden; el primero con algún grupo manda) |
|---|---|---|
| CU-01 | ¿Qué cinco temas merecen revisión para la agenda de Panamá y por qué? | `primero del ranking` |
| CU-02 | Tema económico con serie oficial y brief, sin confundir dato anual con medición de hoy | `tema=economia, con_dato_oficial=True` |
| CU-03 | Repetición frente a corroboración independiente; una agencia replicada cuenta como una procedencia | `mas_titulares_que_procedencias=True, procedencias_minimas=2` → `mas_titulares_que_procedencias=True, procedencias_minimas=1` |
| CU-04 | Cifra inexistente o contradicción: abstenerse o mostrar versiones, con la verificación pendiente | `contradiccion_abierta=True` → `estado=insuficiente, vacio=cifras_sin_dato_oficial` |
| CU-05 | ¿Qué señales públicas del entorno logístico debo revisar? | grupo fijo `GRP-da35c3dead` (banca); se reutiliza su CASO- |

## Las fichas

| Caso de uso | Caso | Grupo | Posición | P | Estado de evidencia | Elegida por | Titular central | Revisión | Borrador | Comprobaciones | Fallos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CU-01 | CASO-002 | GRP-21ad932d54 | 1 | 90.45 | insuficiente | primero del ranking | Minsa enciende alarmas por diagnósticos de cáncer de mama en hombres en Panamá | requiere evidencia · provisional (D-101) | sin borrador en la caché de generación (no se llamó a ningún proveedor) | 25/25 | 0 |
| CU-02 | CASO-003 | GRP-81a11a5998 | 13 | 81.25 | parcial | tema=economia, con_dato_oficial=True | ¿Cómo se fija el precio del combustible en Panamá? El MEF explica la fórmula quincenal tras aprobarse nuevo subsidio | aprobado como borrador · provisional (D-101) | sin borrador en la caché de generación (no se llamó a ningún proveedor) | 65/65 | 0 |
| CU-03 | CASO-006 | GRP-0dfdd5a021 | 54 | 50.39 | suficiente | mas_titulares_que_procedencias=True, procedencias_minimas=2 | Trump streicht Europa - Hilfe, lenkt Millionen nach Lateinamerika | aprobado como borrador · provisional (D-101) | sin borrador en la caché de generación (no se llamó a ningún proveedor) | 102/102 | 0 |
| CU-04 | CASO-007 | GRP-5e6531917f | 3 | 88.41 | insuficiente | estado=insuficiente, vacio=cifras_sin_dato_oficial (respaldo declarado) | Más de 30 mujeres han muerto de forma violenta en Panamá este año | requiere evidencia · provisional (D-101) | sin borrador en la caché de generación (no se llamó a ningún proveedor) | 25/25 | 0 |
| CU-05 | CASO-001 | GRP-da35c3dead | 36 | 80.13 | suficiente | grupo fijo GRP-da35c3dead (banca) | Mulino viajará a Asia: suscribirá convenios bilaterales con Singapur y Vietnam | aprobado como borrador · provisional (D-101) | versión 3 | 39/39 | 0 |

## Comprobaciones (proporciones con n e IC 95 % de Wilson)

| Comprobación | ok / n | Proporción | IC 95 % |
|---|---|---|---|
| `afirmacion_con_cita` | 32 / 32 | 100% | [89%, 100%] |
| `cita_con_id_en_datos` | 44 / 44 | 100% | [92%, 100%] |
| `cita_con_campo_y_valor` | 44 / 44 | 100% | [92%, 100%] |
| `cifra_de_conteo_coincide` | 15 / 15 | 100% | [80%, 100%] |
| `declaracion_literal` | 19 / 19 | 100% | [83%, 100%] |
| `url_presente` | 48 / 48 | 100% | [93%, 100%] |
| `procedencias_y_estado` | 5 / 5 | 100% | [57%, 100%] |
| `leyenda_de_alcance` | 5 / 5 | 100% | [57%, 100%] |
| `marca_borrador` | 5 / 5 | 100% | [57%, 100%] |
| `cinco_partes` | 5 / 5 | 100% | [57%, 100%] |
| `sin_descripcion_rss` | 19 / 19 | 100% | [83%, 100%] |
| `sin_nombres_de_autor` | 5 / 5 | 100% | [57%, 100%] |
| `contrato_fichas_jsonl` | 5 / 5 | 100% | [57%, 100%] |
| `revision_provisional_visible` | 5 / 5 | 100% | [57%, 100%] |

Resultado: **todas las comprobaciones pasan** · detalle por cita en `outputs/fichas_trazables/trazabilidad.json`.
