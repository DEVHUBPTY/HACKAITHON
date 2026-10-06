# Cómo importar este paquete en Notion

> Impórtalo en el workspace de la organización si existe; si no, en uno propio del equipo, compartido solo con el jurado (D-74).

## Estructura final (D-59)

Arriba quedan **solo las 8 secciones** que exige el PDF, en este orden:

| # | Sección | Contiene |
|---|---|---|
| 1 | 🏠 Inicio del reto | Subpáginas **Checklist de admisión** y **Autoevaluación con la rúbrica** |
| 2 | 📋 Plan y decisiones | Bases **Backlog**, **Decisiones** y **Bitácora** · subpágina **Cronograma del evento** |
| 3 | 🗂️ Catálogo de datos | Base **Catálogo de datos** · subpágina **Fuentes y referencias** |
| 4 | 🏗️ Diseño de solución | Base **Prompts** · subpáginas **Guía de temas**, **Salidas por modalidad**, **Registro de parámetros**, **Opciones por etapa**, **Modelos y costos** |
| 5 | 🧾 Casos y evidencias | Base **Casos y evidencias** |
| 6 | 🧪 Pruebas y métricas | Base **Pruebas** · subpáginas **Métricas** y **Protocolo de evaluación** |
| 7 | ⚠️ Riesgos y ética | Base **Riesgos** · subpágina **Fuera de alcance** |
| 8 | 🎤 Presentación al jurado | Página del pitch · subpágina **Preguntas del jurado** |

## 1. Crear la página raíz
**🏆 HackIAthon · De la señal a la decisión**.

## 2. Importar las páginas (carpeta `paginas/`)
**⋯ → Importar → Texto y Markdown**. Importa primero las páginas principales y después, **dentro de cada una**, las de su carpeta homónima (por ejemplo, dentro de *Diseño de solución* las 4 de `03 Diseno de solucion/`).
Renómbralas con su emoji y quita el número. Los bloques Mermaid: cambia el lenguaje del bloque a **Mermaid**.

## 3. Importar las bases (carpeta `bases/`)
**⋯ → Importar → CSV**, dentro de la sección que indica la tabla de arriba. *Catálogo de datos* y *Casos y evidencias* pueden ser la sección misma (base de página completa).

## 4. Ajustes después de importar
Notion importa todo como texto. Cambia estos tipos (los valores se conservan):

**Todas las bases con columna Fase** (Backlog, Decisiones, Bitácora) → *Fase* como *Selección* (Preparación · Evento).

**Backlog**
- Estado → *Estado* (Por hacer · En curso · Bloqueado · Hecho)
- Etapa, Tramo, Rol, Prioridad, Modalidad → *Selección*
- Fechas → *Fecha* (con fecha de fin) · Responsable → *Persona*
- Vistas: **Tablero** por Estado, **Cronología** por Fechas, **Evento** filtrada por *Fase = Evento*

**Decisiones**
- Estado → *Selección* (Propuesta · Aceptada · Reemplazada) · Tipo → *Selección* (Técnica · Producto) · Fecha → *Fecha* · Autor → *Persona*
- Vista **Evento** filtrada por *Fase = Evento*

**Casos y evidencias**
- R, I, U, N, E → *Número* · Modalidad, Tema, Estado de evidencia, Caso de uso → *Selección*
- Estado de revisión → *Estado* (Nuevo · En revisión · Requiere evidencia · Aprobado como borrador · Descartado)
- Revisor → *Persona* · Fecha de revisión y Última exportación → *Fecha*
- Propiedad **P** (Fórmula): `round((30 * prop("R") + 25 * prop("I") + 20 * prop("U") + 15 * prop("N") + 10 * prop("E")) * 10) / 10`
- Propiedad **Rango** (Fórmula): `if(prop("P") >= 70, "Alto", if(prop("P") >= 40, "Medio", "Bajo"))`
- Plantilla de ficha con: leyenda de alcance arriba · Qué se reporta · Quién lo reporta · Qué está respaldado · Qué falta comprobar · Acción recomendada · Borrador · Historial de revisión
- Borra la fila **CASO-000** de ejemplo cuando cargues la primera ficha real

**Pruebas** → Estado como *Selección* (Pendiente · Pasa · Falla · Corregido) · Evidencia de ejecución → *Archivos* o *URL*

**Riesgos** → Categoría, Probabilidad, Impacto, Estado → *Selección*

**Bitácora** → Fecha → *Fecha* con hora · Autor → *Persona* · Tipo → *Selección*

## 5. Relaciones (recomendado)
Backlog ↔ Decisiones · Pruebas ↔ Decisiones · Riesgos ↔ Pruebas. Las columnas de texto con IDs sirven para enlazarlas rápido.

## 6. Accesos
Sigue la sección *Accesos y políticas* del **Checklist de admisión**.
