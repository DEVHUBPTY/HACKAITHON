# Flujo de desarrollo con Claude Code

Cada fase tiene una parte que hace el agente y otra que hacen ustedes. El despliegue no aplica: el reto pide un **prototipo ejecutable y reproducible en local**, así que esa fase se reemplaza por **Empaquetar y ensayar**.

| Fase | Claude Code | El equipo | Evidencia en Notion |
|---|---|---|---|
| **Planificar** | Convierte una tarea del backlog en spec de 4 partes si aún no existe; señala dependencias | Prioriza, estima, asigna y aprueba la spec | Backlog · Decisiones |
| **Diseñar** | Genera el esqueleto: módulos vacíos, esquemas pandera/pydantic, YAML de configuración | Fija arquitectura, reglas v1.3 y umbrales | Diseño de solución |
| **Construir** | Implementa una spec a la vez, después de que el plan esté aprobado | Guía el comportamiento y decide los *tradeoffs* | Bitácora |
| **Probar** | Propone tests desde la spec y desde T01–T10 | Verifica casos borde, intención y revisa y aprueba las etiquetas de evaluación que propone el asistente (D-85) | Pruebas · Métricas |
| **Revisar** | Primera pasada contra `docs/REVISION.md`; después, un agente revisor independiente (que no escribió el código) deja su veredicto escrito en el PR y en Notion, y con veredicto favorable el asistente integra el PR (D-78) | Sigue el trabajo por el chat y responde las consultas; revisa y aprueba lo que el reto exige a personas (etiquetas, D-85) | Backlog · Bitácora · Pruebas (falla → corregido) |
| **Documentar** | README, diccionario de datos, resúmenes de cambios | Narrativa del pitch y registro de decisiones | Todas |
| **Empaquetar y ensayar** | Verifica instalación limpia y comandos del README | Ensayo con Wi-Fi apagado | Pruebas (T10) |

## Prompts por fase

**Planificar**
> Lee `specs/E1-08.md` y `CLAUDE.md`. Propón un plan: archivos que vas a crear o modificar, enfoque, riesgos y qué tests escribirás. No escribas código todavía.

**Diseñar**
> Crea el esqueleto de los módulos que menciona la spec, solo con firmas, type hints y docstrings. Sin lógica.

**Construir**
> Plan aprobado. Implementa `specs/E1-08.md`. Al final ejecuta los comandos de "Listo cuando" y muéstrame la salida.

**Probar**
> Escribe primero los tests de "Listo cuando" de `specs/E1-10.md` y verifica que fallen. Después implementa hasta que pasen. No debilites ningún assert.

**Revisar**
> Revisa el diff actual contra `docs/REVISION.md` y `CLAUDE.md`. Lista hallazgos por severidad.

**Documentar**
> Actualiza el README con instalación, comando de ejecución y cómo correr las pruebas. Genera un resumen de los cambios de hoy para la Bitácora de Notion.

## Reglas de trabajo

1. **Una spec por sesión.** Al cambiar de tarea, empezar una conversación nueva para que el contexto no se mezcle.
2. **Plan antes que código**, siempre.
3. **Si la spec y `CLAUDE.md` chocan, manda `CLAUDE.md`** y se corrige la spec.
4. **Una tarea, un worktree, una rama, un PR.** Se integra por PR a `main` con la plantilla de `.github/` y la revisión del paso *Revisar* (D-78). El equipo (David Fen, Javier Acosta, Juan Zhou) hace de todo; el responsable de cada tarea está en el Backlog de Notion.
5. **Cronograma:** tramos, punto de corte y reparto por área en `docs/cronograma.md`.
