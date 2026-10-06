# 📋 Plan y decisiones

Esta sección contiene dos bases de datos:

- **Backlog**: todas las tareas, con responsable, estado, etapa, tramo y dependencias.
- **Decisiones**: cada decisión técnica o de producto con contexto, opciones y justificación.

## Vistas recomendadas

- **Backlog → Tablero** agrupado por *Estado*.
- **Backlog → Cronología** usando la propiedad *Fechas* (el reto exige cronología).
- **Backlog → Por responsable** agrupado por *Responsable*.
- **Decisiones → Tabla** ordenada por *ID*, y vista agrupada por *Tipo* (técnica · producto).

## Reglas del equipo

1. Una decisión se registra **cuando se toma**, no al final.
2. Una prueba fallida se registra **antes** de arreglarla, para que quede la corrección.
3. Cada cambio de etapa se registra como decisión, con el criterio que se cumplió.
4. Nunca pegar claves, tokens ni capturas con secretos.
5. Cada tarea técnica tiene su spec en el repo (`specs/<ID>.md`), indicada en la columna *Spec* del Backlog.

## Dos tipos de revisión (no confundir)

| | Revisión de código | Revisión editorial |
|---|---|---|
| Qué se revisa | Cambios en el repositorio | Fichas y borradores que produce el sistema |
| Quién | Claude Code (primera pasada) + una persona distinta al autor | La persona editorial o analista responsable |
| Dónde queda | Base *Pruebas* (falla → corregido) | Base *Casos y evidencias* (estado de revisión) |
| Guía | `docs/REVISION.md` | Etapa 7 del reto |

## Flujo de desarrollo

Planificar → Diseñar → Construir → Probar → Revisar → Documentar → Empaquetar y ensayar.
El detalle de qué hace Claude Code y qué hace el equipo en cada fase está en `docs/FLUJO_CLAUDE_CODE.md` del repositorio.

## Registro durante el evento (D-58)

Todas las bases tienen la propiedad **Fase**: *Preparación* (antes del evento) o *Evento*.

- Cada decisión se registra **al tomarla**, con fase *Evento*.
- Cada prueba fallida se registra **antes** de corregirla.
- La **Bitácora** se actualiza **al menos cada 2 horas** (avance, problema, decisión o prueba).
- Vista recomendada: Decisiones y Bitácora filtradas por *Fase = Evento*, para mostrarle al jurado el trabajo del evento.

## Mínimos exigidos

- [ ] Al menos 8 tareas (hay 47).
- [ ] Al menos 3 decisiones justificadas (hay 74; 66 aceptadas, 8 propuestas; cada una marcada como técnica o de producto).
- [ ] Registro durante la ejecución (ver Bitácora).

- **Cronograma del evento:** subpágina con los tramos en horas, el reparto por rol y el punto de corte.
