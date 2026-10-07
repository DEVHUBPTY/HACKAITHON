# Salidas por modalidad

Definición exacta de lo que produce la etapa 6. Los límites numéricos viven en `config/salidas.yaml`; las listas de frases prohibidas, en `config/restricciones.yaml`.

**Comunes a toda salida:** marca **BORRADOR · requiere revisión** · ID del caso y versión · leyenda de alcance (D-51), que no cuenta para los límites de palabras · cada oración con sus afirmaciones citadas (salvo transiciones permitidas, D-41).

**Origen de cada campo:** `LLM` = lo redacta el modelo con afirmaciones validadas · `Ficha` = se copia de la ficha sin LLM (D-43) · `Regla` = lo calcula el código.

---

## 1 · Paquete editorial (TVN)

| Campo | Lector | Límite | Origen | Reglas |
|---|---|---|---|---|
| **Título propuesto** | Editora | ≤ 14 palabras | LLM | Fiel a una afirmación; si viene de una declaración, con atribución o verbo de reporte |
| **Titulares propuestos** (D-10) | Productor digital | 2–3, ≤ 14 palabras c/u | LLM | Mismas reglas que el título; sin palabras sensacionalistas |
| **Enfoque de interés público** | Editora | 1–2 oraciones | LLM | Por qué importa a la población; tipo inferencia o hipótesis, nunca presentado como hecho |
| **Brief** | Editora | ≤ 250 palabras | LLM | Distingue hecho, declaración, inferencia e hipótesis; incluye año en todo dato oficial |
| **3 preguntas de investigación** | Periodista | Exactamente 3 | LLM sobre vacíos | Cada una referencia el vacío de la ficha que la origina |
| **Fuentes y verificaciones pendientes** | Periodista | — | Ficha | Vacíos y fuentes sugeridas tal cual la ficha (D-37, D-43) |
| **Guion** | Producción | 45–60 s ≈ 110–150 palabras (calibrable) | LLM | Entrada · desarrollo · cierre; atribución hablada ("según reportan…"); solo marcadores `[VISUAL: a definir por producción]` |
| **Resumen web** (D-10) | Productor digital | ≤ 120 palabras | LLM | Mismas reglas que el brief |
| **Copy digital** | Productor digital | ≤ 80 palabras (hashtags cuentan) | LLM | Sin emojis ni palabras sensacionalistas; máximo 2 hashtags |

### Prohibiciones del PDF y cómo se controlan

| El PDF prohíbe inventar… | Control en el validador |
|---|---|
| **Entrevistas** | Frases de entrevista ("en entrevista con", "declaró a este medio", "consultado por", "en conversación con"…) se rechazan salvo que estén literalmente en un titular citado |
| **Citas** | Texto entre comillas debe ser literal del titular citado (D-45) |
| **Imágenes disponibles** | Solo marcadores `[VISUAL: …]`; se rechazan "en estas imágenes", "como vemos", "las imágenes muestran"… (D-25) |
| **Afirmaciones no respaldadas** | Toda afirmación con cita válida; reglas por tipo (D-41); lectura simulada prohibida (D-51) |

### Paquete de investigación (D-42)
Cuando la acción es *Investigar ya* o *Vigilar*: **título de trabajo**, **enfoque**, **3 preguntas**, **fuentes y verificaciones**. Sin brief largo, guion, copy, titulares ni resumen web.

---

## 2 · Boletín de entorno (banca)

| Campo | Límite | Origen | Reglas |
|---|---|---|---|
| **Resumen** | ≤ 250 palabras | LLM | Dividido en dos bloques rotulados: **Observaciones** y **Hipótesis de impacto** |
| ↳ Observaciones | — | LLM | Solo afirmaciones de tipo hecho o declaración, citadas |
| ↳ Hipótesis de impacto | — | LLM | Solo inferencia o hipótesis; redacción condicional; sin cifras nuevas |
| **Sectores potencialmente relacionados** | — | Regla | Sector del tema principal y del secundario (mapeo tema → sector), cada uno con el motivo |
| **Horizonte temporal** | — | Regla | *Inmediato* (evidencia de días) · *corto plazo* (semanas) · *estructural* (solo datos anuales); según las fechas de la evidencia (D-11) |
| **Evidencia** | — | Ficha | Lo respaldado de la ficha, con citas y limitaciones |
| **3 preguntas para el analista** | Exactamente 3 | LLM sobre vacíos | Cada una referencia su vacío |
| **Aviso fijo** | — | Regla | "No constituye recomendación financiera ni opinión oficial de la SBP." |

### Prohibiciones del PDF y cómo se controlan

| El PDF prohíbe… | Control en el validador |
|---|---|
| **Recomendar compra o venta** | Léxico de recomendación ("comprar", "vender", "invertir", "recomendamos", "conviene"…) rechazado en cualquier tipo |
| **Inferir pérdidas, impagos o exposición de cartera** | Léxico ("pérdidas", "impago", "morosidad", "exposición", "cartera", "default", "riesgo de crédito", "score"…) **rechazado en inferencias e hipótesis**. Permitido solo en una **declaración** que lo cite literalmente de un titular (ej. "según La Prensa, las inundaciones causaron pérdidas") |
| **Alerta definitiva** | Lenguaje de certeza en hipótesis ("ocurrirá", "sin duda", "inevitable") rechazado |

### Etiquetas
Internamente se usan los 4 tipos (D-41). En el boletín se muestran: hecho y declaración → **observación**; inferencia e hipótesis → **hipótesis de impacto**.

---

## Metadatos de la generación (no son campos de contenido)

Todo paquete (`PaqueteEditorial`, `PaqueteInvestigacion`, `BoletinBanca`) lleva además estos campos de metadatos. No son parte del texto que lee la persona ni cuentan para los límites de palabras; sirven para trazabilidad y revisión:

| Campo | Qué es | Origen |
|---|---|---|
| `marca` | «BORRADOR · requiere revisión» (`config/restricciones.yaml`) | Regla |
| `id_caso`, `version` | ID del caso (hoy el `GRP-` hasta que E1-16 asigne `CASO-`) y versión | Ficha |
| `leyenda_alcance` | Leyenda de alcance (D-51), según `uso_descripcion` de la ficha | Regla |
| `accion` | Acción recomendada de la ficha que decidió qué se generó (D-42) | Ficha |
| `forzado` | `true` si la persona forzó el paquete completo (queda registrado) | Regla |
| `vacios` | Vacíos de la ficha (si la acción es «Completar evidencia y producir»), secciones que no se pudieron redactar con su motivo y secciones recortadas por exceso de palabras (D-96) | Regla |
| `afirmaciones` | Las afirmaciones validadas del paso 1, con sus citas (ID + campo, `traducido` si el titular no está en español) | LLM validado |

## Cómo se mide

| Medición | Cómo |
|---|---|
| Límites de palabras y cantidades | Validador (tests por campo) |
| Duración real del guion | Cronometrar la lectura en voz alta de 5 guiones; ajustar el rango en `config/salidas.yaml` |
| Prohibiciones | Un test por frase prohibida, incluido el caso permitido en declaración literal |
| Utilidad | Revisión humana de la editora o el analista (tasa de aceptación y corrección, E1-16) |
