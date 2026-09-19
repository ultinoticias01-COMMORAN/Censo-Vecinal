import sqlite3
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io
import json

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE PÁGINA Y BASE DE DATOS
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Censo Comunitario Avanzado", page_icon="🏡", layout="wide")

DB_FILE = "censo.db"

# Campos del formulario por defecto (etiqueta, tipo_control, opciones_json)
CAMPOS_BASE_DEFAULT = {
    "cedula": ("Cédula de Identidad", "texto", "[]"),
    "nombres": ("Nombres", "texto", "[]"),
    "apellidos": ("Apellidos", "texto", "[]"),
    "sexo": ("Sexo / Género", "desplegable", json.dumps(["Femenino", "Masculino", "Otro"])),
    "fecha_nac": ("Fecha de Nacimiento", "texto", "[]"),
    "telefono": ("Teléfono de Contacto", "texto", "[]"),
    "manzana": ("Manzana / Sector", "texto", "[]"),
    "fecha_llegada": ("Fecha de Llegada a la Comunidad", "texto", "[]"),
    "direccion": ("Dirección Detallada de Habitación", "texto", "[]"),
    "condicion_salud": ("Condición / Afectación de Salud", "desplegable", json.dumps(["Ninguna", "Enfermedad Crónica", "Discapacidad", "Adulto Mayor Encamado", "Embarazada", "Población de Riesgo", "Otra"])),
    "detalle_salud": ("Detalles adicionales de salud", "texto", "[]")
}

LISTA_PERMISOS = [
    "ver_censo",
    "registrar_habitantes",
    "editar_habitantes",
    "eliminar_habitantes",
    "ver_estadisticas",
    "gestion_bitacora",
    "personalizar_etiquetas",
    "respaldos_importacion"
]

def get_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabla de Habitantes
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
            condicion_salud TEXT DEFAULT 'Ninguna',
            detalle_salud TEXT DEFAULT '',
            campos_adicionales TEXT DEFAULT '{}'
        )
    """)
    
    # Tabla de Usuarios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            username TEXT PRIMARY KEY,
            password TEXT,
            nombre_completo TEXT,
            rol TEXT,
            permisos TEXT DEFAULT '{}'
        )
    """)
    
    # Migración de permisos de usuarios
    cursor.execute("PRAGMA table_info(usuarios)")
    cols_usuarios = [column[1] for column in cursor.fetchall()]
    if "permisos" not in cols_usuarios:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN permisos TEXT DEFAULT '{}'")
        perm_master = json.dumps({p: True for p in LISTA_PERMISOS})
        perm_admin = json.dumps({p: True for p in LISTA_PERMISOS if p != "personalizar_etiquetas"})
        perm_user = json.dumps({"ver_censo": True, "ver_estadisticas": True})
        cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'master'", (perm_master,))
        cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'admin'", (perm_admin,))
        cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'user'", (perm_user,))

    # Tabla de Configuración Avanzada de Campos (Estructura y Listas Desplegables)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_estilo_campos (
            clave_campo TEXT PRIMARY KEY,
            etiqueta TEXT,
            tipo_control TEXT,
            opciones_json TEXT
        )
    """)
    
    # Migración de configuración avanzada de campos
    cursor.execute("PRAGMA table_info(configuracion_estilo_campos)")
    if cursor.fetchall():
        for clave, (etiqueta_def, tipo_def, opciones_def) in CAMPOS_BASE_DEFAULT.items():
            cursor.execute("""
                INSERT OR IGNORE INTO configuracion_estilo_campos (clave_campo, etiqueta, tipo_control, opciones_json)
                VALUES (?, ?, ?, ?)
            """, (clave, etiqueta_def, tipo_def, opciones_def))

    # Tabla de Bitácora
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bitacora_documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cedula TEXT,
            tipo_documento TEXT,
            descripcion TEXT,
            fecha_emision TEXT,
            emitido_por TEXT,
            FOREIGN KEY (cedula) REFERENCES habitantes (cedula)
        )
    """)
    
    # Tabla de Campos Adicionales Extra
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_campos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_campo TEXT UNIQUE,
            tipo_campo TEXT
        )
    """)
    
    # Inicializar Usuarios por Defecto
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        permisos_master = json.dumps({p: True for p in LISTA_PERMISOS})
        permisos_admin = json.dumps({p: True for p in LISTA_PERMISOS if p != "personalizar_etiquetas"})
        permisos_user = json.dumps({"ver_censo": True, "ver_estadisticas": True})
        
        cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)", ("master", "master123", "Usuario Master", "Master", permisos_master))
        cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)", ("admin", "admin123", "Administrador Principal", "Administrador", permisos_admin))
        cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)", ("user", "user123", "Visualizador Invitado", "Visualizador", permisos_user))
    
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# 2. FUNCIONES DE GESTIÓN Y BASE DE DATOS
# -----------------------------------------------------------------------------

def cargar_configuracion_campos():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT clave_campo, etiqueta, tipo_control, opciones_json FROM configuracion_estilo_campos")
    filas = cursor.fetchall()
    conn.close()
    
    config = {}
    for f in filas:
        try:
            opciones = json.loads(f[3])
        except:
            opciones = []
        config[f[0]] = {
            "etiqueta": f[1],
            "tipo_control": f[2],
            "opciones": opciones
        }
    return config

def guardar_configuracion_campo(clave, etiqueta, tipo_control, opciones_lista):
    conn = get_connection()
    cursor = conn.cursor()
    opciones_json = json.dumps([op.strip() for op in opciones_lista if op.strip()], ensure_ascii=False)
    cursor.execute("""
        INSERT OR REPLACE INTO configuracion_estilo_campos (clave_campo, etiqueta, tipo_control, opciones_json)
        VALUES (?, ?, ?, ?)
    """, (clave, etiqueta, tipo_control, opciones_json))
    conn.commit()
    conn.close()

def formato_fecha_pantalla(fecha_str):
    try:
        f = datetime.strptime(str(fecha_str).split()[0], "%Y-%m-%d")
        return f.strftime("%d/%m/%Y")
    except:
        return str(fecha_str)

def parsear_fecha_bd(fecha_str):
    try:
        s = str(fecha_str).split()[0]
        if "/" in s:
            return datetime.strptime(s, "%d/%m/%Y").date()
        return datetime.strptime(s, "%Y-%m-%d").date()
    except:
        return datetime.now().date()

def cargar_habitantes():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM habitantes", conn)
    conn.close()
    
    df["sexo"] = df["sexo"].fillna("No especificado")
    df["condicion_salud"] = df["condicion_salud"].fillna("Ninguna")
    df["detalle_salud"] = df["detalle_salud"].fillna("")
    df["campos_adicionales"] = df["campos_adicionales"].fillna("{}")
    return df

def guardar_habitante(datos):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO habitantes (
            cedula, nombres, apellidos, sexo, fecha_nac, fecha_llegada, 
            direccion, manzana, telefono, condicion_salud, detalle_salud, campos_adicionales
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, datos)
    conn.commit()
    conn.close()

def actualizar_habitante_completo(cedula_original, datos_nuevos):
    conn = get_connection()
    cursor = conn.cursor()
    nueva_cedula = datos_nuevos[0]
    
    if cedula_original != nueva_cedula:
        cursor.execute("UPDATE bitacora_documentos SET cedula = ? WHERE cedula = ?", (nueva_cedula, cedula_original))
        cursor.execute("DELETE FROM habitantes WHERE cedula = ?", (cedula_original,))
    
    cursor.execute("""
        INSERT OR REPLACE INTO habitantes (
            cedula, nombres, apellidos, sexo, fecha_nac, fecha_llegada, 
            direccion, manzana, telefono, condicion_salud, detalle_salud, campos_adicionales
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, datos_nuevos)
    
    conn.commit()
    conn.close()

def eliminar_habitante(cedula):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM habitantes WHERE cedula = ?", (cedula,))
    cursor.execute("DELETE FROM bitacora_documentos WHERE cedula = ?", (cedula,))
    conn.commit()
    conn.close()

def borrar_todo_el_censo():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM habitantes")
    cursor.execute("DELETE FROM bitacora_documentos")
    conn.commit()
    conn.close()

# --- CAMPOS ADICIONALES EXTRA ---
def cargar_campos_personalizados():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT nombre_campo, tipo_campo FROM configuracion_campos")
    filas = cursor.fetchall()
    conn.close()
    return filas

def agregar_campo_personalizado(nombre, tipo):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO configuracion_campos (nombre_campo, tipo_campo) VALUES (?, ?)", (nombre, tipo))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

# --- USUARIOS Y PERMISOS ---
def verificar_login(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, nombre_completo, rol, permisos FROM usuarios WHERE username = ? AND password = ?", (username, password))
    user = cursor.fetchone()
    conn.close()
    return user

def cargar_usuarios():
    conn = get_connection()
    df = pd.read_sql_query("SELECT username, nombre_completo, rol, permisos FROM usuarios", conn)
    conn.close()
    return df

def guardar_usuario(username, password, nombre_completo, rol, dict_permisos):
    conn = get_connection()
    cursor = conn.cursor()
    json_permisos = json.dumps(dict_permisos)
    
    cursor.execute("SELECT password FROM usuarios WHERE username = ?", (username,))
    f = cursor.fetchone()
    pass_final = password if password.strip() else (f[0] if f else "123456")
    
    cursor.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?, ?)", (username, pass_final, nombre_completo, rol, json_permisos))
    conn.commit()
    conn.close()

def eliminar_usuario(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE username = ?", (username,))
    conn.commit()
    conn.close()

def tiene_permiso(clave_permiso):
    if st.session_state.rol_actual == "Master":
        return True
    permisos = st.session_state.get("permisos_usuario", {})
    return permisos.get(clave_permiso, False)

# Función para renderizar dinámicamente un campo (Texto o Lista Desplegable)
def renderizar_campo_dinamico(key_campo, cfg_dict, valor_previo="", key_suffix=""):
    cfg = cfg_dict.get(key_campo, {"etiqueta": key_campo, "tipo_control": "texto", "opciones": []})
    etiqueta = cfg["etiqueta"]
    tipo = cfg["tipo_control"]
    opciones = cfg["opciones"]
    
    if tipo == "desplegable" and opciones:
        index_sel = 0
        if valor_previo in opciones:
            index_sel = opciones.index(valor_previo)
        return st.selectbox(f"{etiqueta}:", opciones, index=index_sel, key=f"{key_campo}_{key_suffix}")
    else:
        return st.text_input(f"{etiqueta}:", value=str(valor_previo), key=f"{key_campo}_{key_suffix}")

# -----------------------------------------------------------------------------
# 3. CONTROL DE SESIÓN Y LOGIN
# -----------------------------------------------------------------------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None
    st.session_state.rol_actual = None
    st.session_state.permisos_usuario = {}

if not st.session_state.autenticado:
    st.markdown("<h1 style='text-align: center;'>🔒 Control de Acceso - Censo Comunitario</h1>", unsafe_allow_html=True)
    
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        with st.form("form_login"):
            usuario = st.text_input("Usuario")
            clave = st.text_input("Contraseña", type="password")
            btn_login = st.form_submit_button("Ingresar al Sistema", use_container_width=True)
            
            if btn_login:
                user_data = verificar_login(usuario, clave)
                if user_data:
                    st.session_state.autenticado = True
                    st.session_state.username = user_data[0]
                    st.session_state.usuario_actual = user_data[1]
                    st.session_state.rol_actual = user_data[2]
                    try:
                        st.session_state.permisos_usuario = json.loads(user_data[3])
                    except:
                        st.session_state.permisos_usuario = {}
                    st.success(f"¡Bienvenido {user_data[1]}!")
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas.")
    st.stop()

# -----------------------------------------------------------------------------
# 4. CARGA DE CONFIGURACIÓN DE CAMPOS DINÁMICOS
# -----------------------------------------------------------------------------
cfg_campos = cargar_configuracion_campos()

# -----------------------------------------------------------------------------
# 5. BARRA LATERAL
# -----------------------------------------------------------------------------
with st.sidebar:
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
    
    if tiene_permiso("personalizar_etiquetas"):
        st.subheader("➕ Variable Adicional Extra")
        nuevo_nom = st.text_input("Nombre Variable:")
        nuevo_tipo = st.selectbox("Tipo de Dato:", ["Texto", "Número", "Fecha"])
        
        if st.button("Guardar Variable Extra", use_container_width=True):
            if nuevo_nom.strip():
                agregar_campo_personalizado(nuevo_nom.strip(), nuevo_tipo)
                st.success("Variable creada con éxito.")
                st.rerun()

    st.caption("Sistema de Censo Comunitario v5.0")

# -----------------------------------------------------------------------------
# 6. NAVEGACIÓN Y PESTAÑAS DINÁMICAS SEGÚN PERMISOS
# -----------------------------------------------------------------------------
st.title("🏡 Censo Digital de la Comunidad")

pestañas = []
if tiene_permiso("ver_censo"):
    pestañas.append("📊 Consultar y Filtros")
if tiene_permiso("registrar_habitantes"):
    pestañas.append("📝 Registrar Habitante")
if tiene_permiso("editar_habitantes") or tiene_permiso("eliminar_habitantes"):
    pestañas.append("⚙️ Editar / Eliminar")
if tiene_permiso("ver_estadisticas"):
    pestañas.append("📈 Estadísticas")
if tiene_permiso("personalizar_etiquetas"):
    pestañas.append("✏️ Personalizar Formulario")
if st.session_state.rol_actual == "Master":
    pestañas.append("👥 Usuarios y Permisos")
if tiene_permiso("respaldos_importacion") or st.session_state.rol_actual == "Master":
    pestañas.append("💾 Respaldos y Borrado")

if not pestañas:
    st.warning("⚠️ No tienes permisos asignados para ver módulos en la aplicación. Contacta al Usuario Master.")
    st.stop()

tabs = st.tabs(pestañas)

# -----------------------------------------------------------------------------
# TAB: PERSONALIZAR FORMULARIO (NOMBRES, TIPOS Y OPCIONES DESPLEGABLES)
# -----------------------------------------------------------------------------
if "✏️ Personalizar Formulario" in pestañas:
    with tabs[pestañas.index("✏️ Personalizar Formulario")]:
        st.subheader("✏️ Configurar Campos y Listas Desplegables del Formulario")
        st.info("Aquí puedes cambiar el nombre de cada campo, decidir si será un texto libre o una lista desplegable, y definir sus opciones separadas por comas.")
        
        with st.form("form_config_campos_avanzado"):
            for clave, (etiqueta_def, tipo_def, opciones_def) in CAMPOS_BASE_DEFAULT.items():
                st.markdown(f"#### ⚙️ Campo: `{clave}`")
                c_data = cfg_campos.get(clave, {"etiqueta": etiqueta_def, "tipo_control": tipo_def, "opciones": json.loads(opciones_def)})
                
                col_c1, col_c2, col_c3 = st.columns([2, 1.5, 3])
                
                with col_c1:
                    nueva_etiq = st.text_input(f"Nombre del campo ({clave}):", value=c_data["etiqueta"], key=f"cfg_lbl_{clave}")
                with col_c2:
                    nuevo_tipo_ctrl = st.selectbox(
                        "Tipo de control:",
                        ["texto", "desplegable"],
                        index=0 if c_data["tipo_control"] == "texto" else 1,
                        key=f"cfg_tipo_{clave}"
                    )
                with col_c3:
                    str_opciones_actuales = ", ".join(c_data["opciones"])
                    nuevas_opciones_str = st.text_input(
                        "Opciones (separadas por comas si es desplegable):",
                        value=str_opciones_actuales,
                        key=f"cfg_ops_{clave}"
                    )
                st.markdown("---")

            if st.form_submit_button("💾 Guardar Toda la Configuración del Formulario", type="primary", use_container_width=True):
                for clave in CAMPOS_BASE_DEFAULT.keys():
                    etiq_val = st.session_state[f"cfg_lbl_{clave}"].strip()
                    tipo_ctrl_val = st.session_state[f"cfg_tipo_{clave}"]
                    ops_raw = st.session_state[f"cfg_ops_{clave}"]
                    
                    lista_ops = [x.strip() for x in ops_raw.split(",") if x.strip()]
                    guardar_configuracion_campo(clave, etiq_val, tipo_ctrl_val, lista_ops)
                
                st.success("✅ Configuración de campos y listas desplegables actualizada.")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB: REGISTRAR HABITANTE
# -----------------------------------------------------------------------------
if "📝 Registrar Habitante" in pestañas:
    with tabs[pestañas.index("📝 Registrar Habitante")]:
        st.subheader("📝 Formulario Unificado de Registro de Habitante")
        
        datos_extra = {}
        
        with st.form("form_censo_unificado", clear_on_submit=True):
            # 1. DATOS PERSONALES
            st.markdown("### 👤 Datos Personales e Identificación")
            col1, col2 = st.columns(2)
            with col1:
                cedula = renderizar_campo_dinamico("cedula", cfg_campos, key_suffix="reg")
                nombres = renderizar_campo_dinamico("nombres", cfg_campos, key_suffix="reg")
                apellidos = renderizar_campo_dinamico("apellidos", cfg_campos, key_suffix="reg")
            with col2:
                sexo = renderizar_campo_dinamico("sexo", cfg_campos, key_suffix="reg")
                lbl_fn = cfg_campos.get("fecha_nac", {}).get("etiqueta", "Fecha de Nacimiento")
                fecha_nac = st.date_input(f"{lbl_fn} (DD/MM/YYYY)", min_value=datetime(1920, 1, 1), max_value=datetime.now(), format="DD/MM/YYYY")
                telefono = renderizar_campo_dinamico("telefono", cfg_campos, key_suffix="reg")

            st.markdown("---")

            # 2. UBICACIÓN Y VIVIENDA
            st.markdown("### 🏠 Ubicación y Vivienda")
            col3, col4 = st.columns(2)
            with col3:
                manzana = renderizar_campo_dinamico("manzana", cfg_campos, key_suffix="reg")
                lbl_fl = cfg_campos.get("fecha_llegada", {}).get("etiqueta", "Fecha de Llegada")
                fecha_llegada = st.date_input(f"{lbl_fl} (DD/MM/YYYY)", min_value=datetime(1950, 1, 1), max_value=datetime.now(), format="DD/MM/YYYY")
            with col4:
                direccion = renderizar_campo_dinamico("direccion", cfg_campos, key_suffix="reg")

            st.markdown("---")

            # 3. SALUD Y VULNERABILIDAD
            st.markdown("### ⚕️ Salud y Vulnerabilidad")
            col5, col6 = st.columns(2)
            with col5:
                condicion_salud = renderizar_campo_dinamico("condicion_salud", cfg_campos, key_suffix="reg")
            with col6:
                detalle_salud = renderizar_campo_dinamico("detalle_salud", cfg_campos, key_suffix="reg")

            st.markdown("---")

            # 4. CAMPOS ADICIONALES EXTRA
            st.markdown("### ➕ Campos Adicionales Personalizados")
            campos_config = cargar_campos_personalizados()
            if campos_config:
                col_c1, col_c2 = st.columns(2)
                for idx, (nom_c, tipo_c) in enumerate(campos_config):
                    target_col = col_c1 if idx % 2 == 0 else col_c2
                    with target_col:
                        if tipo_c == "Texto":
                            datos_extra[nom_c] = st.text_input(f"{nom_c}:")
                        elif tipo_c == "Número":
                            datos_extra[nom_c] = st.number_input(f"{nom_c}:", value=0)
                        elif tipo_c == "Fecha":
                            d_extra = st.date_input(f"{nom_c} (DD/MM/YYYY):", format="DD/MM/YYYY")
                            datos_extra[nom_c] = d_extra.strftime("%d/%m/%Y")
            else:
                st.info("No hay variables extra personalizadas configuradas.")

            st.markdown("---")
            guardar = st.form_submit_button("💾 Guardar Registro de Habitante", type="primary", use_container_width=True)

        if guardar:
            if str(nombres).strip() and str(apellidos).strip() and str(cedula).strip():
                json_extra = json.dumps(datos_extra, ensure_ascii=False)
                datos = (
                    str(cedula).strip(), str(nombres).strip(), str(apellidos).strip(), str(sexo).strip(),
                    fecha_nac.strftime("%Y-%m-%d"), fecha_llegada.strftime("%Y-%m-%d"),
                    str(direccion).strip(), str(manzana).strip(), str(telefono).strip(),
                    str(condicion_salud).strip(), str(detalle_salud).strip(), json_extra
                )
                guardar_habitante(datos)
                st.success(f"✅ Registro de {nombres} {apellidos} guardado exitosamente.")
            else:
                st.error("⚠️ Ingrese los campos obligatorios.")

# -----------------------------------------------------------------------------
# TAB: CONSULTAR Y FILTROS
# -----------------------------------------------------------------------------
if "📊 Consultar y Filtros" in pestañas:
    with tabs[pestañas.index("📊 Consultar y Filtros")]:
        st.subheader("Consulta General de Habitantes")
        df = cargar_habitantes()
        
        if not df.empty:
            df_pantalla = df.copy()
            df_pantalla["fecha_nac"] = df_pantalla["fecha_nac"].apply(formato_fecha_pantalla)
            df_pantalla["fecha_llegada"] = df_pantalla["fecha_llegada"].apply(formato_fecha_pantalla)
            
            # Renombrar columnas según etiquetas configuradas
            renombrar_dic = {clave: cfg_campos.get(clave, {}).get("etiqueta", clave) for clave in CAMPOS_BASE_DEFAULT.keys()}
            df_pantalla = df_pantalla.rename(columns=renombrar_dic)

            busqueda = st.text_input("🔍 Buscar en el censo...")
            if busqueda:
                df_pantalla = df_pantalla[df_pantalla.astype(str).apply(lambda x: x.str.contains(busqueda, case=False)).any(axis=1)]

            st.dataframe(df_pantalla, use_container_width=True, hide_index=True)
        else:
            st.info("No hay registros cargados.")

# -----------------------------------------------------------------------------
# TAB: EDITAR / ELIMINAR HABITANTE
# -----------------------------------------------------------------------------
if "⚙️ Editar / Eliminar" in pestañas:
    with tabs[pestañas.index("⚙️ Editar / Eliminar")]:
        st.subheader("⚙️ Modificación de Datos del Habitante")
        
        df_edit = cargar_habitantes()
        if not df_edit.empty:
            cedula_buscar = st.selectbox("Seleccione la persona a modificar:", df_edit["cedula"].unique())
            hab = df_edit[df_edit["cedula"] == cedula_buscar].iloc[0]
            
            try:
                dict_dyn = json.loads(hab["campos_adicionales"])
            except:
                dict_dyn = {}

            with st.form("form_edit_unificado"):
                # 1. DATOS PERSONALES
                st.markdown("### 👤 Datos Personales")
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    e_cedula = renderizar_campo_dinamico("cedula", cfg_campos, hab['cedula'], key_suffix="edit")
                    e_nombres = renderizar_campo_dinamico("nombres", cfg_campos, hab['nombres'], key_suffix="edit")
                    e_apellidos = renderizar_campo_dinamico("apellidos", cfg_campos, hab['apellidos'], key_suffix="edit")
                with col_e2:
                    e_sexo = renderizar_campo_dinamico("sexo", cfg_campos, hab['sexo'], key_suffix="edit")
                    fn_dt = parsear_fecha_bd(hab['fecha_nac'])
                    lbl_fn = cfg_campos.get("fecha_nac", {}).get("etiqueta", "Fecha Nacimiento")
                    e_fn = st.date_input(f"{lbl_fn}:", value=fn_dt, format="DD/MM/YYYY")
                    e_telefono = renderizar_campo_dinamico("telefono", cfg_campos, hab['telefono'], key_suffix="edit")

                st.markdown("---")

                # 2. UBICACIÓN
                st.markdown("### 🏠 Ubicación")
                col_e3, col_e4 = st.columns(2)
                with col_e3:
                    e_manzana = renderizar_campo_dinamico("manzana", cfg_campos, hab['manzana'], key_suffix="edit")
                    fl_dt = parsear_fecha_bd(hab['fecha_llegada'])
                    lbl_fl = cfg_campos.get("fecha_llegada", {}).get("etiqueta", "Fecha Llegada")
                    e_fl = st.date_input(f"{lbl_fl}:", value=fl_dt, format="DD/MM/YYYY")
                with col_e4:
                    e_direccion = renderizar_campo_dinamico("direccion", cfg_campos, hab['direccion'], key_suffix="edit")

                st.markdown("---")

                # 3. SALUD
                st.markdown("### ⚕️ Salud")
                col_e5, col_e6 = st.columns(2)
                with col_e5:
                    e_condicion_salud = renderizar_campo_dinamico("condicion_salud", cfg_campos, hab['condicion_salud'], key_suffix="edit")
                with col_e6:
                    e_detalle_salud = renderizar_campo_dinamico("detalle_salud", cfg_campos, hab['detalle_salud'], key_suffix="edit")

                st.markdown("---")

                # 4. CAMPOS EXTRA
                st.markdown("### ➕ Campos Adicionales Extra")
                e_dict_extra = {}
                campos_cfg = cargar_campos_personalizados()
                
                if campos_cfg:
                    col_ec1, col_ec2 = st.columns(2)
                    for idx, (nom_c, tipo_c) in enumerate(campos_cfg):
                        target_col = col_ec1 if idx % 2 == 0 else col_ec2
                        val_prev = dict_dyn.get(nom_c, "")
                        with target_col:
                            if tipo_c == "Texto":
                                e_dict_extra[nom_c] = st.text_input(f"{nom_c}:", value=str(val_prev))
                            elif tipo_c == "Número":
                                e_dict_extra[nom_c] = st.number_input(f"{nom_c}:", value=int(val_prev) if str(val_prev).isdigit() else 0)
                            elif tipo_c == "Fecha":
                                e_dict_extra[nom_c] = st.text_input(f"{nom_c} (DD/MM/YYYY):", value=str(val_prev))

                st.markdown("---")
                btn_mod = st.form_submit_button("💾 Actualizar Todos los Datos", type="primary", use_container_width=True)
                
                if btn_mod:
                    datos_mod = (
                        str(e_cedula).strip(), str(e_nombres).strip(), str(e_apellidos).strip(), str(e_sexo).strip(),
                        e_fn.strftime("%Y-%m-%d"), e_fl.strftime("%Y-%m-%d"),
                        str(e_direccion).strip(), str(e_manzana).strip(), str(e_telefono).strip(),
                        str(e_condicion_salud).strip(), str(e_detalle_salud).strip(), json.dumps(e_dict_extra, ensure_ascii=False)
                    )
                    actualizar_habitante_completo(cedula_buscar, datos_mod)
                    st.success("✅ Datos actualizados correctamente.")
                    st.rerun()

            if tiene_permiso("eliminar_habitantes"):
                st.markdown("---")
                if st.button(f"🗑️ Eliminar Registro de {hab['nombres']} {hab['apellidos']}", type="primary", use_container_width=True):
                    eliminar_habitante(cedula_buscar)
                    st.success("✅ Registro eliminado.")
                    st.rerun()

# -----------------------------------------------------------------------------
# TAB: GESTIÓN DE USUARIOS Y PERMISOS (SOLO MASTER)
# -----------------------------------------------------------------------------
if st.session_state.rol_actual == "Master" and "👥 Usuarios y Permisos" in pestañas:
    with tabs[pestañas.index("👥 Usuarios y Permisos")]:
        st.subheader("👥 Control de Usuarios y Matriz de Permisos (Dominio Máster)")
        
        df_users = cargar_usuarios()
        col_u1, col_u2 = st.columns([1, 1])
        
        with col_u1:
            st.markdown("### ➕ Crear / Editar Usuario")
            user_sel = st.selectbox("Editar usuario existente o crear nuevo:", ["-- Crear Nuevo --"] + list(df_users["username"]))
            
            if user_sel != "-- Crear Nuevo --":
                row_u = df_users[df_users["username"] == user_sel].iloc[0]
                val_username = row_u["username"]
                val_nombre = row_u["nombre_completo"]
                val_rol = row_u["rol"]
                try:
                    perm_actuales = json.loads(row_u["permisos"])
                except:
                    perm_actuales = {}
            else:
                val_username, val_nombre, val_rol, perm_actuales = "", "", "Administrador", {}

            with st.form("form_gestion_usuario"):
                u_username = st.text_input("Username:", value=val_username, disabled=(user_sel != "-- Crear Nuevo --"))
                u_pass = st.text_input("Contraseña (dejar en blanco para mantener actual):", type="password")
                u_nombre = st.text_input("Nombre Completo:", value=val_nombre)
                u_rol = st.selectbox("Rol Asignado:", ["Administrador", "Visualizador"], index=0 if val_rol == "Administrador" else 1)
                
                st.markdown("#### 🔑 Tildar Permisos y Módulos Permitidos:")
                nuevos_permisos = {}
                for perm in LISTA_PERMISOS:
                    val_check = perm_actuales.get(perm, False)
                    nuevos_permisos[perm] = st.checkbox(f"Permitir: `{perm}`", value=val_check)
                
                if st.form_submit_button("💾 Guardar Usuario y Permisos", type="primary", use_container_width=True):
                    target_user = u_username.strip() if user_sel == "-- Crear Nuevo --" else user_sel
                    if target_user:
                        guardar_usuario(target_user, u_pass, u_nombre.strip(), u_rol, nuevos_permisos)
                        st.success(f"✅ Usuario {target_user} guardado exitosamente.")
                        st.rerun()
                    else:
                        st.error("Ingrese un nombre de usuario válido.")

        with col_u2:
            st.markdown("### 📋 Usuarios Registrados")
            st.dataframe(df_users[["username", "nombre_completo", "rol"]], use_container_width=True, hide_index=True)
            
            st.markdown("---")
            st.markdown("### 🗑️ Eliminar Usuario")
            u_del = st.selectbox("Seleccionar usuario a eliminar:", [u for u in df_users["username"] if u != "master"])
            if st.button("🗑️ Eliminar Usuario Seleccionado", type="primary"):
                eliminar_usuario(u_del)
                st.success("Usuario eliminado.")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB: RESPALDOS Y BORRADO TOTAL DEL CENSO
# -----------------------------------------------------------------------------
if "💾 Respaldos y Borrado" in pestañas:
    with tabs[pestañas.index("💾 Respaldos y Borrado")]:
        st.subheader("💾 Gestión de Respaldos e Importación")
        
        col_res1, col_res2 = st.columns(2)
        
        with col_res1:
            st.markdown("### 📤 Exportar Datos")
            df_exp = cargar_habitantes()
            if not df_exp.empty:
                csv_bytes = df_exp.to_csv(index=False, sep=";", encoding="utf-8-sig")
                st.download_button("📥 Descargar Censo (CSV)", csv_bytes, "censo_comunidad.csv", "text/csv")
                
                buffer_exc = io.BytesIO()
                with pd.ExcelWriter(buffer_exc, engine='openpyxl') as writer:
                    df_exp.to_excel(writer, index=False, sheet_name="Censo")
                st.download_button("📊 Descargar Censo (Excel)", buffer_exc.getvalue(), "censo_comunidad.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        with col_res2:
            st.markdown("### 📥 Importar Archivos (CSV / Excel)")
            uploaded_file = st.file_uploader("Cargar archivo", type=["csv", "xlsx"])
            if uploaded_file is not None and st.button("📥 Procesar e Importar"):
                try:
                    if uploaded_file.name.endswith(".xlsx"):
                        df_imp = pd.read_excel(uploaded_file)
                    else:
                        try:
                            df_imp = pd.read_csv(uploaded_file, sep=";", encoding="utf-8-sig")
                            if len(df_imp.columns) <= 1:
                                uploaded_file.seek(0)
                                df_imp = pd.read_csv(uploaded_file, sep=",")
                        except:
                            uploaded_file.seek(0)
                            df_imp = pd.read_csv(uploaded_file, sep=",")

                    df_imp.columns = [str(col).strip().lower() for col in df_imp.columns]

                    for _, row in df_imp.iterrows():
                        f_nac_imp = parsear_fecha_bd(row.get("fecha_nacimiento", row.get("fecha_nac", ""))).strftime("%Y-%m-%d")
                        f_lleg_imp = parsear_fecha_bd(row.get("fecha_llegada", "")).strftime("%Y-%m-%d")

                        guardar_habitante((
                            str(row.get("cedula", "")).strip(),
                            str(row.get("nombres", row.get("nombre", ""))).strip(),
                            str(row.get("apellidos", row.get("apellido", ""))).strip(),
                            str(row.get("sexo", "No especificado")).strip(),
                            f_nac_imp,
                            f_lleg_imp,
                            str(row.get("direccion", "")).strip(),
                            str(row.get("manzana", "")).strip(),
                            str(row.get("telefono", "")).strip(),
                            str(row.get("condicion_salud", "Ninguna")).strip(),
                            str(row.get("detalle_salud", "")).strip(),
                            str(row.get("campos_adicionales", "{}")).strip()
                        ))
                    st.success("✅ Importación completada.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al importar archivo: {e}")

        st.markdown("---")
        st.markdown("### ⚠️ Zona Peligrosa: Borrado Completo del Censo")
        st.error("Esta acción eliminará de forma permanente TODOS los registros de habitantes del censo y la bitácora.")
        
        confirmar_borrado = st.checkbox("Confirmo que deseo borrar todos los datos del censo definitivamente.")
        
        if st.button("💣 BORRAR TODO EL CENSO", type="primary", use_container_width=True):
            if confirmar_borrado:
                borrar_todo_el_censo()
                st.success("🔥 Se ha vaciado la base de datos del censo por completo.")
                st.rerun()
            else:
                st.warning("Debe tildar la casilla de confirmación para poder vaciar el censo.")
