# Guía de temas y reglas de frontera

Esta guía la usan **el sistema** (para escribir `config/temas.yaml`) y **las personas** que etiquetan (E1-06).
Si cambia, cambian las dos cosas a la vez.

La salida del clasificador son **solo los 6 temas del reto** (sección 3, etapa 2). Lo que aparece en "Incluye" sirve para describir cada tema; no son categorías nuevas.

## Los 6 temas

| Tema | Incluye | No incluye → va a |
|---|---|---|
| **Economía** | Crecimiento y PIB · inflación y precios (canasta básica, combustibles) · empleo · finanzas públicas (deuda, presupuesto, recaudación) · inversión · comercio exterior · banca y calificaciones de riesgo | Ingresos o peajes del Canal → Logística/Canal · una ley o impuesto nuevo → Regulación |
| **Logística/Canal** | Operación del Canal (tránsitos, calado, reservas, niveles del lago Gatún) · puertos · Zona Libre de Colón · **carga aérea** · transporte de carga · cadenas de suministro | Vuelos de pasajeros → Turismo · reglas nuevas de la ACP → Regulación |
| **Turismo** | Llegada de visitantes · cruceros · hotelería y ocupación · **aviación de pasajeros** y conectividad · destinos y promoción | Carga aérea → Logística/Canal |
| **Servicios públicos** | Agua potable · electricidad · telecomunicaciones e internet · transporte público · recolección de basura · **salud pública** (hospitales, CSS, MINSA, medicamentos) · **educación pública** (escuelas, clases, docentes) · **seguridad ciudadana** (policía, operativos, cárceles, delitos) · **obras públicas** (carreteras, puentes, acueductos, licitaciones y contratos de obra, sobrecostos de obra; D-111) | Una ley o reforma nueva sobre el servicio → Regulación (secundario Servicios públicos) |
| **Eventos naturales** | Sismos · inundaciones y lluvias · deslizamientos · sequía y El Niño · incendios forestales · alertas de protección civil | Interrupción de un servicio causada por el fenómeno → Servicios públicos |
| **Regulación** | Leyes y decretos · resoluciones de entes reguladores · reformas · listas internacionales (listas grises, GAFI) · **contratos y concesiones públicas** · sanciones | — |

## Fuera de los temas

| Motivo | Cuándo | Ejemplos |
|---|---|---|
| `no_es_panama` | La noticia no trata sobre Panamá ni lo afecta | Panama City (Florida), Panama Papers como referencia histórica sin hecho nuevo, sombreros Panamá |
| `fuera_de_temas` | Es sobre Panamá, pero de un área que el reto no cubre | Deportes, farándula, cultura, política electoral y partidista sin norma de por medio |
| `no_es_noticia` | El titular no es una nota con contenido (D-87; las personas también pueden asignarlo al etiquetar) | Solo el nombre del medio, una portada o sección, un titular promocional, una página que no es una nota |

Los tres quedan fuera de la bandeja, se conservan y se cuentan por separado en el reporte de calidad.
Una noticia de otro país **que afecta a Panamá** no es `no_es_panama` (migración por el Darién, decisiones sobre el Canal).

**Alcance regional (D-84).** Una nota que menciona la región (Centroamérica, América Latina, Caribe) o un fenómeno regional que afecta a Panamá (El Niño y La Niña, rutas marítimas) **no es ruido**, aunque no nombre a Panamá. Se etiqueta con su tema como cualquier otra y se marca **alcance regional**; se cuenta aparte. Si no afecta a Panamá de ninguna manera, sigue siendo `no_es_panama`. El sistema lo aplica así (D-120): una nota regional de un medio no panameño que no nombra a Panamá ni trae uno de esos fenómenos (El Niño y La Niña, rutas marítimas y su comercio, migración por el Darién) se marca `no_es_panama`; las de medios panameños no.

## Reglas de frontera

Se aplica la **primera** regla que corresponda:

1. **Hecho central, no consecuencias.** Se clasifica por lo que pasó según el titular, no por lo que podría causar.
2. **Norma nueva → Regulación.** Ley, decreto, resolución, reforma, contrato, concesión o sanción de una autoridad. El área afectada va como tema secundario.
3. **El sujeto es el Canal → Logística/Canal**, aunque hable de dinero o de agua.
4. **Interrupción o falla de un servicio → Servicios públicos**, aunque la causa sea natural.
5. **Fenómeno físico en sí → Eventos naturales.**
6. **Pasajeros → Turismo; carga → Logística/Canal.**
7. **Cifras macroeconómicas generales → Economía.**

## Obras públicas: frontera (D-111)

Las obras públicas son parte de Servicios públicos, no un tema nuevo: la salida sigue siendo de 6 temas y el reto no define subtemas (D-125
retiró el subtema `obras_publicas` que D-111 había creado). Se aplica después de las reglas de arriba, y cada una puede cambiar el tema:

- **El acto de contratar es Regulación** (regla 2; D-111): una licitación, un contrato o una adjudicación de obra va a Regulación con
  Servicios públicos como secundario. **La obra en sí** (construcción, avance, retraso, inauguración, estado de una carretera o
  de un puente, sobrecosto reportado o auditado) es Servicios públicos (obras públicas).
- **Acueducto:** construir, ampliar o rehabilitar el acueducto (o uno nuevo) es una obra pública (D-111); el servicio (corte, suministro, Idaan) es agua potable. Ambos son Servicios públicos.
- **Fenómeno y obra:** si el hecho central es el derrumbe o la crecida que daña una carretera o un puente, es Eventos naturales
  (regla 5); si es la interrupción del servicio o la obra de reparación, es Servicios públicos.
- **Puertos, esclusas y carga** siguen en Logística/Canal aunque sean obras (regla 3 y 6).
- **Justicia y elecciones no son parte de los 6 temas.** Una investigación o un proceso judicial por corrupción en una obra, o la política
  electoral, es `fuera_de_temas`, salvo que el hecho central toque uno de los 6 temas (el sobrecosto de la obra sí es una obra pública;
  el proceso judicial que lo investiga no; D-111). Hasta D-125 un titular con marcadores judiciales (imputa, juez, fiscalía,
  peculado, corrupción…) no recibía el subtema `obras_publicas`; sin subtemas esa exclusión desapareció, y el titular tampoco se vuelve
  ruido por eso: ver la limitación de `docs/parametros.md`.

## Casos difíciles (también son tests de E1-07)

Titulares ilustrativos, escritos para fijar el criterio; no vienen del corpus.

| Titular | Principal | Secundario | Regla |
|---|---|---|---|
| Sequía obliga al Canal a reducir tránsitos diarios | Logística/Canal | Eventos naturales | 3 |
| Lluvias dejan sin agua a sectores de San Miguelito | Servicios públicos | Eventos naturales | 4 |
| Fuerte sismo sacude la provincia de Chiriquí | Eventos naturales | — | 5 |
| ASEP aprueba aumento de la tarifa eléctrica | Regulación | Servicios públicos | 2 |
| Ingresos del Canal crecen en el año fiscal | Logística/Canal | Economía | 3 |
| Panamá sale de la lista gris del GAFI | Regulación | Economía | 2 |
| Aerolínea abre nueva ruta de pasajeros a Europa | Turismo | — | 6 |
| Aumenta la carga aérea en Tocumen | Logística/Canal | — | 6 |
| Inflación cerró el año en X% | Economía | — | 7 |
| Asamblea aprueba reforma a la CSS | Regulación | Servicios públicos | 2 |
| Hospital reporta falta de medicamentos | Servicios públicos | — | 4 |
| Paro docente deja sin clases a escuelas | Servicios públicos | — | 4 |
| Policía reporta aumento de homicidios | Servicios públicos | — | 4 |
| Gobierno firma nuevo contrato minero | Regulación | Economía | 2 |
| Selección de fútbol clasifica al Mundial | `fuera_de_temas` | — | — |

## Seguridad ciudadana: cuidado especial

Las noticias de sucesos suelen nombrar personas y acusaciones. Dentro de Servicios públicos:

- Las acusaciones se atribuyen como **declaraciones**, nunca como hechos.
- **No** se agrupa ni se resume por persona.
- Si el volumen de sucesos empieza a dominar la bandeja, se documenta y se revisa con Precision@5 (riesgo R-18).

## Cómo se clasifica (decisión D-21)

Se implementaron y midieron **las dos opciones** con el mismo código; la salida de ambas son solo los 6 temas. **D-125:** la opción B se retiró (el reto no define subtemas) y solo queda la A (más la logística de D-121).

- **Opción A:** cada tema tiene una descripción (columna "Incluye") y unos 10 titulares de ejemplo **reales**, tomados de la exploración (E0-09).
- ~~**Opción B:** cada elemento de "Incluye" es un subtema con su propio prototipo; el resultado se sube a su tema.~~ Retirada por D-125.
- **Criterio fijado antes de medir (D-57):** se usa B solo si el intervalo de confianza del 95 % de la diferencia de macro-F1 excluye el cero. Si no, se usa A por ser más simple.
- Los titulares usados como ejemplo se excluyen de la evaluación.
