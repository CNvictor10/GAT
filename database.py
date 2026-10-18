import sqlite3
import datetime
import json
import os
import re

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.environ.get('GAT_DATABASE_PATH') or os.path.join(PROJECT_DIR, 'donglai.db')

def crear_conexion():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def asegurar_columna_dni_usuarios(conn=None):
    """Añade DNI a bases existentes sin modificar las cuentas antiguas."""
    cerrar_conexion = conn is None
    conn = conn or crear_conexion()
    cursor = conn.cursor()
    tabla = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'usuarios'"
    ).fetchone()
    if not tabla:
        if cerrar_conexion:
            conn.close()
        return

    columnas = {fila[1] for fila in cursor.execute("PRAGMA table_info(usuarios)")}
    if 'dni' not in columnas:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN dni TEXT")

    dnis_usados = {
        str(fila[0]).strip()
        for fila in cursor.execute("SELECT dni FROM usuarios WHERE dni IS NOT NULL AND dni <> ''")
    }
    for usuario_id, email in cursor.execute(
        "SELECT id, email FROM usuarios WHERE dni IS NULL AND email LIKE 'dni-%@users.invalid'"
    ).fetchall():
        coincidencia = re.fullmatch(r'dni-(\d{8})@users\.invalid', email or '', re.IGNORECASE)
        if coincidencia and coincidencia.group(1) not in dnis_usados:
            dni_legacy = coincidencia.group(1)
            cursor.execute("UPDATE usuarios SET dni=? WHERE id=?", (dni_legacy, usuario_id))
            dnis_usados.add(dni_legacy)

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_dni "
        "ON usuarios(dni) WHERE dni IS NOT NULL AND dni <> ''"
    )
    conn.commit()
    if cerrar_conexion:
        conn.close()


def asegurar_columna_unidades_por_caja(conn=None):
    """Guarda por separado el contenido de una caja y las existencias del producto."""
    cerrar_conexion = conn is None
    conn = conn or crear_conexion()
    tabla = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventario'"
    ).fetchone()
    if tabla:
        columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(inventario)")}
        if 'unidades_por_caja' not in columnas:
            conn.execute("ALTER TABLE inventario ADD COLUMN unidades_por_caja INTEGER NOT NULL DEFAULT 0")
            conn.commit()
    if cerrar_conexion:
        conn.close()


def asegurar_columna_imagen_producto(conn=None):
    """Añade la ruta de imagen al catálogo existente sin alterar sus productos."""
    cerrar_conexion = conn is None
    conn = conn or crear_conexion()
    tabla = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventario'"
    ).fetchone()
    if tabla:
        columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(inventario)")}
        if 'imagen' not in columnas:
            conn.execute("ALTER TABLE inventario ADD COLUMN imagen TEXT NOT NULL DEFAULT ''")
            conn.commit()
    if cerrar_conexion:
        conn.close()


def asegurar_columnas_administracion_usuarios(conn=None):
    """Añade los campos necesarios para suspender cuentas y exigir cambios de clave."""
    cerrar_conexion = conn is None
    conn = conn or crear_conexion()
    tabla = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='usuarios'"
    ).fetchone()
    if tabla:
        columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(usuarios)")}
        if 'activo' not in columnas:
            conn.execute("ALTER TABLE usuarios ADD COLUMN activo INTEGER NOT NULL DEFAULT 1")
        if 'debe_cambiar_password' not in columnas:
            conn.execute("ALTER TABLE usuarios ADD COLUMN debe_cambiar_password INTEGER NOT NULL DEFAULT 0")
        if 'session_version' not in columnas:
            conn.execute("ALTER TABLE usuarios ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    if cerrar_conexion:
        conn.close()


def asegurar_columnas_razon_social_cotizaciones(conn=None):
    """Añade razones sociales configurables y guarda una copia en cada cotización."""
    cerrar_conexion = conn is None
    conn = conn or crear_conexion()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS razones_sociales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL COLLATE NOCASE UNIQUE,
            ruc TEXT NOT NULL DEFAULT '',
            telefono TEXT NOT NULL DEFAULT '',
            medios_pago TEXT NOT NULL DEFAULT '',
            activa INTEGER NOT NULL DEFAULT 1,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    tabla = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cotizaciones'"
    ).fetchone()
    if tabla:
        columnas = {fila[1] for fila in conn.execute('PRAGMA table_info(cotizaciones)')}
        migraciones = {
            'razon_social_id': 'INTEGER',
            'razon_social_nombre': "TEXT NOT NULL DEFAULT ''",
            'razon_social_ruc': "TEXT NOT NULL DEFAULT ''",
            'razon_social_telefono': "TEXT NOT NULL DEFAULT ''",
            'razon_social_medios_pago': "TEXT NOT NULL DEFAULT ''",
        }
        for columna, tipo in migraciones.items():
            if columna not in columnas:
                conn.execute(f'ALTER TABLE cotizaciones ADD COLUMN {columna} {tipo}')
    conn.commit()
    if cerrar_conexion:
        conn.close()


def asegurar_columnas_folios_y_cierres(conn=None):
    """Aplica al iniciar la app los folios mensuales y fechas operativas de caja."""
    cerrar_conexion = conn is None
    conn = conn or crear_conexion()
    tablas = {fila[0] for fila in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('cotizaciones', 'cierres_caja')"
    )}
    if 'cotizaciones' in tablas:
        columnas = {fila[1] for fila in conn.execute('PRAGMA table_info(cotizaciones)')}
        if 'numero_cotizacion' not in columnas:
            conn.execute("ALTER TABLE cotizaciones ADD COLUMN numero_cotizacion TEXT NOT NULL DEFAULT ''")
        filas_sin_folio = conn.execute(
            "SELECT id, fecha FROM cotizaciones WHERE numero_cotizacion IS NULL OR numero_cotizacion='' ORDER BY fecha, id"
        ).fetchall()
        for fila in filas_sin_folio:
            periodo = str(fila['fecha'] or '')[:7].replace('-', '')
            if len(periodo) != 6 or not periodo.isdigit():
                periodo = '000000'
            ultimo = conn.execute(
                "SELECT COALESCE(MAX(CAST(substr(numero_cotizacion, 8) AS INTEGER)), 0) "
                "FROM cotizaciones WHERE numero_cotizacion LIKE ?", (f'{periodo}-%',),
            ).fetchone()[0]
            conn.execute("UPDATE cotizaciones SET numero_cotizacion=? WHERE id=?",
                         (f'{periodo}-{ultimo + 1:04d}', fila['id']))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cotizaciones_numero ON cotizaciones(numero_cotizacion)")
    if 'cierres_caja' in tablas:
        columnas = {fila[1] for fila in conn.execute('PRAGMA table_info(cierres_caja)')}
        if 'fecha_operativa' not in columnas:
            conn.execute("ALTER TABLE cierres_caja ADD COLUMN fecha_operativa TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE cierres_caja SET fecha_operativa=substr(fecha, 1, 10) WHERE fecha_operativa='' OR fecha_operativa IS NULL")
    conn.commit()
    if cerrar_conexion:
        conn.close()

def importar_productos_desde_excel(archivo=None):
    """Importa sin borrar productos ni cambiar el stock existente."""
    from excel_handler import sincronizar_inventario_desde_excel

    resultado = sincronizar_inventario_desde_excel(archivo)
    if not resultado.get('success'):
        print(f"No se importó el Excel: {resultado.get('message', 'error desconocido')}")
        return 0
    return int(resultado.get('importados', 0))

def inicializar_db():
    """Crea tablas, añade columnas faltantes (migraciones) y datos iniciales."""
    conn = crear_conexion()
    cursor = conn.cursor()

    def check_and_add_column(table, column, type, default=None):
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [col[1] for col in cursor.fetchall()]
        if column not in cols:
            print(f"Migrando: Añadiendo '{column}' a '{table}'...")
            default_clause = ""
            if default is not None:
                if default == 'NULL':
                    default_clause = " DEFAULT NULL"
                elif isinstance(default, (int, float)):
                    default_clause = f" DEFAULT {default}"
                else:
                    default_clause = f" DEFAULT '{default}'"
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type}{default_clause}")
                conn.commit()
                print(f"Éxito: Columna {column} añadida a {table}.")
            except Exception as e:
                print(f"Error migración al añadir {column} a {table}: {e}")

    print("Creando o verificando tablas...")
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        nombre TEXT NOT NULL, 
        email TEXT UNIQUE, 
        dni TEXT UNIQUE,
        password TEXT NOT NULL, 
        rol TEXT NOT NULL DEFAULT 'usuario', 
        activo INTEGER NOT NULL DEFAULT 1,
        debe_cambiar_password INTEGER NOT NULL DEFAULT 0,
        session_version INTEGER NOT NULL DEFAULT 0,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    asegurar_columna_dni_usuarios(conn)
    asegurar_columnas_administracion_usuarios(conn)

    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY, 
        nombre TEXT NOT NULL, 
        nombre_en TEXT DEFAULT '',
        nombre_zh TEXT DEFAULT '',
        descripcion TEXT, 
        cantidad INTEGER NOT NULL DEFAULT 0 CHECK(cantidad >= 0), 
        precio_unitario REAL NOT NULL, 
        precio_unidad REAL DEFAULT 0,
        umbral_stock INTEGER DEFAULT 10, 
        costo_adquisicion REAL DEFAULT 0,
        unidades_por_caja INTEGER NOT NULL DEFAULT 0,
        imagen TEXT NOT NULL DEFAULT '',
        fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cotizaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        cliente_nombre TEXT NOT NULL, 
        cliente_celular TEXT, 
        cliente_email TEXT, 
        cliente_ruc TEXT, 
        fecha TEXT NOT NULL, 
        total REAL NOT NULL, 
        estado TEXT NOT NULL DEFAULT 'pendiente', 
        tipo_pago TEXT, 
        fecha_aprobacion TEXT,
        cliente_direccion TEXT,
        usuario_id INTEGER NOT NULL,
        FOREIGN KEY (usuario_id) REFERENCES usuarios (id))''')
    asegurar_columnas_razon_social_cotizaciones(conn)

    cursor.execute('''CREATE TABLE IF NOT EXISTS cotizacion_detalles (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        cotizacion_id INTEGER NOT NULL, 
        producto_id INTEGER NOT NULL, 
        cantidad INTEGER NOT NULL, 
        descripcion TEXT, 
        precio_unitario_cotizado REAL NOT NULL,
        costo_unitario REAL DEFAULT 0,
        FOREIGN KEY (cotizacion_id) REFERENCES cotizaciones (id), 
        FOREIGN KEY (producto_id) REFERENCES inventario (id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cierres_caja (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        fecha TEXT NOT NULL, 
        hora TEXT NOT NULL, 
        total_ventas REAL NOT NULL, 
        efectivo_en_caja REAL NOT NULL, 
        diferencia REAL NOT NULL, 
        observaciones TEXT, 
        usuario_id INTEGER NOT NULL, 
        desglose_pagos TEXT NOT NULL,
        diferencia_total REAL DEFAULT 0,
        monto_apertura REAL DEFAULT 0,
        ingresos_extra REAL DEFAULT 0,
        egresos REAL DEFAULT 0,
        efectivo_teorico REAL DEFAULT 0,
        otros_medios_teoricos REAL DEFAULT 0,
        costo_total_cierre REAL DEFAULT 0,
        ganancia_bruta REAL DEFAULT 0,
        fecha_operativa TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (usuario_id) REFERENCES usuarios (id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos_caja (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        cotizacion_id INTEGER NOT NULL, 
        fecha TEXT NOT NULL, 
        ingreso_total REAL NOT NULL, 
        costo_total REAL NOT NULL, 
        tipo_pago TEXT NOT NULL DEFAULT 'Efectivo',
        FOREIGN KEY(cotizacion_id) REFERENCES cotizaciones(id))''')

    conn.commit()

    print("Iniciando migraciones de columnas...")
    asegurar_columnas_folios_y_cierres(conn)
    check_and_add_column('inventario', 'precio_unidad', 'REAL', 0.0)
    check_and_add_column('inventario', 'costo_adquisicion', 'REAL', 0.0)
    check_and_add_column('inventario', 'nombre_en', 'TEXT', '')
    check_and_add_column('inventario', 'nombre_zh', 'TEXT', '')
    check_and_add_column('inventario', 'unidades_por_caja', 'INTEGER', 0)
    check_and_add_column('inventario', 'imagen', 'TEXT', '')
    check_and_add_column('cotizaciones', 'fecha_aprobacion', 'TEXT', 'NULL')
    check_and_add_column('cotizaciones', 'cliente_direccion', 'TEXT', '')
    # Asigna folios mensuales a los registros históricos, conservando el ID interno.
    check_and_add_column('cotizacion_detalles', 'costo_unitario', 'REAL', 0.0)
    check_and_add_column('movimientos_caja', 'tipo_pago', 'TEXT', 'Efectivo')
    check_and_add_column('cierres_caja', 'diferencia_total', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'monto_apertura', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'ingresos_extra', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'egresos', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'efectivo_teorico', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'otros_medios_teoricos', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'costo_total_cierre', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'ganancia_bruta', 'REAL', 0.0)

    print("Verificando usuario administrador...")
    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE rol='admin' AND activo=1")
    if cursor.fetchone()[0] == 0:
        print("No hay usuario administrador. Ejecuta crear_admin.py para habilitar el acceso inicial.")

    cursor.execute("SELECT COUNT(*) FROM inventario")
    inventario_vacio = cursor.fetchone()[0] == 0
    if inventario_vacio:
        print("📦 Inventario vacío: importando productos desde Excel sin borrar registros.")
        importar_productos_desde_excel()

    conn.close()
    print("✅ Inicialización de la base de datos completada.")

# --- FUNCIONES DE NEGOCIO (requeridas por app.py) ---

def registrar_pago_cotizacion(cotizacion_id, monto, tipo_pago):
    conn = crear_conexion()
    try:
        cursor = conn.cursor()
        conn.execute("BEGIN IMMEDIATE;")
        cursor.execute("SELECT id, total, estado, fecha_aprobacion FROM cotizaciones WHERE id = ?", (cotizacion_id,))
        cot = cursor.fetchone()
        if not cot:
            return {"success": False, "message": f"Cotización ID {cotizacion_id} no encontrada."}
        if cot['estado'] in ('Aprobada', 'Pagada'):
            return {"success": False, "message": "Esta cotización ya está pagada."}

        monto = round(float(monto), 2)
        total = round(float(cot['total'] or 0), 2)
        pagado = round(float(cursor.execute(
            "SELECT COALESCE(SUM(ingreso_total), 0) FROM movimientos_caja WHERE cotizacion_id = ?",
            (cotizacion_id,),
        ).fetchone()[0] or 0), 2)
        saldo = round(total - pagado, 2)
        if monto <= 0:
            return {"success": False, "message": "El monto del abono debe ser mayor que cero."}
        if monto > saldo + 0.001:
            return {"success": False, "message": f"El abono supera el saldo pendiente de S/ {saldo:.2f}."}
        if not tipo_pago or not tipo_pago.strip():
            return {"success": False, "message": "Selecciona el medio de pago."}

        primer_abono = pagado <= 0
        cogs = 0.0
        if primer_abono:
            cursor.execute("""
                SELECT cd.producto_id, cd.cantidad, cd.costo_unitario,
                       i.cantidad AS stock_actual, i.nombre AS prod_nombre
                FROM cotizacion_detalles cd
                JOIN inventario i ON i.id = cd.producto_id
                WHERE cd.cotizacion_id = ?
            """, (cotizacion_id,))
            detalles = cursor.fetchall()
            for detalle in detalles:
                if detalle['cantidad'] > detalle['stock_actual']:
                    conn.rollback()
                    return {"success": False, "message": f"Stock insuficiente: {detalle['prod_nombre']}"}
            for detalle in detalles:
                cursor.execute("UPDATE inventario SET cantidad = cantidad - ? WHERE id = ?",
                               (detalle['cantidad'], detalle['producto_id']))
                cogs += (detalle['costo_unitario'] or 0.0) * detalle['cantidad']
        
        fecha_pago = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        nuevo_pagado = round(pagado + monto, 2)
        nuevo_estado = 'Pagada' if nuevo_pagado >= total - 0.001 else 'Parcial'
        cursor.execute("SELECT COUNT(DISTINCT tipo_pago) FROM movimientos_caja WHERE cotizacion_id=?",
                       (cotizacion_id,))
        metodos_previos = cursor.fetchone()[0]
        metodo_resumen = 'Mixto' if metodos_previos and cursor.execute(
            "SELECT 1 FROM movimientos_caja WHERE cotizacion_id=? AND tipo_pago<>? LIMIT 1",
            (cotizacion_id, tipo_pago),
        ).fetchone() else tipo_pago
        cursor.execute("UPDATE cotizaciones SET estado=?, tipo_pago=?, fecha_aprobacion=COALESCE(fecha_aprobacion, ?) WHERE id=?",
                       (nuevo_estado, metodo_resumen, fecha_pago, cotizacion_id))
        cursor.execute("INSERT INTO movimientos_caja (cotizacion_id, fecha, ingreso_total, costo_total, tipo_pago) VALUES (?,?,?,?,?)",
                       (cotizacion_id, fecha_pago, monto, cogs, tipo_pago))
        conn.commit()
        mensaje = "Pago completo registrado." if nuevo_estado == 'Pagada' else f"Abono registrado. Saldo pendiente: S/ {total - nuevo_pagado:.2f}."
        if primer_abono:
            mensaje += " Stock descontado."
        return {"success": True, "message": mensaje}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Error: {str(e)}"}
    finally:
        conn.close()


def aprobar_cotizacion(cotizacion_id, tipo_pago):
    """Compatibilidad con el flujo anterior: registra el saldo completo."""
    conn = crear_conexion()
    try:
        row = conn.execute("SELECT total FROM cotizaciones WHERE id=?", (cotizacion_id,)).fetchone()
        if not row:
            return {"success": False, "message": f"Cotización ID {cotizacion_id} no encontrada."}
        monto = round(float(row['total'] or 0), 2)
    finally:
        conn.close()
    return registrar_pago_cotizacion(cotizacion_id, monto, tipo_pago)

def obtener_ventas_aprobadas_para_cierre(fecha_inicio, fecha_fin):
    conn = crear_conexion()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT SUM(ingreso_total) as t, SUM(costo_total) as c FROM movimientos_caja WHERE fecha >= ? AND fecha <= ?",
                       (fecha_inicio, fecha_fin))
        res = cursor.fetchone()
        total = res['t'] or 0.0
        cogs = res['c'] or 0.0
        
        cursor.execute("SELECT tipo_pago, SUM(ingreso_total) as s FROM movimientos_caja WHERE fecha >= ? AND fecha <= ? GROUP BY tipo_pago",
                       (fecha_inicio, fecha_fin))
        desglose = {row['tipo_pago']: round(row['s'] or 0.0, 2) for row in cursor.fetchall()}

        cursor.execute("""
            SELECT mc.id, mc.cotizacion_id AS cot_id, mc.fecha,
                   mc.ingreso_total, mc.tipo_pago, c.cliente_nombre,
                   c.numero_cotizacion
            FROM movimientos_caja mc
            JOIN cotizaciones c ON c.id = mc.cotizacion_id
            WHERE mc.fecha >= ? AND mc.fecha <= ?
            ORDER BY mc.fecha, mc.id
        """, (fecha_inicio, fecha_fin))
        movimientos = []
        for row in cursor.fetchall():
            movimiento = dict(row)
            movimiento['fecha'] = str(movimiento['fecha']).split(' ')[-1][:5]
            movimientos.append(movimiento)
        
        return {"total_ventas": round(total, 2), "costo_total_cierre": round(cogs, 2), "desglose_pagos": desglose, "movimientos": movimientos}
    except Exception as e:
        return {"total_ventas": 0, "costo_total_cierre": 0, "desglose_pagos": {}, "movimientos": []}
    finally:
        conn.close()

def crear_cierre_caja(inicio, fin, uid, apertura, extra, egresos, fisico, obs):
    fecha_operativa = str(inicio)[:10]
    conn = crear_conexion()
    try:
        existente = conn.execute("SELECT 1 FROM cierres_caja WHERE fecha_operativa=?", (fecha_operativa,)).fetchone()
        if existente:
            return {"success": False, "message": f"La caja del {fecha_operativa} ya tiene un cierre registrado."}
    finally:
        conn.close()

    datos = obtener_ventas_aprobadas_para_cierre(inicio, fin)
    total_ventas = datos['total_ventas']
    cogs = datos['costo_total_cierre']
    
    efectivo_ventas = datos['desglose_pagos'].get('Efectivo', 0.0)
    otros_medios_teoricos = total_ventas - efectivo_ventas
    efectivo_teorico = apertura + efectivo_ventas + extra - egresos
    diferencia = fisico - efectivo_teorico
    ganancia = total_ventas - cogs
    
    conn = crear_conexion()
    try:
        fecha = datetime.datetime.now().strftime('%Y-%m-%d')
        hora = datetime.datetime.now().strftime('%H:%M:%S')
        conn.execute("""
            INSERT INTO cierres_caja (fecha, hora, total_ventas, efectivo_en_caja, diferencia, 
            observaciones, usuario_id, desglose_pagos, monto_apertura, ingresos_extra, egresos, 
            efectivo_teorico, otros_medios_teoricos, costo_total_cierre, ganancia_bruta, diferencia_total, fecha_operativa)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (fecha, hora, total_ventas, fisico, diferencia, obs, uid, json.dumps(datos['desglose_pagos']),
              apertura, extra, egresos, efectivo_teorico, otros_medios_teoricos, cogs, ganancia, diferencia, fecha_operativa))
        conn.commit()
        return {"success": True, "message": "Cierre registrado."}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Error: {str(e)}"}
    finally:
        conn.close()

def sincronizar_inventario_desde_excel(archivo=None):
    from excel_handler import sincronizar_inventario_desde_excel as sincronizar
    return sincronizar(archivo)

if __name__ == '__main__':
    print("🚀 Iniciando configuración de la base de datos...")
    inicializar_db()
    print("\n✅ Base de datos Donglai.db lista para usar.")
    print("Para crear o restablecer tu administrador, ejecuta: python crear_admin.py")
    
    try:
        conn = crear_conexion()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM inventario")
        total = cursor.fetchone()['total']
        conn.close()
        print(f"📦 Total de productos en inventario: {total}")
    except Exception as e:
        print(f"⚠️ Error al verificar productos: {e}")
