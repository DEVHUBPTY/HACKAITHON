# 🎯 Autoevaluación con la rúbrica (sección 10)

Puntaje = Σ (peso × nota / 5). Escala: 0 ausente · 1 parcial · 2 básico · 3 funcional · 4 sólido · **5 excepcional y verificado**.
Se completa **antes del cierre**, con la evidencia real, para encontrar los puntos débiles a tiempo.

| Dimensión | Peso | Para un 5 pide | Nuestra evidencia | Riesgo de quedar bajo | Nota (0–5) | Puntos |
|---|---|---|---|---|---|---|
| **Utilidad para TVN o banca** | 20 | Usuario claro, flujo realista, salidas accionables, impacto demostrado **sin exagerar** | Usuarios y escenarios (Inicio) · ficha con acción · paquete y boletín · Precision@5 · prueba de tiempo | Sin editor real, la utilidad queda como exploratoria | | |
| **Prototipo y flujo completo** | 20 | Carga, consulta, priorización, ficha, borrador y revisión funcionan **con datos comunes** | E1-02 a E1-16 · demo de 4 min · T01–T10 | Depende del snapshot de la organización (R-13, R-27) | | |
| **Uso efectivo de IA** | 15 | NLP/ML sustantivo, baseline y **mejora o limitación medida** | Embeddings en 3 tareas · 4 baselines · `ia_vs_baseline.md` con intervalos | Pocas etiquetas → intervalos anchos | | |
| **Evidencias y explicabilidad** | 15 | Citas pertinentes, puntaje reproducible, contradicciones y abstención correctas | Validador · reglas v1.3 recalculables en Notion · T05, T06 · sustento ≥ 90 % · X06 | Validez de sustento por debajo de la meta | | |
| **Notion: ejecución y pitch** | 15 | Trabajo trazable **durante el evento**, catálogo y pruebas completos, pitch navegable | 8 secciones · fase *Evento* · Checklist de admisión · Presentación con 7 pasos | Poco registro durante el evento | | |
| **Calidad técnica y evaluación** | 10 | Código reproducible, **arquitectura proporcional**, pruebas y métricas verificables | Poetry + lockfile · `scripts.reproducir` · pytest · protocolo de evaluación | **Sobrediseño**: el plan es ambicioso para 24–48 h | | |
| **Seguridad, privacidad y ética** | 5 | Controles operativos, derechos documentados, resistencia a abuso del agente | Validador (D-41, D-51, D-53, D-68) · T07 · marca de inyección · redacción de logs · fuentes y condiciones | — | | |
| **Total** | **100** | | | | | |

## Condiciones previas (separadas del puntaje)

| Condición | Cómo se verifica | Estado |
|---|---|---|
| Acceso a Notion, documentación y pitch | Checklist de admisión | ⬜ |
| Demo ejecutable | C-04 (ensayo sin internet) · C-07 (instalación limpia) | ⬜ |
| Fuentes declaradas | Catálogo de datos · Fuentes y referencias · `scripts.auditoria_final` | ⬜ |
| Ausencia de secretos | `scripts.auditoria_final` · C-05 | ⬜ |
| Sin citas falsas ni acciones prohibidas | `scripts.auditoria_final` | ⬜ |

## Sobre la "arquitectura proporcional"

La rúbrica premia una arquitectura **proporcional** al problema. El plan tiene muchas piezas; la forma de mantenerlo proporcional es:
- **Respetar las etapas:** la Etapa 1 sola ya cubre todo el flujo; lo demás es opcional.
- **Stack simple:** Python, DuckDB, Streamlit y modelos locales; sin servidores, colas ni servicios externos.
- **Explicarlo en el pitch:** cada pieza existe por un requisito concreto del PDF.
