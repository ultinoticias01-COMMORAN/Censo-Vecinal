import hashlib
import io
import json
import sqlite3
from datetime import datetime
import pandas as pd
import plotly.express as px
import streamlit as st

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE PÁGINA Y CONSTANTES
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Censo Comunitario Avanzado", page_icon="🏡", layout="wide"
)

DB_FILE = "censo.db"

CAMPOS_BASE_DEFAULT = {
    "cedula": ("Cédula de Identidad", "texto", "[]"),
    "nombres": ("Nombres", "texto", "[]"),
    "apellidos": ("Apellidos", "texto", "[]"),
    "sexo": (
        "Sexo / Género",
        "desplegable",
        json.dumps(["Femenino", "Masculino", "Otro"]),
    ),
    "fecha_nac": ("Fecha de Nacimiento", "texto", "[]"),
    "telefono": ("Teléfono de Contacto", "texto", "[]"),
    "manzana": ("Manzana / Sector", "texto", "[]"),
    "fecha_llegada": ("Fecha de Llegada a la Comunidad", "texto", "[]"),
    "direccion": ("Dirección Detallada de Habitación", "texto", "[]"),
    "estado_civil": (
        "Estado Civil",
        "desplegable",
        json.dumps([
            "Soltero/a",
            "Casado/a",
            "Concubino/a",
            "Divorciado/a",
            "Viudo/a",
        ]),
    ),
    "condicion_salud": (
        "Condición / Afectación de Salud",
        "desplegable",
        json.dumps([
            "Ninguna",
            "Enfermedad Crónica",
            "Discapacidad",
            "Adulto Mayor Encamado",
            "Embarazada",
            "Población de Riesgo",
            "Otra",
        ]),
    ),
    "detalle_salud": ("Detalles adicionales de salud", "texto", "[]"),
}

LISTA_PERMISOS = [
    "ver_censo",
    "registrar_habitantes",
    "editar_habitantes",
    "eliminar_habitantes",
    "ver_estadisticas",
    "gestion_bitacora",
    "bitacora_comunal",
    "personalizar_etiquetas",
    "respaldos_importacion",
]


# -----------------------------------------------------------------------------
# 2. FUNCIONES DE BASE DE DATOS Y MIGRACIONES
# -----------------------------------------------------------------------------
def hash_password(password: str) -> str:
  return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_connection():
  return sqlite3.connect(DB_FILE)


def init_db():
  with get_connection() as conn:
    cursor = conn.cursor()

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS habitantes (
                cedula TEXT PRIMARY KEY,
                nombres TEXT,
                apellidos TEXT,
                sexo TEXT,
                fecha_nac TEXT,
                fecha_llegada TEXT,
                direccion TEXT,
                manzana TEXT,
                telefono TEXT,
                estado_civil TEXT DEFAULT 'Soltero/a',
                conyuge_cedula TEXT DEFAULT '',
                es_padre_madre INTEGER DEFAULT 0,
                hijos_cedulas TEXT DEFAULT '[]',
                pertenece_consejo INTEGER DEFAULT 0,
                cargo_consejo TEXT DEFAULT 'Ninguno',
                condicion_salud TEXT DEFAULT 'Ninguna',
                detalle_salud TEXT DEFAULT '',
                es_jefe_hogar INTEGER DEFAULT 0,
                jefe_hogar_cedula TEXT DEFAULT '',
                campos_adicionales TEXT DEFAULT '{}'
            )
        """)

    cursor.execute("PRAGMA table_info(habitantes)")
    cols_hab = [column[1] for column in cursor.fetchall()]
    nuevas_columnas = [
        ("estado_civil", "TEXT DEFAULT 'Soltero/a'"),
        ("conyuge_cedula", "TEXT DEFAULT ''"),
        ("es_padre_madre", "INTEGER DEFAULT 0"),
        ("hijos_cedulas", "TEXT DEFAULT '[]'"),
        ("pertenece_consejo", "INTEGER DEFAULT 0"),
        ("cargo_consejo", "TEXT DEFAULT 'Ninguno'"),
        ("es_jefe_hogar", "INTEGER DEFAULT 0"),
        ("jefe_hogar_cedula", "TEXT DEFAULT ''"),
        ("campos_adicionales", "TEXT DEFAULT '{}'"),
    ]
    for col_nom, col_tipo in nuevas_columnas:
      if col_nom not in cols_hab:
        cursor.execute(f"ALTER TABLE habitantes ADD COLUMN {col_nom} {col_tipo}")

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_comunidad (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_comunidad TEXT,
                nombre_consejo TEXT,
                periodo TEXT,
                vencimiento TEXT
            )
        """)
    cursor.execute("SELECT COUNT(*) FROM config_comunidad")
    if cursor.fetchone()[0] == 0:
      cursor.execute(
          """
                INSERT INTO config_comunidad (nombre_comunidad, nombre_consejo, periodo, vencimiento)
                VALUES (?, ?, ?, ?)
            """,
          (
              "Comunidad Turpialito",
              "Consejo Comunal Nuevo Horizonte",
              "2024 - 2026",
              "06/09/2026",
          ),
      )

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                username TEXT PRIMARY KEY,
                password TEXT,
                nombre_completo TEXT,
                rol TEXT,
                permisos TEXT DEFAULT '{}'
            )
        """)

    cursor.execute("PRAGMA table_info(usuarios)")
    cols_usuarios = [column[1] for column in cursor.fetchall()]
    if "permisos" not in cols_usuarios:
      cursor.execute(
          "ALTER TABLE usuarios ADD COLUMN permisos TEXT DEFAULT '{}'"
      )
      perm_master = json.dumps({p: True for p in LISTA_PERMISOS})
      perm_admin = json.dumps(
          {p: True for p in LISTA_PERMISOS if p != "personalizar_etiquetas"}
      )
      perm_user = json.dumps({"ver_censo": True, "ver_estadisticas": True})
      cursor.execute(
          "UPDATE usuarios SET permisos = ? WHERE username = 'master'",
          (perm_master,),
      )
      cursor.execute(
          "UPDATE usuarios SET permisos = ? WHERE username = 'admin'",
          (perm_admin,),
      )
      cursor.execute(
          "UPDATE usuarios SET permisos = ? WHERE username = 'user'",
          (perm_user,),
      )

    cursor.execute("SELECT username, password FROM usuarios")
    usuarios_existentes = cursor.fetchall()

    if not usuarios_existentes:
      permisos_master = json.dumps({p: True for p in LISTA_PERMISOS})
      permisos_admin = json.dumps(
          {p: True for p in LISTA_PERMISOS if p != "personalizar_etiquetas"}
      )
      permisos_user = json.dumps({"ver_censo": True, "ver_estadisticas": True})

      cursor.execute(
          "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)",
          (
              "master",
              hash_password("master123"),
              "Usuario Master",
              "Master",
              permisos_master,
          ),
      )
      cursor.execute(
          "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)",
          (
              "admin",
              hash_password("admin123"),
              "Administrador Principal",
              "Administrador",
              permisos_admin,
          ),
      )
      cursor.execute(
          "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)",
          (
              "user",
              hash_password("user123"),
              "Visualizador Invitado",
              "Visualizador",
              permisos_user,
          ),
      )
    else:
      for user, pwd in usuarios_existentes:
        if len(pwd) != 64:
          pwd_encriptada = hash_password(pwd)
          cursor.execute(
              "UPDATE usuarios SET password = ? WHERE username = ?",
              (pwd_encriptada, user),
          )

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS configuracion_estilo_campos (
                clave_campo TEXT PRIMARY KEY,
                etiqueta TEXT,
                tipo_control TEXT,
                opciones_json TEXT
            )
        """)

    for clave, (etiqueta_def, tipo_def, opciones_def) in CAMPOS_BASE_DEFAULT.items():
      cursor.execute(
          """
                INSERT OR IGNORE INTO configuracion_estilo_campos (clave_campo, etiqueta, tipo_control, opciones_json)
                VALUES (?, ?, ?, ?)
            """,
          (clave, etiqueta_def, tipo_def, opciones_def),
      )

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS bitacora_documentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cedula TEXT,
                tipo_documento TEXT,
                descripcion TEXT,
                fecha_emision TEXT,
                emitido_por TEXT
            )
        """)

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS bitacora_oficios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                vocero_responsable TEXT,
                titulo TEXT,
                institucion_destino TEXT,
                descripcion TEXT,
                estatus TEXT
            )
        """)

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS bitacora_eventualidades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_inicio TEXT,
                hora_inicio TEXT,
                fecha_fin TEXT,
                hora_fin TEXT,
                tipo_evento TEXT,
                sector_afectado TEXT,
                detalles TEXT,
                atendido INTEGER DEFAULT 0
            )
        """)

    cursor.execute("PRAGMA table_info(bitacora_eventualidades)")
    cols_ev_db = [c[1] for c in cursor.fetchall()]
    if "fecha_inicio" not in cols_ev_db:
      cursor.execute(
          "ALTER TABLE bitacora_eventualidades ADD COLUMN fecha_inicio TEXT"
      )
    if "hora_inicio" not in cols_ev_db:
      cursor.execute(
          "ALTER TABLE bitacora_eventualidades ADD COLUMN hora_inicio TEXT"
      )
    if "fecha_fin" not in cols_ev_db:
      cursor.execute(
          "ALTER TABLE bitacora_eventualidades ADD COLUMN fecha_fin TEXT"
      )
    if "hora_fin" not in cols_ev_db:
      cursor.execute(
          "ALTER TABLE bitacora_eventualidades ADD COLUMN hora_fin TEXT"
      )

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS vocerias_comite (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                comite TEXT,
                nombre_vocero TEXT,
                cedula_vocero TEXT,
                telefono TEXT,
                correo TEXT
            )
        """)
    cursor.execute("SELECT COUNT(*) FROM vocerias_comite")
    if cursor.fetchone()[0] == 0:
      vocerias_iniciales = [
          ("Mesa Técnica de Agua", "Juan Pérez", "12345678", "0412-1111111", ""),
          (
              "Finanzas y Contraloría",
              "María Rodríguez",
              "87654321",
              "0414-2222222",
              "",
          ),
          ("Seguridad Ciudadana", "Carlos Gómez", "11223344", "0416-3333333", ""),
          (
              "Educación y Cultura",
              "Ana Martínez",
              "44332211",
              "0424-4444444",
              "",
          ),
      ]
      cursor.executemany(
          """
                INSERT INTO vocerias_comite (comite, nombre_vocero, cedula_vocero, telefono, correo)
                VALUES (?, ?, ?, ?, ?)
            """,
          vocerias_iniciales,
      )

    cursor.execute("""
            CREATE TABLE IF NOT EXISTS configuracion_campos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_campo TEXT UNIQUE,
                tipo_campo TEXT,
                opciones_json TEXT DEFAULT '[]'
            )
        """)

    conn.commit()


init_db()


# -----------------------------------------------------------------------------
# 3. LÓGICA DE NEGOCIO Y OPERACIONES DE DATOS
# -----------------------------------------------------------------------------
def cargar_configuracion_comunidad():
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nombre_comunidad, nombre_consejo, periodo, vencimiento FROM"
        " config_comunidad LIMIT 1"
    )
    res = cursor.fetchone()
    if res:
      return {
          "nombre_comunidad": res[0],
          "nombre_consejo": res[1],
          "periodo": res[2],
          "vencimiento": res[3],
      }
    return {
        "nombre_comunidad": "Comunidad",
        "nombre_consejo": "Consejo Comunal",
        "periodo": "",
        "vencimiento": "",
    }


def guardar_configuracion_comunidad(
    nombre_comunidad, nombre_consejo, periodo, vencimiento
):
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM config_comunidad")
    cursor.execute(
        """
            INSERT INTO config_comunidad (nombre_comunidad, nombre_consejo, periodo, vencimiento)
            VALUES (?, ?, ?, ?)
        """,
        (nombre_comunidad, nombre_consejo, periodo, vencimiento),
    )
    conn.commit()


def cargar_configuracion_campos():
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT clave_campo, etiqueta, tipo_control, opciones_json FROM"
        " configuracion_estilo_campos"
    )
    filas = cursor.fetchall()

  config = {}
  for f in filas:
    try:
      opciones = json.loads(f[3]) if f[3] else []
    except Exception:
      opciones = []
    config[f[0]] = {"etiqueta": f[1], "tipo_control": f[2], "opciones": opciones}
  return config


def formato_fecha_pantalla(fecha_str):
  try:
    f = parsear_fecha_bd(fecha_str)
    return f.strftime("%d/%m/%Y")
  except Exception:
    return str(fecha_str)


def parsear_fecha_bd(fecha_str):
  fecha_defecto = datetime(1990, 1, 1).date()
  if (
      pd.isna(fecha_str)
      or not fecha_str
      or str(fecha_str).strip() in ["None", "nan", ""]
  ):
    return fecha_defecto
  try:
    if isinstance(fecha_str, (datetime, pd.Timestamp)):
      return fecha_str.date()
    s = str(fecha_str).split()[0].strip()
    if "/" in s:
      f = datetime.strptime(s, "%d/%m/%Y").date()
    else:
      f = datetime.strptime(s, "%Y-%m-%d").date()
    if f.year < 1900:
      return datetime(1900, 1, 1).date()
    return f
  except Exception:
    return fecha_defecto


def calcular_edades_vectorizado(df_col_fecha_nac):
  hoy = pd.Timestamp.now().normalize()
  f_nac = pd.to_datetime(df_col_fecha_nac, errors="coerce")
  anios = (
      hoy.year
      - f_nac.dt.year
      - (
          (hoy.month < f_nac.dt.month)
          | ((hoy.month == f_nac.dt.month) & (hoy.day < f_nac.dt.day))
      )
  )
  return anios.fillna(0).astype(int)


def calcular_tiempo_comunidad_vectorizado(df_col_fecha_llegada):
  hoy = pd.Timestamp.now().normalize()
  f_lleg = pd.to_datetime(df_col_fecha_llegada, errors="coerce")
  anios = (
      hoy.year
      - f_lleg.dt.year
      - (
          (hoy.month < f_lleg.dt.month)
          | ((hoy.month == f_lleg.dt.month) & (hoy.day < f_lleg.dt.day))
      )
  )
  return anios.clip(lower=0).fillna(0).astype(int)


@st.cache_data
def cargar_habitantes():
  with get_connection() as conn:
    df = pd.read_sql_query("SELECT * FROM habitantes", conn)

  df["sexo"] = df["sexo"].fillna("No especificado")
  df["estado_civil"] = df["estado_civil"].fillna("Soltero/a")
  df["conyuge_cedula"] = df["conyuge_cedula"].fillna("").astype(str)
  df["es_padre_madre"] = df["es_padre_madre"].fillna(0).astype(int)
  df["hijos_cedulas"] = df["hijos_cedulas"].fillna("[]")
  df["pertenece_consejo"] = df["pertenece_consejo"].fillna(0).astype(int)
  df["cargo_consejo"] = df["cargo_consejo"].fillna("Ninguno")
  df["condicion_salud"] = df["condicion_salud"].fillna("Ninguna")
  df["detalle_salud"] = df["detalle_salud"].fillna("")
  df["es_jefe_hogar"] = df["es_jefe_hogar"].fillna(0).astype(int)
  df["jefe_hogar_cedula"] = (
      df["jefe_hogar_cedula"].fillna("").astype(str).str.strip()
  )
  df["campos_adicionales"] = df["campos_adicionales"].fillna("{}")

  df["edad_num"] = calcular_edades_vectorizado(df["fecha_nac"])
  df["tiempo_comunidad_num"] = calcular_tiempo_comunidad_vectorizado(
      df["fecha_llegada"]
  )
  return df


def obtener_jefes_hogar():
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT cedula, nombres, apellidos FROM habitantes WHERE es_jefe_hogar ="
        " 1 ORDER BY nombres ASC"
    )
    return cursor.fetchall()


def guardar_habitante(datos):
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        """
            INSERT OR REPLACE INTO habitantes (
                cedula, nombres, apellidos, sexo, fecha_nac, fecha_llegada, 
                direccion, manzana, telefono, estado_civil, conyuge_cedula,
                es_padre_madre, hijos_cedulas, pertenece_consejo, cargo_consejo,
                condicion_salud, detalle_salud, es_jefe_hogar, jefe_hogar_cedula, 
                campos_adicionales
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        datos,
    )
    conn.commit()
  st.cache_data.clear()


def actualizar_habitante_completo(cedula_original, datos_nuevos):
  with get_connection() as conn:
    cursor = conn.cursor()
    nueva_cedula = datos_nuevos[0]

    if cedula_original != nueva_cedula:
      cursor.execute(
          "UPDATE bitacora_documentos SET cedula = ? WHERE cedula = ?",
          (nueva_cedula, cedula_original),
      )
      cursor.execute(
          "UPDATE habitantes SET jefe_hogar_cedula = ? WHERE jefe_hogar_cedula"
          " = ?",
          (nueva_cedula, cedula_original),
      )
      cursor.execute(
          "UPDATE habitantes SET conyuge_cedula = ? WHERE conyuge_cedula = ?",
          (nueva_cedula, cedula_original),
      )
      cursor.execute(
          "DELETE FROM habitantes WHERE cedula = ?", (cedula_original,)
      )

    cursor.execute(
        """
            INSERT OR REPLACE INTO habitantes (
                cedula, nombres, apellidos, sexo, fecha_nac, fecha_llegada, 
                direccion, manzana, telefono, estado_civil, conyuge_cedula,
                es_padre_madre, hijos_cedulas, pertenece_consejo, cargo_consejo,
                condicion_salud, detalle_salud, es_jefe_hogar, jefe_hogar_cedula, 
                campos_adicionales
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        datos_nuevos,
    )
    conn.commit()
  st.cache_data.clear()


def eliminar_habitante(cedula):
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM habitantes WHERE cedula = ?", (cedula,))
    cursor.execute("DELETE FROM bitacora_documentos WHERE cedula = ?", (cedula,))
    cursor.execute(
        "UPDATE habitantes SET jefe_hogar_cedula = '' WHERE jefe_hogar_cedula"
        " = ?",
        (cedula,),
    )
    cursor.execute(
        "UPDATE habitantes SET conyuge_cedula = '' WHERE conyuge_cedula = ?",
        (cedula,),
    )
    conn.commit()
  st.cache_data.clear()


def borrar_todo_el_censo():
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM habitantes")
    cursor.execute("DELETE FROM bitacora_documentos")
    cursor.execute("DELETE FROM bitacora_oficios")
    cursor.execute("DELETE FROM bitacora_eventualidades")
    cursor.execute("DELETE FROM vocerias_comite")
    conn.commit()
  st.cache_data.clear()


def registrar_documento_bitacora(cedula, tipo_doc, descripcion, emitido_por):
  with get_connection() as conn:
    cursor = conn.cursor()
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
            INSERT INTO bitacora_documentos (cedula, tipo_documento, descripcion, fecha_emision, emitido_por)
            VALUES (?, ?, ?, ?, ?)
        """,
        (cedula, tipo_doc, descripcion, fecha_actual, emitido_por),
    )
    conn.commit()


def obtener_bitacora_habitante(cedula):
  with get_connection() as conn:
    df = pd.read_sql_query(
        "SELECT id, tipo_documento, descripcion, fecha_emision, emitido_por FROM"
        " bitacora_documentos WHERE cedula = ? ORDER BY id DESC",
        conn,
        params=(cedula,),
    )
  return df


def registrar_oficio_comunal(
    fecha, vocero, titulo, institucion, descripcion, estatus
):
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        """
            INSERT INTO bitacora_oficios (fecha, vocero_responsable, titulo, institucion_destino, descripcion, estatus)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
        (fecha, vocero, titulo, institucion, descripcion, estatus),
    )
    conn.commit()


def cargar_oficios_comunales():
  with get_connection() as conn:
    return pd.read_sql_query(
        "SELECT * FROM bitacora_oficios ORDER BY id DESC", conn
    )


def eliminar_oficio_comunal(id_oficio):
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bitacora_oficios WHERE id = ?", (id_oficio,))
    conn.commit()


def cargar_vocerias_comite():
  with get_connection() as conn:
    return pd.read_sql_query(
        "SELECT id, comite, nombre_vocero, cedula_vocero, telefono, correo FROM"
        " vocerias_comite ORDER BY id ASC",
        conn,
    )


def guardar_voceria(
    comite, nombre_vocero, cedula_vocero, telefono, correo, id_voceria=None
):
  with get_connection() as conn:
    cursor = conn.cursor()
    if id_voceria:
      cursor.execute(
          """
                UPDATE vocerias_comite 
                SET comite = ?, nombre_vocero = ?, cedula_vocero = ?, telefono = ?, correo = ?
                WHERE id = ?
            """,
          (comite, nombre_vocero, cedula_vocero, telefono, correo, id_voceria),
      )
    else:
      cursor.execute(
          """
                INSERT INTO vocerias_comite (comite, nombre_vocero, cedula_vocero, telefono, correo)
                VALUES (?, ?, ?, ?, ?)
            """,
          (comite, nombre_vocero, cedula_vocero, telefono, correo),
      )
    conn.commit()


def eliminar_voceria(id_voceria):
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vocerias_comite WHERE id = ?", (id_voceria,))
    conn.commit()


def registrar_eventualidad_comunal(
    fecha_inicio,
    hora_inicio,
    fecha_fin,
    hora_fin,
    tipo_evento,
    sector,
    detalles,
    atendido,
    id_evento=None,
):
  with get_connection() as conn:
    cursor = conn.cursor()
    if id_evento:
      cursor.execute(
          """
                UPDATE bitacora_eventualidades 
                SET fecha_inicio = ?, hora_inicio = ?, fecha_fin = ?, hora_fin = ?, 
                    tipo_evento = ?, sector_afectado = ?, detalles = ?, atendido = ?
                WHERE id = ?
            """,
          (
              fecha_inicio,
              hora_inicio,
              fecha_fin,
              hora_fin,
              tipo_evento,
              sector,
              detalles,
              atendido,
              id_evento,
          ),
      )
    else:
      cursor.execute(
          """
                INSERT INTO bitacora_eventualidades (fecha_inicio, hora_inicio, fecha_fin, hora_fin, tipo_evento, sector_afectado, detalles, atendido)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
          (
              fecha_inicio,
              hora_inicio,
              fecha_fin,
              hora_fin,
              tipo_evento,
              sector,
              detalles,
              atendido,
          ),
      )
    conn.commit()


def cargar_eventualidades_comunales():
  with get_connection() as conn:
    return pd.read_sql_query(
        "SELECT * FROM bitacora_eventualidades ORDER BY id DESC", conn
    )


def eliminar_eventualidad(id_evento):
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM bitacora_eventualidades WHERE id = ?", (id_evento,)
    )
    conn.commit()


def cargar_campos_personalizados():
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, nombre_campo, tipo_campo, opciones_json FROM"
        " configuracion_campos"
    )
    filas = cursor.fetchall()

  resultado = []
  for f in filas:
    try:
      opciones = json.loads(f[3]) if f[3] else []
    except Exception:
      opciones = []
    resultado.append(
        {"id": f[0], "nombre": f[1], "tipo": f[2], "opciones": opciones}
    )
  return resultado


def agregar_campo_personalizado(nombre, tipo, opciones_lista):
  with get_connection() as conn:
    cursor = conn.cursor()
    opciones_json = json.dumps(
        [op.strip() for op in opciones_lista if op.strip()], ensure_ascii=False
    )
    try:
      cursor.execute(
          "INSERT INTO configuracion_campos (nombre_campo, tipo_campo,"
          " opciones_json) VALUES (?, ?, ?)",
          (nombre, tipo, opciones_json),
      )
      conn.commit()
    except sqlite3.IntegrityError:
      pass
  st.cache_data.clear()


def verificar_login(username, password):
  pass_hashed = hash_password(password)
  with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, nombre_completo, rol, permisos FROM usuarios WHERE"
        " username = ? AND password = ?",
        (username, pass_hashed),
    )
    user = cursor.fetchone()
  return user


def cargar_usuarios():
  with get_connection() as conn:
    df = pd.read_sql_query(
        "SELECT username, nombre_completo, rol, permisos FROM usuarios", conn
    )
  return df


def guardar_usuario(username, password, nombre_completo, rol, dict_permisos):
  with get_connection() as conn:
    cursor = conn.cursor()
    json_permisos = json.dumps(dict_permisos)
    cursor.execute(
        "SELECT password FROM usuarios WHERE username = ?", (username,)
    )
    f = cursor.fetchone()
    if password.strip():
      pass_final = hash_password(password.strip())
    else:
      pass_final = f[0] if f else hash_password("123456")
    cursor.execute(
        "INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?, ?)",
        (username, pass_final, nombre_completo, rol, json_permisos),
    )
    conn.commit()


def tiene_permiso(clave_permiso):
  if st.session_state.rol_actual == "Master":
    return True
  permisos = st.session_state.get("permisos_usuario", {})
  return permisos.get(clave_permiso, False)


def renderizar_campo_dinamico(key_campo, cfg_dict, key_suffix=""):
  cfg = cfg_dict.get(
      key_campo,
      {"etiqueta": key_campo, "tipo_control": "texto", "opciones": []},
  )
  etiqueta = cfg["etiqueta"]
  tipo = cfg["tipo_control"]
  opciones = cfg["opciones"]
  key_widget = f"{key_campo}_{key_suffix}"

  if key_widget not in st.session_state:
    st.session_state[key_widget] = (
        opciones[0] if (tipo == "desplegable" and opciones) else ""
    )

  if tipo == "desplegable" and opciones:
    return st.selectbox(f"{etiqueta}:", opciones, key=key_widget)
  else:
    return st.text_input(f"{etiqueta}:", key=key_widget)


# -----------------------------------------------------------------------------
# 4. CONTROL DE SESIÓN Y LOGIN
# -----------------------------------------------------------------------------
if "autenticado" not in st.session_state:
  st.session_state.autenticado = False
  st.session_state.usuario_actual = None
  st.session_state.rol_actual = None
  st.session_state.permisos_usuario = {}

if not st.session_state.autenticado:
  st.markdown(
      "<h1 style='text-align: center;'>🔒 Control de Acceso - Censo"
      " Comunitario</h1>",
      unsafe_allow_html=True,
  )

  _, col_center, _ = st.columns([1, 2, 1])
  with col_center:
    usuario = st.text_input("Usuario")
    clave = st.text_input("Contraseña", type="password")
    btn_login = st.button(
        "Ingresar al Sistema", use_container_width=True, type="primary"
    )

    if btn_login:
      user_data = verificar_login(usuario, clave)
      if user_data:
        st.session_state.autenticado = True
        st.session_state.username = user_data[0]
        st.session_state.usuario_actual = user_data[1]
        st.session_state.rol_actual = user_data[2]
        try:
          st.session_state.permisos_usuario = json.loads(user_data[3])
        except Exception:
          st.session_state.permisos_usuario = {}
        st.success(f"¡Bienvenido {user_data[1]}!")
        st.rerun()
      else:
        st.error("❌ Credenciales incorrectas.")
  st.stop()

# -----------------------------------------------------------------------------
# 5. CARGA DE CONFIGURACIÓN Y BARRA LATERAL
# -----------------------------------------------------------------------------
cfg_campos = cargar_configuracion_campos()
cfg_comunidad = cargar_configuracion_comunidad()

with st.sidebar:
  st.title("🏡 Datos Comunidad")
  st.write(f"**Comunidad:** {cfg_comunidad['nombre_comunidad']}")
  st.write(f"**Consejo:** {cfg_comunidad['nombre_consejo']}")
  st.write(f"**Período:** {cfg_comunidad['periodo']}")
  st.write(f"**Vencimiento:** {cfg_comunidad['vencimiento']}")

  st.markdown("---")
  st.title("👤 Perfil de Usuario")
  st.write(f"**Usuario:** {st.session_state.usuario_actual}")
  st.write(f"**Rol:** `{st.session_state.rol_actual}`")

  if st.button("🚪 Cerrar Sesión", use_container_width=True):
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None
    st.session_state.rol_actual = None
    st.session_state.permisos_usuario = {}
    st.rerun()

  st.markdown("---")
  st.caption("Sistema de Censo Comunitario v8.5")

# -----------------------------------------------------------------------------
# 6. NAVEGACIÓN Y PESTAÑAS DINÁMICAS
# -----------------------------------------------------------------------------
st.title(f"🏡 {cfg_comunidad['nombre_comunidad']} - Censo Digital")

pestañas = []
if tiene_permiso("ver_censo"):
  pestañas.append("📊 Consultar y Filtros")
if tiene_permiso("registrar_habitantes"):
  pestañas.append("📝 Registrar Habitante")
if tiene_permiso("gestion_bitacora"):
  pestañas.append("📜 Bitácora de Documentos")
if tiene_permiso("bitacora_comunal"):
  pestañas.append("📢 Bitácora Comunal y Oficios")
if tiene_permiso("ver_estadisticas"):
  pestañas.append("📈 Estadísticas")
if tiene_permiso("personalizar_etiquetas"):
  pestañas.append("✏️ Configurar Comunidad & Formulario")
if st.session_state.rol_actual == "Master":
  pestañas.append("👥 Usuarios y Permisos")
if tiene_permiso("respaldos_importacion") or st.session_state.rol_actual == "Master":
  pestañas.append("💾 Respaldos y Borrado")

if not pestañas:
  st.warning(
      "⚠️ No tienes permisos asignados para ver módulos en la aplicación."
  )
  st.stop()

tabs = st.tabs(pestañas)

# -----------------------------------------------------------------------------
# TAB: CONSULTAR Y FILTROS
# -----------------------------------------------------------------------------
if "📊 Consultar y Filtros" in pestañas:
  with tabs[pestañas.index("📊 Consultar y Filtros")]:
    st.subheader(
        "📊 Búsqueda Global, Filtros electorales y Consulta de Grupo Familiar"
    )
    df = cargar_habitantes()

    if not df.empty:
      col_search1, col_search2, col_search3 = st.columns([2, 2, 1])
      with col_search1:
        busqueda = st.text_input(
            "🔍 Buscar por texto:",
            placeholder="Cédula, Nombres, Dirección, etc...",
        )

      with col_search2:
        jefes_lista = obtener_jefes_hogar()
        opciones_jefes = [("TODOS", "👨‍👩‍👧‍👦 -- Ver Todos los Grupos --")] + [
            (j[0], f"🏡 {j[1]} {j[2]} (C.I: {j[0]})") for j in jefes_lista
        ]

        jefe_filtro_sel = st.selectbox(
            "👨‍👩‍👧‍👦 Filtrar por Grupo Familiar (Jefe de Hogar):",
            [op[0] for op in opciones_jefes],
            format_func=lambda code: dict(opciones_jefes).get(code, code),
        )

      with col_search3:
        vista_modo = st.radio(
            "Modo de vista:", ["Tarjetas Visuales", "Tabla Resumida"], horizontal=True
        )

      with st.expander(
          "🗳️ Filtros Avanzados y Rango de Edad (Padrón Electoral)", expanded=False
      ):
        col_ed1, col_ed2, col_ed3 = st.columns(3)
        with col_ed1:
          activar_filtro_edad = st.checkbox(
              "Activar filtro por Rango de Edad / Electoral", value=False
          )
        with col_ed2:
          edad_min = st.number_input(
              "Edad mínima (años):", min_value=0, max_value=120, value=15
          )
        with col_ed3:
          edad_max = st.number_input(
              "Edad máxima (años):", min_value=0, max_value=120, value=120
          )

      df_filtrado = df.copy()
      if busqueda.strip():
        df_filtrado = df_filtrado[
            df_filtrado.apply(
                lambda row: row.astype(str)
                .str.contains(busqueda, case=False)
                .any(),
                axis=1,
            )
        ]

      if jefe_filtro_sel != "TODOS":
        df_filtrado = df_filtrado[
            (df_filtrado["cedula"] == jefe_filtro_sel)
            | (df_filtrado["jefe_hogar_cedula"] == jefe_filtro_sel)
        ]

      if activar_filtro_edad:
        df_filtrado = df_filtrado[
            (df_filtrado["edad_num"] >= edad_min)
            & (df_filtrado["edad_num"] <= edad_max)
        ]

      st.caption(
          f"Mostrando {len(df_filtrado)} registro(s) encontrado(s) con los"
          " filtros actuales."
      )

      if not df_filtrado.empty:
        col_dl1, col_dl2, _ = st.columns([1, 1, 2])
        with col_dl1:
          csv_data = df_filtrado.to_csv(index=False, sep=";", encoding="utf-8-sig")
          st.download_button(
              label="📥 Descargar Encontrados / Padrón (CSV)",
              data=csv_data,
              file_name=(
                  "padron_electoral_censo_"
                  f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
              ),
              mime="text/csv",
              use_container_width=True,
          )
        with col_dl2:
          buffer_excel = io.BytesIO()
          with pd.ExcelWriter(buffer_excel, engine="openpyxl") as writer:
            df_filtrado.to_excel(writer, index=False, sheet_name="PadronElectoral")
          st.download_button(
              label="📊 Descargar Encontrados / Padrón (Excel)",
              data=buffer_excel.getvalue(),
              file_name=(
                  "padron_electoral_censo_"
                  f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
              ),
              mime=(
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              ),
              use_container_width=True,
          )
        st.markdown("---")

      if vista_modo == "Tarjetas Visuales":
        for idx, hab in df_filtrado.iterrows():
          cedula_curr = hab["cedula"]
          nombre_completo = f"{hab['nombres']} {hab['apellidos']}"
          es_jefe_flag = hab["es_jefe_hogar"] == 1
          rol_familiar = (
              "👑 JEFE DE HOGAR" if es_jefe_flag else "👨‍👩‍👧‍👦 Cargas / Familiar"
          )
          consejo_badge = (
              f" | 🛡️ {hab['cargo_consejo']}"
              if hab["pertenece_consejo"] == 1
              else ""
          )

          cargas_asociadas = (
              df[df["jefe_hogar_cedula"] == cedula_curr]
              if es_jefe_flag
              else pd.DataFrame()
          )
          num_cargas = len(cargas_asociadas)
          badge_cargas = (
              f" | 👨‍👩‍👧‍👦 {num_cargas} Familiar(es) a cargo"
              if es_jefe_flag
              else ""
          )

          with st.expander(
              f"👤 **{nombre_completo}** (`{rol_familiar}`) — C.I:`{cedula_curr}` |"
              f" Manzana: {hab['manzana']}{consejo_badge}{badge_cargas}",
              expanded=bool(busqueda.strip() or jefe_filtro_sel != "TODOS"),
          ):
            kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
            kpi1.metric("🎂 Edad", f"{hab['edad_num']} años")
            kpi2.metric("🏠 Tiempo Comunidad", f"{hab['tiempo_comunidad_num']} años")
            kpi3.metric("👫 Sexo", hab["sexo"])
            kpi4.metric("💍 Estado Civil", hab["estado_civil"])
            kpi5.metric("🏘️ Manzana / Sector", hab["manzana"])

            st.markdown("---")

            col_info1, col_info2 = st.columns(2)
            with col_info1:
              st.markdown("##### 📌 Datos Personales y Familiares")
              st.write(f"**Condición Familiar:** {rol_familiar}")
              if not es_jefe_flag and hab["jefe_hogar_cedula"]:
                match_jefe = df[df["cedula"] == hab["jefe_hogar_cedula"]]
                if not match_jefe.empty:
                  j_nom = (
                      f"{match_jefe.iloc[0]['nombres']}"
                      f" {match_jefe.iloc[0]['apellidos']}"
                  )
                  st.write(
                      f"**Vínculo con Jefe de Hogar:** {j_nom}"
                      f" (`{hab['jefe_hogar_cedula']}`)"
                  )
                else:
                  st.write(f"**Jefe de Hogar (C.I.):** {hab['jefe_hogar_cedula']}")

              if hab["estado_civil"] in ["Casado/a", "Concubino/a"] and hab[
                  "conyuge_cedula"
              ]:
                match_c = df[df["cedula"] == hab["conyuge_cedula"]]
                if not match_c.empty:
                  c_nom = (
                      f"{match_c.iloc[0]['nombres']}"
                      f" {match_c.iloc[0]['apellidos']}"
                  )
                  st.write(
                      f"**Cónyuge / Pareja:** {c_nom} (`{hab['conyuge_cedula']}`)"
                  )
                else:
                  st.write(
                      f"**Cónyuge (C.I.):** {hab['conyuge_cedula']}"
                  )

              if hab["es_padre_madre"] == 1:
                try:
                  hijos_list = json.loads(hab["hijos_cedulas"])
                  if hijos_list:
                    nombres_hijos = []
                    for h_ci in hijos_list:
                      m_h = df[df["cedula"] == h_ci]
                      if not m_h.empty:
                        nombres_hijos.append(
                            f"{m_h.iloc[0]['nombres']}"
                            f" {m_h.iloc[0]['apellidos']} (`{h_ci}`)"
                        )
                      else:
                        nombres_hijos.append(f"C.I: {h_ci}")
                    st.write(
                        "**Hijos/as Registrados:** "
                        + ", ".join(nombres_hijos)
                    )
                except Exception:
                  pass

              if hab["pertenece_consejo"] == 1:
                st.write(
                    "**Consejo Comunal:** ✅ Sí participa | **Cargo:**"
                    f" `{hab['cargo_consejo']}`"
                )
              else:
                st.write("**Consejo Comunal:** No participa activamente")

              st.write(
                  "**Fecha de Nacimiento:**"
                  f" {formato_fecha_pantalla(hab['fecha_nac'])}"
              )
              st.write(
                  "**Fecha de Llegada:**"
                  f" {formato_fecha_pantalla(hab['fecha_llegada'])}"
              )
              st.write(f"**Dirección Detallada:** {hab['direccion']}")

            with col_info2:
              st.markdown("##### ⚕️ Salud y Campos Personalizados")
              st.write(f"**Condición de Salud:** {hab['condicion_salud']}")
              if hab["detalle_salud"]:
                st.write(f"**Detalle Salud:** {hab['detalle_salud']}")

              try:
                extras = json.loads(hab["campos_adicionales"])
                if extras:
                  st.markdown("**Campos Personalizados:**")
                  for k_ext, v_ext in extras.items():
                    st.write(f"- *{k_ext}:* {v_ext}")
              except Exception:
                pass

            if es_jefe_flag:
              st.markdown("---")
              st.markdown(
                  f"##### 👨‍👩‍👧‍👦 Cargas / Familiares Vinculados a {nombre_completo}"
                  f" ({num_cargas})"
              )
              if not cargas_asociadas.empty:
                df_cargas_show = cargas_asociadas.copy()
                df_cargas_show["Edad"] = df_cargas_show["edad_num"]
                df_cargas_show["Fecha Nac."] = df_cargas_show[
                    "fecha_nac"
                ].apply(formato_fecha_pantalla)
                df_cargas_show["Nombre Completo"] = (
                    df_cargas_show["nombres"] + " " + df_cargas_show["apellidos"]
                )

                cols_cargas = [
                    "cedula",
                    "Nombre Completo",
                    "sexo",
                    "Edad",
                    "telefono",
                    "condicion_salud",
                ]
                st.dataframe(
                    df_cargas_show[cols_cargas].rename(
                        columns={
                            "cedula": "Cédula",
                            "sexo": "Sexo",
                            "telefono": "Teléfono",
                            "condicion_salud": "Salud",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
              else:
                st.info(
                    "ℹ️ No hay cargas familiares registradas bajo este Jefe de"
                    " Hogar."
                )

            st.markdown("---")
            btn_col1, btn_col2, _ = st.columns([1, 1, 3])

            if tiene_permiso("editar_habitantes"):
              with btn_col1:
                if st.button(
                    "✏️ Editar Datos",
                    key=f"btn_edit_{cedula_curr}",
                    use_container_width=True,
                ):
                  st.session_state[f"modo_edit_{cedula_curr}"] = not st.session_state.get(
                      f"modo_edit_{cedula_curr}", False
                  )

            if tiene_permiso("eliminar_habitantes"):
              with btn_col2:
                if st.button(
                    "🗑️ Eliminar Registro",
                    key=f"btn_del_{cedula_curr}",
                    type="primary",
                    use_container_width=True,
                ):
                  eliminar_habitante(cedula_curr)
                  st.success(f"Habitante con cédula {cedula_curr} eliminado.")
                  st.rerun()

            if st.session_state.get(f"modo_edit_{cedula_curr}", False):
              st.markdown("---")
              st.subheader(f"🛠️ Editar Datos de {nombre_completo}")

              col_ins1, col_ins2 = st.columns(2)
              with col_ins1:
                e_ced = st.text_input(
                    "Cédula:", value=hab["cedula"], key=f"e_ced_{cedula_curr}"
                )
                e_nom = st.text_input(
                    "Nombres:", value=hab["nombres"], key=f"e_nom_{cedula_curr}"
                )
                e_ape = st.text_input(
                    "Apellidos:",
                    value=hab["apellidos"],
                    key=f"e_ape_{cedula_curr}",
                )
                e_tel = st.text_input(
                    "Teléfono:", value=hab["telefono"], key=f"e_tel_{cedula_curr}"
                )
              with col_ins2:
                e_sex = st.selectbox(
                    "Sexo:",
                    ["Femenino", "Masculino", "Otro"],
                    index=(
                        0
                        if hab["sexo"] == "Femenino"
                        else (1 if hab["sexo"] == "Masculino" else 2)
                    ),
                    key=f"e_sex_{cedula_curr}",
                )
                e_fn = st.date_input(
                    "Fecha Nacimiento:",
                    value=parsear_fecha_bd(hab["fecha_nac"]),
                    min_value=datetime(1900, 1, 1).date(),
                    max_value=datetime.now().date(),
                    format="DD/MM/YYYY",
                    key=f"e_fn_{cedula_curr}",
                )
                e_fl = st.date_input(
                    "Fecha Llegada:",
                    value=parsear_fecha_bd(hab["fecha_llegada"]),
                    min_value=datetime(1900, 1, 1).date(),
                    max_value=datetime.now().date(),
                    format="DD/MM/YYYY",
                    key=f"e_fl_{cedula_curr}",
                )

              e_ec = st.selectbox(
                  "Estado Civil:",
                  [
                      "Soltero/a",
                      "Casado/a",
                      "Concubino/a",
                      "Divorciado/a",
                      "Viudo/a",
                  ],
                  index=(
                      0
                      if hab["estado_civil"] == "Soltero/a"
                      else (
                          1
                          if hab["estado_civil"] == "Casado/a"
                          else (
                              2
                              if hab["estado_civil"] == "Concubino/a"
                              else (
                                  3
                                  if hab["estado_civil"] == "Divorciado/a"
                                  else 4
                              )
                          )
                      )
                  ),
                  key=f"e_ec_{cedula_curr}",
              )

              e_conyuge = ""
              if e_ec in ["Casado/a", "Concubino/a"]:
                e_conyuge = st.text_input(
                    "Cédula de Cónyuge / Pareja:",
                    value=hab["conyuge_cedula"],
                    key=f"e_conyuge_{cedula_curr}",
                )

              e_es_padre = st.checkbox(
                  "¿Es Padre o Madre?",
                  value=bool(hab["es_padre_madre"]),
                  key=f"e_esp_{cedula_curr}",
              )
              e_hijos = hab["hijos_cedulas"]
              if e_es_padre:
                try:
                  list_h_actual = json.loads(hab["hijos_cedulas"])
                except Exception:
                  list_h_actual = []
                sel_hijos_edit = st.multiselect(
                    "Seleccionar Hijos/as registrados:",
                    options=df["cedula"].tolist(),
                    default=[
                        h for h in list_h_actual if h in df["cedula"].tolist()
                    ],
                    format_func=lambda c: (
                        f"{c} -"
                        f" {df[df['cedula'] == c]['nombres'].values[0]}"
                    ),
                    key=f"e_hijos_sel_{cedula_curr}",
                )
                e_hijos = json.dumps(sel_hijos_edit)

              e_pert_cc = st.checkbox(
                  "¿Pertenece al Consejo Comunal?",
                  value=bool(hab["pertenece_consejo"]),
                  key=f"e_pert_{cedula_curr}",
              )
              e_cargo_cc = "Ninguno"
              if e_pert_cc:
                cargos_cc_lista = [
                    "Vocero de Mesa Técnica de Agua",
                    "Vocero de Finanzas",
                    "Vocero de Seguridad",
                    "Vocero de Educación y Cultura",
                    "Vocero de Alimentación",
                    "Vocero de Salud",
                    "Vocero de Hábitat y Vivienda",
                    "Vocero Principal",
                    "Otro Vocero / Comité",
                ]
                idx_c = (
                    cargos_cc_lista.index(hab["cargo_consejo"])
                    if hab["cargo_consejo"] in cargos_cc_lista
                    else 0
                )
                e_cargo_cc = st.selectbox(
                    "Cargo / Comité en Consejo Comunal:",
                    cargos_cc_lista,
                    index=idx_c,
                    key=f"e_cargo_{cedula_curr}",
                )

              e_es_jefe = st.checkbox(
                  "¿Es Jefe de Hogar?",
                  value=bool(hab["es_jefe_hogar"]),
                  key=f"e_es_jefe_{cedula_curr}",
              )
              e_jefe_ced = ""
              if not e_es_jefe:
                jefes_disp = obtener_jefes_hogar()
                ops_jefes_edit = [("", "-- Seleccionar Jefe de Hogar --")] + [
                    (j[0], f"{j[1]} {j[2]} ({j[0]})")
                    for j in jefes_disp
                    if j[0] != cedula_curr
                ]
                idx_jefe = 0
                for i_j, o_j in enumerate(ops_jefes_edit):
                  if str(o_j[0]).strip() == str(hab["jefe_hogar_cedula"]).strip():
                    idx_jefe = i_j
                    break
                sel_jefe_edit = st.selectbox(
                    "Vincular a Jefe de Hogar:",
                    [o[0] for o in ops_jefes_edit],
                    index=idx_jefe,
                    format_func=lambda c: dict(ops_jefes_edit).get(c, c),
                    key=f"e_jefe_sel_{cedula_curr}",
                )
                e_jefe_ced = sel_jefe_edit

              e_man = st.text_input(
                  "Manzana:", value=hab["manzana"], key=f"e_man_{cedula_curr}"
              )
              e_dir = st.text_area(
                  "Dirección:", value=hab["direccion"], key=f"e_dir_{cedula_curr}"
              )
              e_sal = st.text_input(
                  "Condición Salud:",
                  value=hab["condicion_salud"],
                  key=f"e_sal_{cedula_curr}",
              )
              e_detsal = st.text_input(
                  "Detalle Salud:",
                  value=hab["detalle_salud"],
                  key=f"e_detsal_{cedula_curr}",
              )

              if st.button(
                  "💾 Guardar Cambios",
                  key=f"btn_save_insitu_{cedula_curr}",
                  type="primary",
                  use_container_width=True,
              ):
                datos_actualizados = (
                    str(e_ced).strip(),
                    str(e_nom).strip(),
                    str(e_ape).strip(),
                    e_sex,
                    e_fn.strftime("%Y-%m-%d"),
                    e_fl.strftime("%Y-%m-%d"),
                    str(e_dir).strip(),
                    str(e_man).strip(),
                    str(e_tel).strip(),
                    str(e_ec).strip(),
                    str(e_conyuge).strip(),
                    1 if e_es_padre else 0,
                    str(e_hijos),
                    1 if e_pert_cc else 0,
                    str(e_cargo_cc),
                    str(e_sal).strip(),
                    str(e_detsal).strip(),
                    1 if e_es_jefe else 0,
                    str(e_jefe_ced).strip(),
                    hab["campos_adicionales"],
                )
                actualizar_habitante_completo(cedula_curr, datos_actualizados)
                st.session_state[f"modo_edit_{cedula_curr}"] = False
                st.success("✅ Cambios guardados correctamente.")
                st.rerun()

      else:
        df_tabla = df_filtrado.copy()
        df_tabla["Edad"] = df_tabla["edad_num"]
        df_tabla["Rol Familiar"] = df_tabla["es_jefe_hogar"].apply(
            lambda x: "Jefe de Hogar" if x == 1 else "Familiar/Carga"
        )
        df_tabla["Participa CC"] = df_tabla["pertenece_consejo"].apply(
            lambda x: "Sí" if x == 1 else "No"
        )
        df_tabla["fecha_nac"] = df_tabla["fecha_nac"].apply(
            formato_fecha_pantalla
        )
        df_tabla["fecha_llegada"] = df_tabla["fecha_llegada"].apply(
            formato_fecha_pantalla
        )

        cols_mostrar = [
            "cedula",
            "nombres",
            "apellidos",
            "Rol Familiar",
            "estado_civil",
            "Participa CC",
            "cargo_consejo",
            "sexo",
            "Edad",
            "manzana",
            "telefono",
            "condicion_salud",
        ]
        st.dataframe(
            df_tabla[cols_mostrar].rename(
                columns={
                    "estado_civil": "Estado Civil",
                    "cargo_consejo": "Cargo Consejo Comunal",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
      st.info("No hay registros cargados en la base de datos.")

# -----------------------------------------------------------------------------
# TAB: BITÁCORA DE DOCUMENTOS
# -----------------------------------------------------------------------------
if "📜 Bitácora de Documentos" in pestañas:
  with tabs[pestañas.index("📜 Bitácora de Documentos")]:
    st.subheader(
        "📜 Registro y Bitácora de Emitidos (Cartas y Constancias)"
    )
    df_bit = cargar_habitantes()

    if not df_bit.empty:
      col_b1, col_b2 = st.columns([1, 2])

      with col_b1:
        st.markdown("### ✍️ Emitir / Registrar Documento")
        habitante_sel = st.selectbox(
            "Seleccione Habitante:",
            options=df_bit["cedula"].tolist(),
            format_func=lambda c: (
                f"{c} -"
                f" {df_bit[df_bit['cedula'] == c]['nombres'].values[0]}"
                f" {df_bit[df_bit['cedula'] == c]['apellidos'].values[0]}"
            ),
        )

        tipo_doc = st.selectbox(
            "Tipo de Documento:",
            [
                "Constancia de Residencia",
                "Carta de Buena Conducta",
                "Constancia de Soltería",
                "Permiso de Mudanza",
                "Aval Comunitario",
                "Otro Documento",
            ],
            key="bit_tipo_doc",
        )
        desc_doc = st.text_area(
            "Observaciones / Detalles del Trámite:", key="bit_desc_doc"
        )
        btn_bit = st.button(
            "📜 Registrar en Bitácora", type="primary", use_container_width=True
        )

        if btn_bit:
          registrar_documento_bitacora(
              habitante_sel,
              tipo_doc,
              desc_doc.strip(),
              st.session_state.usuario_actual,
          )
          st.success("✅ Trámite registrado en la bitácora del habitante.")
          st.rerun()

      with col_b2:
        st.markdown(
            "### 📑 Historial de Trámites del Habitante"
            f" (`Cédula: {habitante_sel}`)"
        )
        df_historial = obtener_bitacora_habitante(habitante_sel)

        if not df_historial.empty:
          df_historial["fecha_emision"] = df_historial["fecha_emision"].apply(
              formato_fecha_pantalla
          )
          df_historial.columns = [
              "ID",
              "Documento",
              "Detalles",
              "Fecha Emisión",
              "Emitido Por",
          ]
          st.dataframe(df_historial, use_container_width=True, hide_index=True)
        else:
          st.info(
              "No se han emitido constancias ni documentos previos para este"
              " habitante."
          )
    else:
      st.info("Registre habitantes para utilizar el módulo de bitácora.")

# -----------------------------------------------------------------------------
# TAB: BITÁCORA COMUNAL Y OFICIOS
# -----------------------------------------------------------------------------
if "📢 Bitácora Comunal y Oficios" in pestañas:
  with tabs[pestañas.index("📢 Bitácora Comunal y Oficios")]:
    st.subheader(
        "📢 Bitácora Comunal: Oficios Institucionales, Vocerías y Eventualidades"
    )

    sub_tab1, sub_tab2, sub_tab3 = st.tabs([
        "📋 Oficios y Trámites",
        "⚠️ Eventualidades y Servicios Públicos",
        "👥 Gestión de Vocerías y Comités",
    ])

    with sub_tab1:
      st.markdown("### ✍️ Registro de Oficios de Voceros")
      col_of1, col_of2 = st.columns([1, 1.5])

      with col_of1:
        fecha_oficio = st.date_input(
            "Fecha del Oficio:", value=datetime.now().date(), format="DD/MM/YYYY"
        )
        df_habitantes_local = cargar_habitantes()
        lista_voceros_opciones = ["Otro vocero / Integrante"]
        if not df_habitantes_local.empty:
          df_voceros_filtrados = df_habitantes_local[
              df_habitantes_local["pertenece_consejo"] == 1
          ]
          if not df_voceros_filtrados.empty:
            for _, r_v in df_voceros_filtrados.iterrows():
              lista_voceros_opciones.append(
                  f"{r_v['nombres']} {r_v['apellidos']} ({r_v['cargo_consejo']})"
              )

        vocero_sel = st.selectbox(
            "Vocero Responsable del Oficio:", lista_voceros_opciones
        )
        titulo_oficio = st.text_input(
            "Título o Asunto del Oficio:",
            placeholder="Ej: Solicitud de cisterna de agua, reparación de alumbrado...",
        )
        inst_destino = st.text_input(
            "Institución de Destino:",
            placeholder="Ej: Alcaldía, Hidrológica, Corpoelec...",
        )
        estatus_oficio = st.selectbox(
            "Estatus del Trámite:",
            ["En Trámite", "Entregado / Recibido", "Aprobado", "Finalizado"],
        )
        desc_oficio = st.text_area("Descripción detallada del oficio:")

        if st.button(
            "💾 Registrar Oficio en Bitácora",
            type="primary",
            use_container_width=True,
        ):
          if titulo_oficio.strip():
            registrar_oficio_comunal(
                fecha_oficio.strftime("%Y-%m-%d"),
                vocero_sel,
                titulo_oficio.strip(),
                inst_destino.strip(),
                desc_oficio.strip(),
                estatus_oficio,
            )
            st.success("✅ Oficio registrado exitosamente en la bitácora.")
            st.rerun()
          else:
            st.error("Ingrese el título o asunto del oficio.")

      with col_of2:
        st.markdown("### 📑 Historial de Oficios Emitidos")
        df_oficios = cargar_oficios_comunales()
        if not df_oficios.empty:
          df_oficios_show = df_oficios.copy()
          df_oficios_show["fecha"] = df_oficios_show["fecha"].apply(
              formato_fecha_pantalla
          )
          df_oficios_show.columns = [
              "ID",
              "Fecha",
              "Vocero",
              "Título",
              "Institución",
              "Descripción",
              "Estatus",
          ]
          st.dataframe(
              df_oficios_show[
                  [
                      "ID",
                      "Fecha",
                      "Vocero",
                      "Título",
                      "Institución",
                      "Estatus",
                  ]
              ],
              use_container_width=True,
              hide_index=True,
          )

          id_del_oficio = st.number_input(
              "ID de Oficio a eliminar:", min_value=0, step=1, key="del_of"
          )
          if st.button("🗑️ Eliminar Oficio Seleccionado", key="btn_del_of"):
            if id_del_oficio > 0:
              eliminar_oficio_comunal(int(id_del_oficio))
              st.warning("Oficio eliminado de la bitácora.")
              st.rerun()
        else:
          st.info("No hay oficios registrados todavía.")

    with sub_tab2:
      st.markdown(
          "### ⚠️ Registro y Edición de Eventualidades y Servicios Públicos"
      )
      col_ev1, col_ev2 = st.columns([1, 1.5])

      with col_ev1:
        accion_ev_mode = st.radio(
            "Acción Eventualidad:", ["Registrar Nueva", "Editar Existente"], horizontal=True
        )
        id_evento_edit = None

        if accion_ev_mode == "Editar Existente":
          df_ev_all = cargar_eventualidades_comunales()
          if not df_ev_all.empty:
            sel_ev_id = st.selectbox(
                "Seleccione ID de Evento a Editar:",
                df_ev_all["id"].tolist(),
                format_func=lambda i: f"ID {i}: {df_ev_all[df_ev_all['id'] == i]['tipo_evento'].values[0]} ({df_ev_all[df_ev_all['id'] == i]['sector_afectado'].values[0]})",
            )
            row_ev_sel = df_ev_all[df_ev_all["id"] == sel_ev_id].iloc[0]
            id_evento_edit = row_ev_sel["id"]

            default_f_ini = parsear_fecha_bd(row_ev_sel["fecha_inicio"])
            default_f_fin = parsear_fecha_bd(row_ev_sel["fecha_fin"])
            default_h_ini = (
                row_ev_sel["hora_inicio"]
                if row_ev_sel["hora_inicio"]
                else "08:00"
            )
            default_h_fin = (
                row_ev_sel["hora_fin"] if row_ev_sel["hora_fin"] else "12:00"
            )
            default_tipo = row_ev_sel["tipo_evento"]
            default_sector = row_ev_sel["sector_afectado"]
            default_detalles = row_ev_sel["detalles"]
            default_atendido = bool(row_ev_sel["atendido"])
          else:
            st.info("No hay eventualidades para editar.")
            default_f_ini, default_f_fin = (
                datetime.now().date(),
                datetime.now().date(),
            )
            default_h_ini, default_h_fin = "08:00", "12:00"
            default_tipo, default_sector, default_detalles, default_atendido = (
                "Falla Eléctrica / Apagón",
                "",
                "",
                False,
            )
        else:
          default_f_ini, default_f_fin = (
              datetime.now().date(),
              datetime.now().date(),
          )
          default_h_ini, default_h_fin = "08:00", "12:00"
          default_tipo, default_sector, default_detalles, default_atendido = (
              "Falla Eléctrica / Apagón",
              "",
              "",
              False,
          )

        f_ini = st.date_input(
            "Fecha de Inicio:",
            value=default_f_ini,
            format="DD/MM/YYYY",
            key="ev_f_ini",
        )
        h_ini = st.text_input(
            "Hora de Inicio (Ej: 08:30 AM / 14:00):",
            value=default_h_ini,
            key="ev_h_ini",
        )

        f_fin = st.date_input(
            "Fecha de Fin / Solución:",
            value=default_f_fin,
            format="DD/MM/YYYY",
            key="ev_f_fin",
        )
        h_fin = st.text_input(
            "Hora de Fin / Solución:", value=default_h_fin, key="ev_h_fin"
        )

        tipos_ev_lista = [
            "Falla Eléctrica / Apagón",
            "Llegada de Agua Potable",
            "Falla de Cloacas / Desborde",
            "Bote de Agua Blanca",
            "Falla de Gas Comunal",
            "Alumbrado Público",
            "Otro Servicio Público",
        ]
        idx_t = (
            tipos_ev_lista.index(default_tipo)
            if default_tipo in tipos_ev_lista
            else 0
        )
        tipo_evento = st.selectbox(
            "Tipo de Eventualidad / Servicio:", tipos_ev_lista, index=idx_t
        )

        sector_afectado = st.text_input(
            "Sector / Manzana Afectada:",
            value=default_sector,
            placeholder="Ej: Manzana 3, Calle Principal...",
        )
        detalles_evento = st.text_area(
            "Detalles y Observaciones de la Eventualidad:",
            value=default_detalles,
            placeholder="Ej: Falla en transformador principal...",
        )
        atendido_check = st.checkbox(
            "¿Incidencia / Evento ya Atendido / Solucionado?",
            value=default_atendido,
        )

        btn_txt = (
            "💾 Actualizar Eventualidad"
            if accion_ev_mode == "Editar Existente"
            else "💾 Registrar Eventualidad"
        )
        if st.button(btn_txt, type="primary", use_container_width=True):
          if sector_afectado.strip():
            registrar_eventualidad_comunal(
                f_ini.strftime("%Y-%m-%d"),
                h_ini.strip(),
                f_fin.strftime("%Y-%m-%d"),
                h_fin.strip(),
                tipo_evento,
                sector_afectado.strip(),
                detalles_evento.strip(),
                1 if atendido_check else 0,
                id_evento=id_evento_edit,
            )
            st.success("✅ Eventualidad guardada con éxito.")
            st.rerun()
          else:
            st.error("Ingrese el sector o manzana afectada.")

      with col_ev2:
        st.markdown(
            "### 📑 Historial con Control de Horarios y Estatus"
        )
        df_eventos = cargar_eventualidades_comunales()
        if not df_eventos.empty:
          df_ev_show = df_eventos.copy()
          df_ev_show["Inicio"] = (
              df_ev_show["fecha_inicio"].apply(formato_fecha_pantalla)
              + " "
              + df_ev_show["hora_inicio"]
          )
          df_ev_show["Fin"] = (
              df_ev_show["fecha_fin"].apply(formato_fecha_pantalla)
              + " "
              + df_ev_show["hora_fin"]
          )
          df_ev_show["Estatus"] = df_ev_show["atendido"].apply(
    lambda x: (
        "✅ Solucionado" if x == 1 or x is True or str(x).lower() == "si"
        else "⏳ Pendiente / En Curso"
    )
)

          cols_show_ev = [
              "id",
              "Inicio",
              "Fin",
              "tipo_evento",
              "sector_afectado",
              "Estatus",
          ]
          st.dataframe(
              df_ev_show[cols_show_ev].rename(
                  columns={
                      "id": "ID",
                      "tipo_evento": "Evento",
                      "sector_afectado": "Sector",
                  }
              ),
              use_container_width=True,
          )

          id_del_ev = st.number_input(
              "ID de Eventualidad a eliminar:", min_value=0, step=1, key="num_del_ev"
          )
          if st.button("🗑️ Eliminar Eventualidad Seleccionada"):
            if id_del_ev > 0:
              eliminar_eventualidad(int(id_del_ev))
              st.warning("Eventualidad eliminada de la bitácora.")
              st.rerun()
        else:
          st.info("No hay eventualidades registradas en el sistema.")

    with sub_tab3:
      st.markdown("### 👥 Gestión y Edición de Vocerías y Comités")
      col_v1, col_v2 = st.columns([1, 1.5])

      with col_v1:
        st.markdown("##### ✍️ Agregar o Editar Vocero/Comité")
        accion_voc = st.radio(
            "Acción Vocería:", ["Agregar Nuevo", "Editar Existente"], horizontal=True, key="r_voc"
        )
        id_voc_edit = None

        if accion_voc == "Editar Existente":
          df_voc_all = cargar_vocerias_comite()
          if not df_voc_all.empty:
            sel_v_id = st.selectbox(
                "Seleccione Vocería a Editar:",
                df_voc_all["id"].tolist(),
                format_func=lambda i: f"{df_voc_all[df_voc_all['id'] == i]['comite'].values[0]} - {df_voc_all[df_voc_all['id'] == i]['nombre_vocero'].values[0]}",
            )
            row_v_sel = df_voc_all[df_voc_all["id"] == sel_v_id].iloc[0]
            id_voc_edit = row_v_sel["id"]

            v_comite_val = row_v_sel["comite"]
            v_nom_val = row_v_sel["nombre_vocero"]
            v_ci_val = row_v_sel["cedula_vocero"]
            v_tel_val = row_v_sel["telefono"]
            v_mail_val = row_v_sel["correo"]
          else:
            st.info("No hay vocerías registradas.")
            v_comite_val, v_nom_val, v_ci_val, v_tel_val, v_mail_val = (
                "",
                "",
                "",
                "",
                "",
            )
        else:
          v_comite_val, v_nom_val, v_ci_val, v_tel_val, v_mail_val = (
              "",
              "",
              "",
              "",
              "",
          )

        comite_inp = st.text_input(
            "Nombre del Comité:",
            value=v_comite_val,
            placeholder="Ej: Mesa Técnica de Agua, Salud, Finanzas...",
        )
        vocero_inp = st.text_input(
            "Nombre y Apellido del Vocero:",
            value=v_nom_val,
            placeholder="Nombre completo...",
        )
        ci_voc_inp = st.text_input(
            "Cédula del Vocero:",
            value=v_ci_val,
            placeholder="Cédula de identidad...",
        )
        tel_voc_inp = st.text_input(
            "Teléfono de Contacto:",
            value=v_tel_val,
            placeholder="Ej: 0412-1234567",
        )
        correo_voc_inp = st.text_input(
            "Correo Electrónico (Opcional):",
            value=v_mail_val,
            placeholder="correo@gmail.com",
        )

        btn_voc_lbl = (
            "💾 Actualizar Vocería"
            if accion_voc == "Editar Existente"
            else "💾 Guardar Nueva Vocería"
        )
        if st.button(btn_voc_lbl, type="primary", use_container_width=True):
          if comite_inp.strip() and vocero_inp.strip():
            guardar_voceria(
                comite_inp.strip(),
                vocero_inp.strip(),
                ci_voc_inp.strip(),
                tel_voc_inp.strip(),
                correo_voc_inp.strip(),
                id_voceria=id_voc_edit,
            )
            st.success("✅ Vocería guardada con éxito.")
            st.rerun()
          else:
            st.error("Complete al menos el comité y el nombre del vocero.")

      with col_v2:
        st.markdown("##### 📑 Listado de Vocerías del Consejo Comunal")
        df_voc_list = cargar_vocerias_comite()
        if not df_voc_list.empty:
          st.dataframe(
              df_voc_list.rename(
                  columns={
                      "id": "ID",
                      "comite": "Comité",
                      "nombre_vocero": "Vocero",
                      "cedula_vocero": "Cédula",
                      "telefono": "Teléfono",
                  }
              ),
              use_container_width=True,
              hide_index=True,
          )

          id_del_voc = st.number_input(
              "ID de Vocería a eliminar:", min_value=0, step=1, key="del_voc_id"
          )
          if st.button("🗑️ Eliminar Vocería Seleccionada"):
            if id_del_voc > 0:
              eliminar_voceria(int(id_del_voc))
              st.warning("Vocería eliminada.")
              st.rerun()
        else:
          st.info("No hay vocerías registradas.")

# -----------------------------------------------------------------------------
# TAB: REGISTRAR HABITANTE
# -----------------------------------------------------------------------------
if "📝 Registrar Habitante" in pestañas:
  with tabs[pestañas.index("📝 Registrar Habitante")]:
    st.subheader("📝 Formulario Unificado de Registro de Habitante")

    datos_extra = {}

    st.markdown("### 👤 Datos Personales e Identificación")
    col1, col2 = st.columns(2)
    with col1:
      cedula = renderizar_campo_dinamico("cedula", cfg_campos, key_suffix="reg")
      nombres = renderizar_campo_dinamico("nombres", cfg_campos, key_suffix="reg")
      apellidos = renderizar_campo_dinamico(
          "apellidos", cfg_campos, key_suffix="reg"
      )
      sexo = renderizar_campo_dinamico("sexo", cfg_campos, key_suffix="reg")
    with col2:
      lbl_fn = cfg_campos.get("fecha_nac", {}).get(
          "etiqueta", "Fecha de Nacimiento"
      )
      if "reg_fn_key" not in st.session_state:
        st.session_state["reg_fn_key"] = datetime(1990, 1, 1).date()

      fecha_nac = st.date_input(
          f"{lbl_fn} (DD/MM/YYYY)",
          min_value=datetime(1900, 1, 1).date(),
          max_value=datetime.now().date(),
          format="DD/MM/YYYY",
          key="reg_fn_key",
      )
      telefono = renderizar_campo_dinamico(
          "telefono", cfg_campos, key_suffix="reg"
      )
      estado_civil = renderizar_campo_dinamico(
          "estado_civil", cfg_campos, key_suffix="reg"
      )

    conyuge_cedula = ""
    if estado_civil in ["Casado/a", "Concubino/a"]:
      st.markdown("##### 💍 Vínculo con Cónyuge / Pareja")
      df_hab_actual = cargar_habitantes()
      opciones_conyuge = [("", "-- Seleccionar Cónyuge de la Base de Datos --")]
      if not df_hab_actual.empty:
        for _, rc in df_hab_actual.iterrows():
          opciones_conyuge.append(
              (str(rc["cedula"]).strip(), f"{rc['nombres']} {rc['apellidos']} (C.I: {rc['cedula']})")
          )
      sel_conyuge_reg = st.selectbox(
          "Seleccione o ingrese cónyuge:",
          [op[0] for op in opciones_conyuge],
          format_func=lambda c: dict(opciones_conyuge).get(c, c),
          key="reg_conyuge_sel",
      )
      conyuge_cedula = sel_conyuge_reg

    st.markdown("---")
    st.markdown("### 👨‍👩‍👧‍👦 Núcleo Familiar, Padres e Hijos")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
      if "reg_es_jefe_key" not in st.session_state:
        st.session_state["reg_es_jefe_key"] = False
      es_jefe = st.checkbox(
          "¿Es el Jefe de Hogar?", key="reg_es_jefe_key"
      )

      if "reg_es_padre_key" not in st.session_state:
        st.session_state["reg_es_padre_key"] = False
      es_padre_madre = st.checkbox(
          "¿Es Padre o Madre (asociar hijos/as)?", key="reg_es_padre_key"
      )

    hijos_cedulas_json = "[]"
    with col_f2:
      if not es_jefe:
        jefes_existentes = obtener_jefes_hogar()
        if jefes_existentes:
          opciones_jefes = [("", "-- Seleccionar Jefe de Hogar --")] + [
              (str(j[0]).strip(), f"{j[1]} {j[2]} ({j[0]})")
              for j in jefes_existentes
          ]
          if "reg_sel_jefe_key" not in st.session_state:
            st.session_state["reg_sel_jefe_key"] = ""
          sel_jefe = st.selectbox(
              "Vincular a Jefe de Hogar:",
              options=[op[0] for op in opciones_jefes],
              format_func=lambda code: dict(opciones_jefes).get(code, code),
              key="reg_sel_jefe_key",
          )
          jefe_seleccionado_cedula = sel_jefe
        else:
          jefe_seleccionado_cedula = ""
      else:
        jefe_seleccionado_cedula = ""

      if es_padre_madre:
        df_hab_hijos = cargar_habitantes()
        lista_todos_hab = (
            df_hab_hijos["cedula"].tolist() if not df_hab_hijos.empty else []
        )
        hijos_sel = st.multiselect(
            "Seleccionar Hijos / Niños asociados:",
            options=lista_todos_hab,
            format_func=lambda c: (
                f"{c} -"
                f" {df_hab_hijos[df_hab_hijos['cedula'] == c]['nombres'].values[0]}"
                f" {df_hab_hijos[df_hab_hijos['cedula'] == c]['apellidos'].values[0]}"
            ),
            key="reg_hijos_multiselect",
        )
        hijos_cedulas_json = json.dumps(hijos_sel)

    st.markdown("---")
    st.markdown("### 🛡️ Consejo Comunal y Participación")
    col_cc1, col_cc2 = st.columns(2)
    with col_cc1:
      if "reg_pert_cc" not in st.session_state:
        st.session_state["reg_pert_cc"] = False
      pertenece_consejo = st.checkbox(
          "¿Pertenece al Consejo Comunal?", key="reg_pert_cc"
      )
    with col_cc2:
      cargo_consejo = "Ninguno"
      if pertenece_consejo:
        lista_cargos_cc = [
            "Vocero de Mesa Técnica de Agua",
            "Vocero de Finanzas",
            "Vocero de Seguridad",
            "Vocero de Educación y Cultura",
            "Vocero de Alimentación",
            "Vocero de Salud",
            "Vocero de Hábitat y Vivienda",
            "Vocero Principal",
            "Otro Vocero / Comité",
        ]
        cargo_consejo = st.selectbox(
            "Seleccione Cargo / Comité:", lista_cargos_cc, key="reg_cargo_cc_sel"
        )

    st.markdown("---")
    st.markdown("### 🏠 Ubicación y Vivienda")
    col3, col4 = st.columns(2)
    with col3:
      manzana = renderizar_campo_dinamico("manzana", cfg_campos, key_suffix="reg")
      lbl_fl = cfg_campos.get("fecha_llegada", {}).get(
          "etiqueta", "Fecha de Llegada"
      )
      if "reg_fl_key" not in st.session_state:
        st.session_state["reg_fl_key"] = datetime(2010, 1, 1).date()
      fecha_llegada = st.date_input(
          f"{lbl_fl} (DD/MM/YYYY)",
          min_value=datetime(1900, 1, 1).date(),
          max_value=datetime.now().date(),
          format="DD/MM/YYYY",
          key="reg_fl_key",
      )
    with col4:
      direccion = renderizar_campo_dinamico(
          "direccion", cfg_campos, key_suffix="reg"
      )

    st.markdown("---")
    st.markdown("### ⚕️ Salud y Vulnerabilidad")
    col5, col6 = st.columns(2)
    with col5:
      condicion_salud = renderizar_campo_dinamico(
          "condicion_salud", cfg_campos, key_suffix="reg"
      )
    with col6:
      detalle_salud = renderizar_campo_dinamico(
          "detalle_salud", cfg_campos, key_suffix="reg"
      )

    st.markdown("---")
    campos_config = cargar_campos_personalizados()
    if campos_config:
      st.markdown("### ➕ Campos Personalizados Agregados")
      col_c1, col_c2 = st.columns(2)
      for idx, c_item in enumerate(campos_config):
        nom_c = c_item["nombre"]
        tipo_c = c_item["tipo"]
        ops_c = c_item["opciones"]
        key_cust = f"reg_cust_{c_item['id']}"

        if key_cust not in st.session_state:
          st.session_state[key_cust] = (
              ops_c[0] if (tipo_c == "Desplegable" and ops_c) else ""
          )

        target_col = col_c1 if idx % 2 == 0 else col_c2
        with target_col:
          if tipo_c == "Desplegable" and ops_c:
            datos_extra[nom_c] = st.selectbox(
                f"{nom_c}:", options=ops_c, key=key_cust
            )
          else:
            datos_extra[nom_c] = st.text_input(f"{nom_c}:", key=key_cust)

    st.markdown("---")
    guardar = st.button(
        "💾 Guardar Registro de Habitante",
        type="primary",
        use_container_width=True,
    )

    if guardar:
      if str(nombres).strip() and str(apellidos).strip() and str(cedula).strip():
        json_extra = json.dumps(datos_extra, ensure_ascii=False)
        datos = (
            str(cedula).strip(),
            str(nombres).strip(),
            str(apellidos).strip(),
            str(sexo).strip(),
            fecha_nac.strftime("%Y-%m-%d"),
            fecha_llegada.strftime("%Y-%m-%d"),
            str(direccion).strip(),
            str(manzana).strip(),
            str(telefono).strip(),
            str(estado_civil).strip(),
            str(conyuge_cedula).strip(),
            1 if es_padre_madre else 0,
            str(hijos_cedulas_json),
            1 if pertenece_consejo else 0,
            str(cargo_consejo),
            str(condicion_salud).strip(),
            str(detalle_salud).strip(),
            1 if es_jefe else 0,
            str(jefe_seleccionado_cedula).strip(),
            json_extra,
        )
        guardar_habitante(datos)

        st.toast(
            f"✅ ¡Registro de {nombres} {apellidos} guardado con éxito!", icon="🎉"
        )
        st.rerun()
      else:
        st.error(
            "⚠️ Ingrese los campos obligatorios (Cédula, Nombres y Apellidos)."
        )

# -----------------------------------------------------------------------------
# TAB: ESTADÍSTICAS
# -----------------------------------------------------------------------------
if "📈 Estadísticas" in pestañas:
  with tabs[pestañas.index("📈 Estadísticas")]:
    st.subheader("📈 Resumen Estadístico, Demográfico y de Eventualidades")
    df_stat = cargar_habitantes()

    if not df_stat.empty:
      st.markdown("### 👑 Jefes de Familia y Consejo Comunal")
      df_jefes = df_stat[df_stat["es_jefe_hogar"] == 1].copy()
      total_jefes = len(df_jefes)
      total_consejo = len(df_stat[df_stat["pertenece_consejo"] == 1])

      k_jefe1, k_jefe2, k_jefe3, k_jefe4 = st.columns(4)
      k_jefe1.metric("Total Jefes de Hogar", total_jefes)
      k_jefe2.metric("Voceros / Consejo Comunal", total_consejo)
      k_jefe3.metric(
          "Total Habitantes Censados", len(df_stat)
      )
      k_jefe4.metric(
          "Promedio Integrantes por Hogar",
          f"{((len(df_stat) - total_jefes) / total_jefes):.1f}"
          if total_jefes > 0
          else "0",
      )

      st.markdown("---")

      def clasificar_rango_edad(edad):
        if edad <= 12:
          return "0 a 12 años"
        elif 13 <= edad <= 15:
          return "13 a 15 años"
        elif 16 <= edad <= 17:
          return "16 a 17 años"
        elif 18 <= edad < 60:
          return "18 a 59 años"
        else:
          return "60+ años"

      df_stat["rango_etario"] = df_stat["edad_num"].apply(clasificar_rango_edad)

      col_g1, col_g2 = st.columns(2)
      with col_g1:
        st.markdown("##### 📊 Rangos de Edad Distribuidos por Sexo")
        df_edad_sexo = (
            df_stat.groupby(["rango_etario", "sexo"])
            .size()
            .reset_index(name="Cantidad")
        )
        fig_edad_sexo = px.bar(
            df_edad_sexo,
            x="rango_etario",
            y="Cantidad",
            color="sexo",
            barmode="group",
            title="Comparativa de Edades por Sexo",
            text="Cantidad",
        )
        fig_edad_sexo.update_traces(textposition="outside")
        st.plotly_chart(fig_edad_sexo, use_container_width=True)

      with col_g2:
        st.markdown("##### 🛡️ Participación en Consejo Comunal por Cargo")
        df_cc_stat = (
            df_stat[df_stat["pertenece_consejo"] == 1]
            .groupby("cargo_consejo")
            .size()
            .reset_index(name="Voceros")
        )
        if not df_cc_stat.empty:
          fig_cc = px.pie(
              df_cc_stat,
              names="cargo_consejo",
              values="Voceros",
              hole=0.4,
              title="Distribución de Cargos en Consejo Comunal",
          )
          st.plotly_chart(fig_cc, use_container_width=True)
        else:
          st.info("No hay voceros registrados en el consejo comunal.")

    st.markdown("---")
    st.markdown("### ⚡ Estadísticas de Eventualidades y Servicios Públicos")
    df_ev_stat = cargar_eventualidades_comunales()

    if not df_ev_stat.empty:
      col_es1, col_es2 = st.columns(2)

      with col_es1:
        st.markdown("##### 📊 Eventos Registrados por Tipo y Estatus")
        df_ev_stat["Estatus Atendido"] = df_ev_stat["atendido"].apply(
            lambda x: "Atendido / Solucionado" if x == 1 else "Pendiente / En Curso"
        )
        fig_ev_tipo = px.histogram(
            df_ev_stat,
            x="tipo_evento",
            color="Estatus Atendido",
            barmode="group",
            title="Incidencias por Tipo y Estado",
        )
        st.plotly_chart(fig_ev_tipo, use_container_width=True)

      with col_es2:
        st.markdown("##### ⏱️ Análisis de Duración de Fallas y Soluciones")
        duraciones = []
        for _, row in df_ev_stat.iterrows():
          try:
            f_i = pd.to_datetime(
                f"{row['fecha_inicio']} {row['hora_inicio']}", errors="coerce"
            )
            f_f = pd.to_datetime(
                f"{row['fecha_fin']} {row['hora_fin']}", errors="coerce"
            )
            if pd.notnull(f_i) and pd.notnull(f_f):
              diff_horas = (f_f - f_i).total_seconds() / 3600.0
              if diff_horas >= 0:
                duraciones.append({
                    "Tipo": row["tipo_evento"],
                    "Sector": row["sector_afectado"],
                    "Horas": diff_horas,
                    "Estatus": (
                        "Solucionado"
                        if row["atendido"] == 1
                        else "Pendiente"
                    ),
                })
          except Exception:
            pass

        if duraciones:
          df_dur = pd.DataFrame(duraciones)
          fig_dur = px.box(
              df_dur,
              x="Tipo",
              y="Horas",
              color="Estatus",
              title="Distribución de Duración de Fallas (en Horas)",
          )
          st.plotly_chart(fig_dur, use_container_width=True)
        else:
          st.info(
              "No hay suficientes registros con horarios estructurados para"
              " calcular duraciones."
          )
    else:
      st.info("No hay eventualidades registradas para mostrar estadísticas.")

# -----------------------------------------------------------------------------
# TAB: CONFIGURAR COMUNIDAD & FORMULARIO
# -----------------------------------------------------------------------------
if "✏️ Configurar Comunidad & Formulario" in pestañas:
  with tabs[pestañas.index("✏️ Configurar Comunidad & Formulario")]:
    st.subheader(
        "⚙️ Configuración General de la Comunidad y Campos Personalizados"
    )

    st.markdown("### 🏘️ Datos del Consejo Comunal y Período")
    col_cc_conf1, col_cc_conf2 = st.columns(2)
    with col_cc_conf1:
      input_nom_comunidad = st.text_input(
          "Nombre de la Comunidad:",
          value=cfg_comunidad["nombre_comunidad"],
      )
      input_nom_consejo = st.text_input(
          "Nombre del Consejo Comunal:",
          value=cfg_comunidad["nombre_consejo"],
      )
    with col_cc_conf2:
      input_periodo = st.text_input(
          "Período de Gestión:",
          value=cfg_comunidad["periodo"],
          placeholder="Ej: 2024 - 2026",
      )
      input_vencimiento = st.text_input(
          "Fecha de Vencimiento / Elección:",
          value=cfg_comunidad["vencimiento"],
          placeholder="Ej: 06/09/2026",
      )

    if st.button(
        "💾 Guardar Datos de la Comunidad",
        type="primary",
        use_container_width=True,
    ):
      guardar_configuracion_comunidad(
          input_nom_comunidad.strip(),
          input_nom_consejo.strip(),
          input_periodo.strip(),
          input_vencimiento.strip(),
      )
      st.success(
          "✅ Datos de la comunidad actualizados correctamente. Recargando..."
      )
      st.rerun()

    st.markdown("---")
    st.markdown("### ➕ Añadir Nuevo Campo Personalizado al Censo")
    col_nc1, col_nc2, col_nc3 = st.columns([2, 1.5, 3])
    with col_nc1:
      nom_nuevo = st.text_input(
          "Nombre del Campo:", placeholder="Ej: Nivel Educativo, Ocupación..."
      )
    with col_nc2:
      tipo_nuevo = st.selectbox("Tipo de Dato:", ["Texto", "Desplegable"])
    with col_nc3:
      ops_nuevo = st.text_input(
          "Opciones si es Desplegable (separadas por comas):"
      )

    if st.button("➕ Añadir Campo Personalizado", type="primary"):
      if nom_nuevo.strip():
        lista_ops = [x.strip() for x in ops_nuevo.split(",") if x.strip()]
        agregar_campo_personalizado(nom_nuevo.strip(), tipo_nuevo, lista_ops)
        st.success(f"✅ Campo '{nom_nuevo.strip()}' creado con éxito.")
        st.rerun()
      else:
        st.error("Ingrese el nombre del campo.")

# -----------------------------------------------------------------------------
# TAB: GESTIÓN DE USUARIOS
# -----------------------------------------------------------------------------
if st.session_state.rol_actual == "Master" and "👥 Usuarios y Permisos" in pestañas:
  with tabs[pestañas.index("👥 Usuarios y Permisos")]:
    st.subheader("👥 Control de Usuarios y Matriz de Permisos")
    df_users = cargar_usuarios()
    col_u1, col_u2 = st.columns([1, 1])

    with col_u1:
      st.markdown("### ➕ Crear / Editar Usuario")
      user_sel = st.selectbox(
          "Editar usuario existente o crear nuevo:",
          ["-- Crear Nuevo --"] + list(df_users["username"]),
      )

      if user_sel != "-- Crear Nuevo --":
        row_u = df_users[df_users["username"] == user_sel].iloc[0]
        val_username = row_u["username"]
        val_nombre = row_u["nombre_completo"]
        val_rol = row_u["rol"]
        try:
          perm_actuales = json.loads(row_u["permisos"])
        except Exception:
          perm_actuales = {}
      else:
        val_username, val_nombre, val_rol, perm_actuales = (
            "",
            "",
            "Administrador",
            {},
        )

      u_username = st.text_input(
          "Username:",
          value=val_username,
          disabled=(user_sel != "-- Crear Nuevo --"),
      )
      u_pass = st.text_input(
          "Contraseña (dejar en blanco para mantener actual):", type="password"
      )
      u_nombre = st.text_input("Nombre Completo:", value=val_nombre)
      u_rol = st.selectbox(
          "Rol Asignado:",
          ["Administrador", "Visualizador"],
          index=0 if val_rol == "Administrador" else 1,
      )

      st.markdown("#### 🔑 Permisos:")
      nuevos_permisos = {}
      for perm in LISTA_PERMISOS:
        val_check = perm_actuales.get(perm, False)
        nuevos_permisos[perm] = st.checkbox(f"Permitir: `{perm}`", value=val_check)

      if st.button(
          "💾 Guardar Usuario y Permisos",
          type="primary",
          use_container_width=True,
      ):
        target_user = (
            u_username.strip() if user_sel == "-- Crear Nuevo --" else user_sel
        )
        if target_user:
          guardar_usuario(
              target_user, u_pass, u_nombre.strip(), u_rol, nuevos_permisos
          )
          st.success(f"✅ Usuario {target_user} guardado.")
          st.rerun()
        else:
          st.error("Ingrese un usuario válido.")

    with col_u2:
      st.markdown("### 📋 Usuarios Registrados")
      st.dataframe(
          df_users[["username", "nombre_completo", "rol"]],
          use_container_width=True,
          hide_index=True,
      )

# -----------------------------------------------------------------------------
# TAB: RESPALDOS Y BORRADO
# -----------------------------------------------------------------------------
if "💾 Respaldos y Borrado" in pestañas:
  with tabs[pestañas.index("💾 Respaldos y Borrado")]:
    st.subheader(
        "💾 Gestión Integral de Respaldos y Restauración del Sistema"
    )
    col_res1, col_res2 = st.columns(2)

    with col_res1:
      st.markdown("### 📤 Respaldo Estructural General")
      try:
        with open(DB_FILE, "rb") as f:
          db_bytes = f.read()
        st.download_button(
            label="📥 Descargar Base de Datos Completa (.db)",
            data=db_bytes,
            file_name=(
                "backup_sistema_censo_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            ),
            mime="application/x-sqlite3",
            use_container_width=True,
        )
      except Exception as e:
        st.error(f"No se pudo leer la base de datos: {e}")

    with col_res2:
      st.markdown("### ⚠️ Zona Peligrosa: Borrado Completo")
      confirmar_borrado = st.checkbox(
          "Confirmo que deseo borrar todos los datos del censo y bitácoras."
      )
      if st.button(
          "💣 BORRAR TODO EL CENSO", type="primary", use_container_width=True
      ):
        if confirmar_borrado:
          borrar_todo_el_censo()
          st.success("🔥 Base de datos vaciada completamente.")
          st.rerun()
        else:
          st.warning("Marque la casilla para confirmar.")
