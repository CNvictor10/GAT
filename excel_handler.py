import pandas as pd
import os

# --- BUSCAR EL ARCHIVO EXCEL ---
def encontrar_excel():
    posibles_rutas = [
        os.environ.get('GAT_EXCEL_PATH'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PRODUCTOS.xlsx'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PRODUCTS.xlsx'),
    ]
    for ruta in posibles_rutas:
        if ruta and os.path.exists(ruta):
            print(f"✅ Archivo Excel encontrado en: {ruta}")
            return ruta
    print("❌ No se encontró el archivo PRODUCTOS.xlsx")
    return None

EXCEL_PATH = encontrar_excel()

def cargar_inventario_desde_excel(ruta=None):
    """Lee el catálogo y diferencia el stock de las unidades por caja."""
    try:
        ruta = ruta or EXCEL_PATH
        es_archivo_subido = hasattr(ruta, 'read')
        if ruta is None or (not es_archivo_subido and not os.path.exists(ruta)):
            print(f"⚠️ Archivo Excel no encontrado")
            return []
        
        print(f"📊 Cargando productos desde: {getattr(ruta, 'filename', ruta)}")
        
        # --- LEER LA HOJA 'PRODUCTOS' ---
        df = pd.read_excel(ruta, sheet_name='PRODUCTOS', header=0)
        
        todos_los_productos = []
        
        print(f"📊 Leyendo hoja: PRODUCTOS")
        productos_encontrados = 0
        
        for _, row in df.iterrows():
            try:
                # Extraer datos
                linea = str(row['Línea']) if pd.notna(row.get('Línea')) else ""
                categoria = str(row['Categoría']) if pd.notna(row.get('Categoría')) else ""
                nombre = str(row['Producto']).strip() if pd.notna(row.get('Producto')) else ""
                descripcion = str(row['Descripción']) if pd.notna(row.get('Descripción')) else ""
                
                if not nombre:
                    continue
                
                # Cant/Caja expresa el contenido del empaque, no las existencias.
                cantidad_caja = 0
                if pd.notna(row.get('Cant/Caja')):
                    try:
                        cantidad_caja = int(float(row['Cant/Caja']))
                    except:
                        cantidad_caja = 0
                
                # El sistema maneja precio por caja y precio por unidad por separado.
                precio_venta_unidad = 0
                if pd.notna(row.get('P. Venta Unit (S/)')):
                    try:
                        precio_venta_unidad = float(row['P. Venta Unit (S/)'])
                    except:
                        precio_venta_unidad = 0
                
                precio_venta_caja = 0
                if pd.notna(row.get('P. Caja Venta (S/)')):
                    try:
                        precio_venta_caja = float(row['P. Caja Venta (S/)'])
                    except:
                        pass
                if precio_venta_caja <= 0:
                    precio_venta_caja = precio_venta_unidad * cantidad_caja
                
                precio_compra_caja = 0
                if pd.notna(row.get('P. Caja Compra (S/)')):
                    try:
                        precio_compra_caja = float(row['P. Caja Compra (S/)'])
                    except:
                        precio_compra_caja = 0
                if pd.notna(row.get('P. Compra Unit (S/)')):
                    try:
                        precio_compra_unidad = float(row['P. Compra Unit (S/)'])
                    except:
                        precio_compra_unidad = 0
                else:
                    precio_compra_unidad = 0
                if precio_compra_caja <= 0:
                    precio_compra_caja = precio_compra_unidad * cantidad_caja

                columnas_stock = ('Stock Inicial', 'Stock', 'Existencias', 'Cantidad Inicial')
                stock_inicial = None
                for columna in columnas_stock:
                    if columna in row.index and pd.notna(row.get(columna)):
                        try:
                            stock_inicial = max(0, int(float(row.get(columna))))
                        except (TypeError, ValueError):
                            stock_inicial = None
                        break
                
                if nombre and precio_venta_unidad > 0:
                    producto = {
                        'nombre': nombre,
                        'nombre_en': '',
                        'nombre_zh': '',
                        'descripcion': descripcion if descripcion else nombre,
                        'categoria': categoria if categoria else linea,
                        'linea': linea,
                        'unidades_por_caja': cantidad_caja,
                        'cantidad': stock_inicial,
                        'precio_unitario': precio_venta_caja,
                        'precio_unidad': precio_venta_unidad,
                        'umbral_stock': 5,
                        'costo_adquisicion': precio_compra_caja,
                        'hoja': 'PRODUCTOS'
                    }
                    todos_los_productos.append(producto)
                    productos_encontrados += 1
            except Exception as e:
                continue
        
        print(f"  ✅ {productos_encontrados} productos cargados desde PRODUCTOS")
        print(f"✅ TOTAL: {len(todos_los_productos)} productos cargados desde Excel")
        return todos_los_productos
        
    except Exception as e:
        print(f"❌ Error al cargar Excel: {e}")
        import traceback
        traceback.print_exc()
        return []

def sincronizar_inventario_desde_excel(archivo=None):
    try:
        from database import crear_conexion
        productos = cargar_inventario_desde_excel(archivo)
        if not productos:
            return {"success": False, "message": "No se encontraron productos en el Excel"}
        
        conn = crear_conexion()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(inventario)")
        columnas = {row[1] for row in cursor.fetchall()}
        if 'unidades_por_caja' in columnas:
            tiene_unidades_por_caja = True
        else:
            tiene_unidades_por_caja = False

        cursor.execute("SELECT id, nombre, cantidad FROM inventario")
        existentes = {row['nombre'].strip().casefold(): (row['id'], row['cantidad']) for row in cursor.fetchall()}
        importados = 0
        actualizados = 0
        for p in productos:
            clave = p['nombre'].strip().casefold()
            campos = [
                'nombre_en=?', 'nombre_zh=?', 'descripcion=?', 'precio_unitario=?',
                'precio_unidad=?', 'umbral_stock=?', 'costo_adquisicion=?',
                'fecha_actualizacion=CURRENT_TIMESTAMP'
            ]
            valores = [
                p.get('nombre_en', ''), p.get('nombre_zh', ''), p.get('descripcion', ''),
                p.get('precio_unitario', 0), p.get('precio_unidad', 0),
                p.get('umbral_stock', 5), p.get('costo_adquisicion', 0)
            ]
            if tiene_unidades_por_caja:
                campos.append('unidades_por_caja=?')
                valores.append(p.get('unidades_por_caja', 0))

            if clave in existentes:
                product_id, stock_actual = existentes[clave]
                if p.get('cantidad') is not None:
                    campos.append('cantidad=?')
                    valores.append(p['cantidad'])
                else:
                    # El Excel actual no trae stock: conservar las existencias del sistema.
                    campos.append('cantidad=?')
                    valores.append(stock_actual)
                valores.append(product_id)
                cursor.execute(f"UPDATE inventario SET {', '.join(campos)} WHERE id=?", valores)
                actualizados += 1
            else:
                stock = p.get('cantidad') if p.get('cantidad') is not None else 0
                nombre_columns = [
                    'nombre', 'nombre_en', 'nombre_zh', 'descripcion', 'cantidad',
                    'precio_unitario', 'precio_unidad', 'umbral_stock', 'costo_adquisicion'
                ]
                values = [
                    p['nombre'], p.get('nombre_en', ''), p.get('nombre_zh', ''),
                    p.get('descripcion', ''), stock, p.get('precio_unitario', 0),
                    p.get('precio_unidad', 0), p.get('umbral_stock', 5),
                    p.get('costo_adquisicion', 0)
                ]
                if tiene_unidades_por_caja:
                    nombre_columns.append('unidades_por_caja')
                    values.append(p.get('unidades_por_caja', 0))
                placeholders = ', '.join('?' for _ in nombre_columns)
                cursor.execute(
                    f"INSERT INTO inventario ({', '.join(nombre_columns)}) VALUES ({placeholders})",
                    values,
                )
                importados += 1
        
        conn.commit()
        return {
            "success": True,
            "message": f"{importados} nuevos y {actualizados} actualizados; stock existente conservado si el Excel no incluye existencias.",
            "importados": importados,
            "actualizados": actualizados,
        }
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        return {"success": False, "message": f"Error: {str(e)}"}
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("🧪 Probando carga de Excel...")
    productos = cargar_inventario_desde_excel()
    print(f"\n📦 Total productos: {len(productos)}")
    if productos:
        print("\n📋 Primeros 5 productos:")
        for p in productos[:5]:
            print(f"  ID:{p['id']} | {p['nombre'][:40]}... | Stock:{p['cantidad']} | S/.{p['precio_unitario']}")
