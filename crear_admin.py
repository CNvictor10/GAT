"""Crea un administrador inicial o restablece el acceso de uno existente.

Ejecutar desde la terminal local del proyecto: python crear_admin.py
"""

from getpass import getpass
import re

from werkzeug.security import generate_password_hash

from database import (
    asegurar_columna_dni_usuarios,
    asegurar_columnas_administracion_usuarios,
    crear_conexion,
)


def main():
    asegurar_columna_dni_usuarios()
    asegurar_columnas_administracion_usuarios()

    dni = input('DNI de la cuenta que será administradora (8 dígitos): ').strip()
    if not re.fullmatch(r'\d{8}', dni):
        raise SystemExit('El DNI debe tener exactamente 8 dígitos.')

    nombre = input('Nombre para mostrar: ').strip()
    if not nombre:
        raise SystemExit('El nombre no puede quedar vacío.')

    password = getpass('Nueva contraseña (mínimo 8 caracteres): ')
    confirmacion = getpass('Repite la contraseña: ')
    if len(password) < 8:
        raise SystemExit('La contraseña debe tener al menos 8 caracteres.')
    if password != confirmacion:
        raise SystemExit('Las contraseñas no coinciden.')

    conn = crear_conexion()
    try:
        cuenta = conn.execute(
            'SELECT id FROM usuarios WHERE dni=? OR email=?',
            (dni, f'dni-{dni}@users.invalid'),
        ).fetchone()
        hash_password = generate_password_hash(password)
        if cuenta:
            administrador_id = cuenta['id']
            conn.execute(
                """UPDATE usuarios
                   SET nombre=?, dni=?, rol='admin', activo=1,
                       debe_cambiar_password=0, password=?,
                       session_version=session_version+1
                   WHERE id=?""",
                (nombre, dni, hash_password, administrador_id),
            )
            mensaje = 'Cuenta existente habilitada como administradora.'
        else:
            conn.execute(
                """INSERT INTO usuarios
                   (nombre, dni, email, password, rol, activo, debe_cambiar_password)
                   VALUES (?, ?, ?, ?, 'admin', 1, 0)""",
                (nombre, dni, f'dni-{dni}@users.invalid', hash_password),
            )
            administrador_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            mensaje = 'Cuenta administradora creada.'
        # El alta inicial deja una sola cuenta con control total. Otros administradores
        # podrán añadirse después desde el panel y por decisión explícita del titular.
        conn.execute(
            """UPDATE usuarios SET rol='trabajador', session_version=session_version+1
               WHERE rol='admin' AND id<>?""",
            (administrador_id,),
        )
        conn.commit()
        print(mensaje)
        print('Ya puedes iniciar sesión con tu DNI y la contraseña nueva.')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
