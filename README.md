# GAT

Aplicación web local para gestionar inventario, cotizaciones y cierres de caja. Está construida con Flask, SQLite y plantillas Jinja; el inventario también puede importarse desde Excel.

## Ejecutar en Windows

En VS Code, abre directamente la carpeta `GAT` que contiene `app.py`, `routes/` y `.vscode/`. Así se usa una sola carpeta de proyecto y el entorno correcto. En la terminal integrada ejecuta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python database.py
python crear_admin.py
$env:GAT_SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
python app.py
```

En la primera configuración, `crear_admin.py` permite crear una cuenta administradora o promover tu usuario existente con su DNI y asignarle una contraseña. No hay contraseñas predeterminadas. Abre `http://127.0.0.1:5000`. La clave de sesión generada se conserva solo en esa ventana de PowerShell; para mantener las sesiones entre reinicios, configura `GAT_SECRET_KEY` de forma permanente.

## Configuración

La aplicación acepta estas variables de entorno; ninguna es obligatoria para el uso local:

| Variable | Uso | Valor predeterminado |
| --- | --- | --- |
| `GAT_SECRET_KEY` | Firma segura de las sesiones | Clave aleatoria por ejecución |
| `GAT_DATABASE_PATH` | Ruta del archivo SQLite | `donglai.db` junto a `database.py` |
| `GAT_EXCEL_PATH` | Ruta del Excel de productos | `PRODUCTOS.xlsx` junto al código (o `PRODUCTS.xlsx`) |
| `GAT_HOST` | Interfaz de red | `127.0.0.1` |
| `GAT_PORT` | Puerto HTTP | `5000` |
| `GAT_DEBUG` | Activa el depurador local (`1`, `true`, `yes` o `si`) | Desactivado |

Respalda `donglai.db` y el Excel antes de moverlos o reemplazarlos. La carpeta `dist` y los ejecutables compilados son salidas de distribución; el código fuente en la raíz es la versión editable.

## Cómo está organizado el código

- `app.py`: configura Flask, carga dependencias compartidas y registra las rutas.
- `routes/auth.py`: inicio de sesión, registro y cierre de sesión.
- `routes/admin.py`: administración de roles, estado de cuentas y restablecimiento de contraseñas.
- `routes/dashboard.py`: página inicial y datos del panel.
- `routes/inventory.py`: operaciones, exportación e importación de Excel sin borrar el inventario.
- `routes/quotes.py`: creación, edición y exportación de cotizaciones.
- `routes/cash_closing.py`: cierres de caja, historial e informes.
- `database.py`: conexiones, tablas y operaciones SQLite.
- `donglai.db`: base de datos activa de SQLite; los archivos locales `.db` están excluidos de Git.
- `data/archive/`: bases originales preservadas antes de consolidar los datos. No se usan al ejecutar la aplicación.
- `data/archive/donglai_dist_backup.db`: origen con el historial de cotizaciones y cierres.
- `data/archive/donglai_parent_source.db`: origen con el inventario de la carpeta contenedora.
- `data/archive/donglai_project_before_merge.db`: copia de la base activa anterior a la consolidación.
- `app.spec`: configuración de PyInstaller para generar la aplicación de escritorio.
- `excel_handler.py`: lectura del catálogo Excel. `Cant/Caja` se guarda en `unidades_por_caja`; el stock se toma de `Stock Inicial`, `Stock`, `Existencias` o `Cantidad Inicial` si una de esas columnas existe. Si falta, conserva el stock actual y asigna cero a productos nuevos.
- `crear_admin.py`: configuración local y segura del administrador inicial; también permite recuperar el acceso del administrador desde la terminal del equipo.
- `templates/` y `static/`: páginas HTML, estilos e imágenes.

Las rutas conservan sus direcciones actuales para que las plantillas sigan funcionando. La lógica SQL que aún está dentro de algunas vistas puede moverse después a `database.py` por partes, sin cambiar el esquema de SQLite de golpe.

La base activa reúne el inventario y el historial encontrados en los archivos originales. Para trabajar, abre únicamente esta carpeta del proyecto en VS Code y usa su `.venv`; evita abrir la carpeta contenedora que está un nivel arriba.

## Administración de cuentas

El menú **Administrar usuarios** solo aparece para administradores. Para habilitar tu cuenta principal, ejecuta `python crear_admin.py` en la terminal de VS Code; ingresa tu DNI y elige una contraseña. En ese alta inicial, la cuenta indicada queda como única administradora y las cuentas admin antiguas pasan a trabajador. Luego puedes dar de alta a cada trabajador desde el panel. El registro público está deshabilitado para impedir que alguien se asigne permisos por su cuenta.

Roles disponibles: **Inventario / almacén**, **Ventas / cotizaciones**, **Caja / cierres**, **Trabajador general** (sin área hasta que se le asigne) y **Administrador** (acceso total). Los trabajadores inician directamente en su área. Las cuentas nuevas reciben una contraseña temporal que deben cambiar en el primer ingreso. Un administrador puede otorgar acceso de administrador a otra persona desde el panel.

Para trabajar con más de una empresa emisora, entra en **Razones sociales** desde el menú de administración y registra cada nombre legal, RUC y datos de contacto o pago. Al crear o editar una cotización se elige la empresa emisora; esos datos se guardan como una copia en la cotización y aparecen en el detalle y el PDF. Las cotizaciones anteriores quedan marcadas sin asignar y el inventario continúa compartido entre las empresas.

En el panel también se pueden eliminar cuentas que no tengan cotizaciones ni cierres asociados. Para conservar el historial, una cuenta con operaciones vinculadas solo puede desactivarse.

## Preferencias del navegador

La aplicación no guarda un idioma elegido en su propio menú. Usa el idioma preferido que envía el navegador para mostrar la traducción disponible (español, inglés o chino); si no hay coincidencia, usa español. El tema claro u oscuro sigue la preferencia de apariencia del sistema operativo y se actualiza si cambia mientras la página está abierta. La traducción automática adicional que ofrece cada navegador depende de la configuración del visitante.
