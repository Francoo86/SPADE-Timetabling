# SPADE Timetabling

Sistema multi-agente para la asignación automática de horarios académicos, implementado con [SPADE](https://spade-mas.readthedocs.io/). Es la migración a Python del proyecto original en JADE: [Implementaciones-MAS](https://github.com/Francoo86/Implementaciones-MAS).

Los agentes negocian entre sí usando el protocolo FIPA-ACL para asignar bloques horarios a profesores en salas disponibles, respetando restricciones de capacidad, campus y turno.

---

## Tabla de contenidos

1. [Requisitos](#requisitos)
2. [Configuración del servidor XMPP (Prosody en WSL)](#configuración-del-servidor-xmpp-prosody-en-wsl)
3. [Instalación del proyecto](#instalación-del-proyecto)
4. [Configuración del entorno](#configuración-del-entorno)
5. [Estructura de datos](#estructura-de-datos)
6. [Uso](#uso)
7. [Salida](#salida)

---

## Requisitos

- **Windows 11** con **WSL 2** habilitado (Ubuntu 22.04 recomendado)
- **Python 3.11+** (en Windows)
- **Prosody** instalado en WSL como servidor XMPP

---

## Configuración del servidor XMPP (Prosody en WSL)

Prosody actúa como el broker de mensajes XMPP que usan los agentes SPADE para comunicarse.

### 1. Instalar Prosody en WSL

```bash
sudo apt update
sudo apt install prosody -y
```

### 2. Aplicar la configuración del proyecto

El repositorio incluye el archivo `wsl-prosody.cfg.lua` con la configuración necesaria. Cópialo reemplazando el archivo por defecto:

```bash
sudo cp /mnt/c/Users/<tu-usuario>/OneDrive/Documentos/GitHub/Work/Francoo86/SPADE-Timetabling/wsl-prosody.cfg.lua /etc/prosody/prosody.cfg.lua
```

Los puntos clave que ya vienen configurados en ese archivo:

| Parámetro | Valor | Descripción |
|---|---|---|
| `allow_registration` | `true` | Los agentes se auto-registran al iniciar |
| `allow_unencrypted_plain_auth` | `true` | Autenticación sin TLS (desarrollo local) |
| `c2s_require_encryption` | `false` | No requiere cifrado cliente-servidor |
| `authentication` | `internal_plain` | Backend de autenticación simple |
| `VirtualHost "localhost"` | `anonymous` | Host local sin contraseña real |

### 3. Iniciar Prosody

```bash
sudo prosodyctl start
```

Para verificar que está corriendo:

```bash
sudo prosodyctl status
```

### 4. Iniciar Prosody automáticamente con WSL (opcional)

Agrega esto a tu `~/.bashrc` o `~/.profile` en WSL:

```bash
sudo prosodyctl start 2>/dev/null
```

O crea una tarea de inicio en Windows que ejecute `wsl sudo prosodyctl start`.

---

## Instalación del proyecto

### 1. Clonar el repositorio

```bash
git clone https://github.com/Francoo86/SPADE-Timetabling.git
cd SPADE-Timetabling
```

### 2. Crear el entorno virtual

```bash
python -m venv .venv
```

Activarlo:

- **PowerShell / CMD:**
  ```powershell
  .venv\Scripts\activate
  ```
- **Git Bash / WSL:**
  ```bash
  source .venv/bin/activate
  ```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

---

## Configuración del entorno

Crea un archivo `.env` en la raíz del proyecto con las siguientes variables:

```env
XMPP_SERVER=localhost
AGENT_PASSWORD=test
```

> `.env` está en `.gitignore` y nunca se sube al repositorio.

---

## Estructura de datos

Los archivos de entrada se encuentran en `data/`. El sistema usa dos formatos:

### Ejecución simple (`main.py`)

Lee directamente desde:

```
data/
├── profesores.json   ← lista de profesores con sus asignaturas
└── salas.json        ← lista de salas con capacidad y campus
```

### Ejecución por escenarios (`benchmarked_main.py` / `iterative_main.py`)

Lee desde subcarpetas de escenario:

```
data/
└── scenarios/
    ├── small/
    │   ├── profesores.json
    │   └── salas.json
    ├── medium/
    │   ├── profesores.json
    │   └── salas.json
    └── full/
        ├── profesores.json
        └── salas.json
```

Los escenarios ya están disponibles en `data/scenarios/`. Para regenerarlos o crear nuevos a partir de los datos crudos en `data/`, usa:

```bash
python data/scenario_creator.py
```

---

## Uso

Asegúrate de que **Prosody esté corriendo en WSL** antes de ejecutar cualquier script.

### Ejecución simple

Corre una negociación con los datos por defecto (`data/profesores.json` y `data/salas.json`):

```bash
python main.py
```

### Ejecución con escenario (benchmarked)

Corre una negociación con un escenario específico. Los escenarios disponibles son `small`, `medium` y `full`:

```bash
python benchmarked_main.py
```

> El escenario por defecto es `medium`. Para cambiarlo, modifica la última línea de `benchmarked_main.py`:
> ```python
> runner = ApplicationRunner(xmpp_server, password, "small")
> ```

### Ejecución iterativa con profiling

Ejecuta múltiples iteraciones y genera estadísticas de rendimiento:

```bash
python iterative_main.py --iterations 5 --scenario small
```

| Argumento | Descripción | Por defecto |
|---|---|---|
| `--iterations` | Número de ejecuciones | `1` |
| `--scenario` | Escenario a usar (`small`, `medium`, `full`) | `small` |

---

## Salida

Tras una ejecución exitosa se generan los siguientes archivos:

| Ruta | Descripción |
|---|---|
| `agent_output/` | Horarios asignados en JSON (profesores y salas) |
| `agent_logs.log` | Log completo de la ejecución |
| `profiling_results/<scenario>/` | Archivos `.prof` y `.txt` de profiling por iteración |
| `iteration_summary/<scenario>/summary.json` | Resumen estadístico de las iteraciones |

Para visualizar los horarios generados como Excel:

```bash
python scheduleRepresentation/exportTeacherSchedule.py
python scheduleRepresentation/exportClassroomSchedule.py
```
