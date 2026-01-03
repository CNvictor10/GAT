import sqlite3


def crear_conexion():
    """
    Crea y devuelve una conexión a la base de datos SQLite.
    """
    conn = sqlite3.connect('clinica.db')
    conn.row_factory = sqlite3.Row
    return conn


def mostrar_cotizaciones():
    """
    Muestra todas las cotizaciones y sus detalles desde la base de datos.
    """
    conn = crear_conexion()
    cursor = conn.cursor()

    print("--- Historial de Cotizaciones ---")
    cursor.execute("SELECT * FROM cotizaciones ORDER BY fecha DESC")
    cotizaciones = cursor.fetchall()

    if not cotizaciones:
        print("No hay cotizaciones registradas.")
    else:
        for coti in cotizaciones:
            print(f"ID Cotización: {coti['id']}")
            print(f"  Cliente: {coti['cliente_nombre']} ({coti['cliente_email']})")
            print(f"  Fecha: {coti['fecha']}")
            print(f"  Total: ${coti['total']:.2f}")
            print(f"  Estado: {coti['estado']}")
            print(f"  Tipo de Pago: {coti['tipo_pago'] if coti['tipo_pago'] else 'N/A'}")
            print("  --- Productos ---")

            # Consultar los detalles de la cotización
            cursor.execute("""
                           SELECT cd.cantidad,
                                  cd.precio_unitario_cotizado,
                                  i.nombre AS nombre_producto
                           FROM cotizacion_detalles cd
                                    JOIN
                                inventario i ON cd.producto_id = i.id
                           WHERE cd.cotizacion_id = ?
                           """, (coti['id'],))
            detalles = cursor.fetchall()

            if detalles:
                for det in detalles:
                    subtotal = det['cantidad'] * det['precio_unitario_cotizado']
                    print(
                        f"    - {det['cantidad']} x {det['nombre_producto']} (${det['precio_unitario_cotizado']:.2f}) = ${subtotal:.2f}")
            print("-" * 25)

    conn.close()


def mostrar_cierres_caja():
    """
    Muestra los registros de cierres de caja.
    """
    conn = crear_conexion()
    cursor = conn.cursor()

    print("\n--- Historial de Cierres de Caja ---")
    cursor.execute("SELECT * FROM cierres_caja ORDER BY fecha DESC, hora DESC")
    cierres = cursor.fetchall()

    if not cierres:
        print("No hay cierres de caja registrados.")
    else:
        for cierre in cierres:
            print(f"ID Cierre: {cierre['id']}")
            print(f"  Fecha: {cierre['fecha']} {cierre['hora']}")
            print(f"  Monto Ventas: ${cierre['monto_ventas']:.2f}")
            print(f"  Monto Ingresado: ${cierre['monto_ingresado']:.2f}")
            print(f"  Diferencia: ${cierre['diferencia']:.2f}")
            print("-" * 25)

    conn.close()


if __name__ == "__main__":
    mostrar_cotizaciones()
    mostrar_cierres_caja()
