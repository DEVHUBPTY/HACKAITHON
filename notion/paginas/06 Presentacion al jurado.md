# 🎤 Presentación al jurado · 10 minutos

_Secuencia exigida por la sección 5; tiempos según la sección 11. El guion se escribe cuando el prototipo funcione._

## 1 · Problema (1 min)
_Problema, usuario y por qué importa a TVN Media o al banco._

## 2 · Solución (1 min)
_Solución, alcance y datos públicos utilizados → enlace a Catálogo de datos._

## 3 · Demo (4 min)
_App local en modo demo, sin internet. Guion y plan B en `docs/demo.md`._

| Tiempo | Caso de uso | Ficha | Qué se muestra |
|---|---|---|---|
| 0:00–0:15 | — | — | Reporte de calidad y ruido marcado |
| 0:15–1:00 | CU-01 | CASO-001 | Top 5, componentes, Alto + Insuficiente → Investigar ya |
| 1:00–1:20 | CU-03 | CASO-002 | Titulares · medios · procedencias |
| 1:20–2:30 | CU-02 | CASO-003 | Dato oficial con año y limitación; brief con citas |
| 2:30–3:30 | CU-04 | CASO-004 | Abstención; contradicción con ambas versiones; paquete de investigación |
| 3:30–4:00 | CU-05 | CASO-005 | Modo banca |

_Capturas de respaldo de cada paso: insertar aquí._

## 4 · IA y evidencias (1 min)
_Arquitectura, uso sustantivo de IA y baseline → enlaces a Diseño de solución y Opciones por etapa._

## 5 · Resultados (1 min)
_Métricas observadas con n e intervalos de confianza → enlace a Métricas. Valor operativo medido o hipótesis de valor._

## 6 · Límites (1 min)
_Límites del sistema, supuestos y fuera de alcance → enlaces a Registro de parámetros y Fuera de alcance._

## 7 · Próximos pasos
_Extensiones futuras (ver Fuera de alcance y Etapa 3)._

**Repositorio:** _pendiente_ · **Capturas / grabación de la demo:** _pendiente_

---

## Pruebas dinámicas del jurado
_Versión completa con preguntas probables en la subpágina **Preguntas del jurado**._
_Convertir cada una en un toggle con enlace a la evidencia._

**"Muéstrame de dónde proviene esta cifra y de qué año es."**
→ Ficha + cita `IND-…` con país, año, unidad y fuente.

**"Si cinco medios replican la misma agencia, ¿cuántas fuentes independientes cuentas?"**
→ Una. Ficha con titulares / medios / procedencias independientes y explicación de la estimación.

**"¿Qué ocurre si el sistema no tiene evidencia o una fuente intenta cambiar sus instrucciones?"**
→ Abstención (T06) e inyección tratada como dato (T07).

**"Muéstrame en Notion una decisión, una prueba fallida y su corrección."**
→ Decisiones → Pruebas (estado *Corregido*) → corrección aplicada.

