# ❓ Preguntas del jurado (5 minutos)

_Respuesta corta + dónde mostrarlo. Convertir cada pregunta en un toggle._

## Las 4 pruebas dinámicas del PDF

| Pregunta | Respuesta corta | Dónde mostrarlo |
|---|---|---|
| "Muéstrame de dónde proviene esta cifra y de qué año es" | Cada cifra cita ID + campo; el dato oficial muestra país, año, unidad y limitación | CASO-003 → cita `IND-` |
| "Si cinco medios replican la misma agencia, ¿cuántas fuentes independientes cuentas?" | Una. Contamos procedencias, no titulares | CASO-002 → *Quién lo reporta* |
| "¿Qué ocurre si el sistema no tiene evidencia o una fuente intenta cambiar sus instrucciones?" | Se abstiene antes de llamar al LLM y dice qué falta; el texto de las fuentes es dato, no instrucción, y se marca como sospechoso | Consulta de abstención · caso `SYN-` de T07 |
| "Muéstrame en Notion una decisión, una prueba fallida y su corrección" | — | Decisiones (vista *Evento*) → Pruebas (estado *Corregido*) |

## Preguntas probables

| Pregunta | Respuesta corta | Dónde mostrarlo |
|---|---|---|
| "¿Por qué esos pesos en el puntaje?" | Son los del PDF; medimos su estabilidad (X02) y su utilidad (Precision@5) | Diseño de solución · Registro de parámetros |
| "¿El puntaje dice si una noticia es verdadera?" | No. Ordena la atención; el estado de evidencia es independiente y nada se etiqueta como verdadero o falso | Bandeja · tabla de acciones |
| "¿Qué aporta la IA frente a algo simple?" | Un baseline por tarea, con métricas e intervalos, y dónde la IA **no** ayuda | Modelos y costos · `ia_vs_baseline.md` |
| "¿Cuánto cuesta operarlo?" | Modelos locales: USD 0 en API; se reporta tiempo de cómputo. Tope de costo si se usa un proveedor de pago | Modelos y costos |
| "¿Qué pasa si se cae internet?" | Funciona igual: snapshot local, caché y modelo local (T10) | Demo en vivo sin Wi-Fi |
| "¿Cómo evitan inventar datos?" | Validador en código: citas, tipos, comillas literales, fechas, causalidad, lectura simulada | Diseño de solución · Cumplimiento de la sección 8 |
| "¿Y los derechos de TVN?" | Solo metadatos; la descripción solo para uso interno; nada protegido en la entrega | Fuentes y referencias · Fuera de alcance |
| "¿Qué tan bien clasifica?" | Macro-F1 con n, intervalo y acuerdo entre etiquetadores | Métricas |
| "¿Esto escala a producción?" | El MVP es por lote y local; producción requeriría ingesta continua y una base multiusuario | Próximos pasos |
| "¿Qué no hace el sistema?" | Lista explícita de fuera de alcance y supuestos declarados | Fuera de alcance · Registro de parámetros |
| "¿Sirve para un banco?" | Mismo motor, otra configuración; observación separada de hipótesis y sin recomendaciones | Demo en modo banca · Salidas por modalidad |
