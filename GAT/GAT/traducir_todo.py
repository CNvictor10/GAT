import sqlite3
from deep_translator import GoogleTranslator
import time

# Configuración de la base de datos
DB_NAME = 'donglai.db'


def crear_conexion():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def traducir_base_datos():
    print("--- INICIANDO TRADUCCIÓN MASIVA ---")
    conn = crear_conexion()
    cursor = conn.cursor()

    # Obtenemos todos los productos
    cursor.execute("SELECT id, nombre, nombre_en, nombre_zh FROM inventario")
    productos = cursor.fetchall()

    total = len(productos)
    print(f"Se encontraron {total} productos para revisar.\n")

    for i, p in enumerate(productos):
        pid = p['id']
        nombre_es = p['nombre']
        nuevo_en = p['nombre_en']
        nuevo_zh = p['nombre_zh']
        cambios = False

        print(f"[{i + 1}/{total}] Procesando: {nombre_es}")

        # 1. Traducir a Inglés si está vacío o es igual al español
        if not nuevo_en or nuevo_en == nombre_es:
            try:
                nuevo_en = GoogleTranslator(source='auto', target='en').translate(nombre_es)
                cambios = True
            except Exception as e:
                print(f"   Error EN: {e}")

        # 2. Traducir a Chino (Tradicional) si está vacío o es igual al español
        if not nuevo_zh or nuevo_zh == nombre_es:
            try:
                # zh-TW es Chino Tradicional (Taiwan/Hong Kong)
                nuevo_zh = GoogleTranslator(source='auto', target='zh-TW').translate(nombre_es)
                cambios = True
            except Exception as e:
                print(f"   Error ZH: {e}")

        # 3. Guardar si hubo cambios
        if cambios:
            conn.execute("UPDATE inventario SET nombre_en=?, nombre_zh=? WHERE id=?", (nuevo_en, nuevo_zh, pid))
            print(f"   -> EN: {nuevo_en}")
            print(f"   -> ZH: {nuevo_zh}")
            conn.commit()
        else:
            print("   -> Ya estaba traducido.")

    conn.close()
    print("\n--- ¡TRADUCCIÓN COMPLETADA EXITOSAMENTE! ---")


if __name__ == '__main__':
    traducir_base_datos()