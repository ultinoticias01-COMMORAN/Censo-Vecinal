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
        cursor.execute("ALTER TABLE usuarios ADD COLUMN permisos TEXT DEFAULT '{}'")
        perm_master = json.dumps({p: True for p in LISTA_PERMISOS})
        perm_admin = json.dumps({p: True for p in LISTA_PERMISOS if p != "personalizar_etiquetas"})
        perm_user = json.dumps({"ver_censo": True, "ver_estadisticas": True})
        cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'master'", (perm_master,))
        cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'admin'", (perm_admin,))
        cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'user'", (perm_user,))

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_estilo_campos (
            clave_campo TEXT PRIMARY KEY,
            etiqueta TEXT,
            tipo_control TEXT,
            opciones_json TEXT
        )
    """)
    
    cursor.execute("PRAGMA table_info(configuracion_estilo_campos)")
    if cursor.fetchall():
        for clave, (etiqueta_def, tipo_def, opciones_def) in CAMPOS_BASE_DEFAULT.items():
            cursor.execute("""
                INSERT OR IGNORE INTO configuracion_estilo_campos (clave_campo, etiqueta, tipo_control, opciones_json)
                VALUES (?, ?, ?, ?)
            """, (clave, etiqueta_def, tipo_def, opciones_def))

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
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_campos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_campo TEXT UNIQUE,
            tipo_campo TEXT
        )
    """)
    
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
# 2. FUNCIONES DE GESTIÓN Y CÁLCULOS
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
    fecha_defecto = datetime(1990, 1, 1).date()
    if not fecha_str or str(fecha_str).strip() in ["None", "nan", ""]:
        return fecha_defecto
    
    try:
        s = str(fecha_str).split()[0]
        if "/" in s:
            f = datetime.strptime(s, "%d/%m/%Y").date()
        else:
            f = datetime.strptime(s, "%Y-%m-%d").date()
            
        if f.year < 1900:
            return datetime(1900, 1, 1).date()
        return f
    except:
        return fecha_defecto

def calcular_edad(fecha_nac_str):
    try:
        f_nac = parsear_fecha_bd(fecha_nac_str)
        hoy = datetime.now().date()
        return hoy.year - f_nac.year - ((hoy.month, hoy.day) < (f_nac.month, f_nac.day))
    except:
        return 0

def calcular_tiempo_comunidad(fecha_llegada_str):
    try:
        f_lleg = parsear_fecha_bd(fecha_llegada_str)
        hoy = datetime.now().date()
        anios = hoy.year - f_lleg.year - ((hoy.month, hoy.day) < (f_lleg.month, f_lleg.day))
        return max(0, anios)
    except:
        return 0

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

# --- FUNCIONES DE BITÁCORA ---
def registrar_documento_bitacora(cedula, tipo_doc, descripcion, emitido_por):
    conn = get_connection()
    cursor = conn.cursor()
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO bitacora_documentos (cedula, tipo_documento, descripcion, fecha_emision, emitido_por)
        VALUES (?, ?, ?, ?, ?)
    """, (cedula, tipo_doc, descripcion, fecha_actual, emitido_por))
    conn.commit()
    conn.close()

def obtener_bitacora_habitante(cedula):
    conn = get_connection()
    df = pd.read_sql_query("SELECT id, tipo_documento, descripcion, fecha_emision, emitido_por FROM bitacora_documentos WHERE cedula = ? ORDER BY id DESC", conn, params=(cedula,))
    conn.close()
    return df

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

def renderizar_campo_dinamico(key_campo, cfg_dict, valor_previo="", key_suffix=""):
    cfg = cfg_dict.get(key_campo, {"etiqueta": key_campo, "tipo_control": "texto", "opciones": []})
    etiqueta = cfg["etiqueta"]
    tipo = cfg["tipo_control"]
    opciones = cfg["opciones"]
    
    if tipo == "desplegable" and opciones:
        index_sel = 0
        if str(valor_previo) in opciones:
            index_sel = opciones.index(str(valor_previo))
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

    st.caption("Sistema de Censo Comunitario v5.5")

# -----------------------------------------------------------------------------
# 6. NAVEGACIÓN Y PESTAÑAS DINÁMICAS
# -----------------------------------------------------------------------------
st.title("🏡 Censo Digital de la Comunidad")

pestañas = []
if tiene_permiso("ver_censo"):
    pestañas.append("📊 Consultar y Filtros")
if tiene_permiso("registrar_habitantes"):
    pestañas.append("📝 Registrar Habitante")
if tiene_permiso("gestion_bitacora"):
    pestañas.append("📜 Bitácora de Documentos")
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
# TAB: CONSULTAR Y FILTROS (BÚSQUEDA EN TODOS LOS CAMPOS Y DESCARGA)
# -----------------------------------------------------------------------------
if "📊 Consultar y Filtros" in pestañas:
    with tabs[pestañas.index("📊 Consultar y Filtros")]:
        st.subheader("📊 Búsqueda Global e Información Detallada de Habitantes")
        df = cargar_habitantes()
        
        if not df.empty:
            df["edad_num"] = df["fecha_nac"].apply(calcular_edad)
            df["tiempo_comunidad_num"] = df["fecha_llegada"].apply(calcular_tiempo_comunidad)
            
            # Buscador global
            col_search1, col_search2 = st.columns([3, 1])
            with col_search1:
                busqueda = st.text_input("🔍 Buscar en TODOS los campos (Cédula, Nombres, Dirección, Salud, Teléfono, etc.):", placeholder="Escriba cualquier dato para buscar...")
            with col_search2:
                vista_modo = st.radio("Modo de vista:", ["Tarjetas Visuales", "Tabla Resumida"], horizontal=True)

            # Filtro omnicanal (busca coincidencia en cualquier columna convertida a texto)
            if busqueda.strip():
                df_filtrado = df[df.apply(lambda row: row.astype(str).str.contains(busqueda, case=False).any(), axis=1)]
            else:
                df_filtrado = df.copy()

            st.caption(f"Mostrando {len(df_filtrado)} registro(s) encontrado(s).")

            # --- OPCIÓN DE DESCARGA DE ENCONTRADOS ---
            if not df_filtrado.empty:
                col_dl1, col_dl2, _ = st.columns([1, 1, 2])
                with col_dl1:
                    csv_data = df_filtrado.to_csv(index=False, sep=";", encoding="utf-8-sig")
                    st.download_button(
                        label="📥 Descargar Encontrados (CSV)",
                        data=csv_data,
                        file_name=f"censo_busqueda_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                with col_dl2:
                    buffer_excel = io.BytesIO()
                    with pd.ExcelWriter(buffer_excel, engine='openpyxl') as writer:
                        df_filtrado.to_excel(writer, index=False, sheet_name="Resultados")
                    st.download_button(
                        label="📊 Descargar Encontrados (Excel)",
                        data=buffer_excel.getvalue(),
                        file_name=f"censo_busqueda_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                st.markdown("---")

            if vista_modo == "Tarjetas Visuales":
                for idx, hab in df_filtrado.iterrows():
                    cedula_curr = hab["cedula"]
                    nombre_completo = f"{hab['nombres']} {hab['apellidos']}"
                    
                    with st.expander(f"👤 **{nombre_completo}** — Cédula: `{cedula_curr}` | Manzana: {hab['manzana']}", expanded=bool(busqueda.strip())):
                        
                        # Indicadores Clave Visuales
                        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
                        kpi1.metric("🎂 Edad", f"{hab['edad_num']} años")
                        kpi2.metric("🏠 Tiempo Comunidad", f"{hab['tiempo_comunidad_num']} años")
                        kpi3.metric("👫 Sexo", hab['sexo'])
                        kpi4.metric("📞 Teléfono", hab['telefono'] if hab['telefono'] else "Sin datos")
                        kpi5.metric("🏘️ Manzana / Sector", hab['manzana'])

                        st.markdown("---")
                        
                        # Detalle en dos columnas
                        col_info1, col_info2 = st.columns(2)
                        with col_info1:
                            st.markdown("##### 📌 Datos Personales y Habitación")
                            st.write(f"**Fecha de Nacimiento:** {formato_fecha_pantalla(hab['fecha_nac'])}")
                            st.write(f"**Fecha de Llegada:** {formato_fecha_pantalla(hab['fecha_llegada'])}")
                            st.write(f"**Dirección Detallada:** {hab['direccion']}")

                        with col_info2:
                            st.markdown("##### ⚕️ Salud y Variables Adicionales")
                            st.write(f"**Condición de Salud:** {hab['condicion_salud']}")
                            if hab['detalle_salud']:
                                st.write(f"**Detalle Salud:** {hab['detalle_salud']}")
                            
                            try:
                                extras = json.loads(hab['campos_adicionales'])
                                if extras:
                                    st.markdown("**Variables Adicionales:**")
                                    for k_ext, v_ext in extras.items():
                                        st.write(f"- *{k_ext}:* {v_ext}")
                            except:
                                pass

                        st.markdown("---")
                        
                        # Botones de Acción Directos
                        btn_col1, btn_col2, _ = st.columns([1, 1, 3])
                        
                        if tiene_permiso("editar_habitantes"):
                            with btn_col1:
                                if st.button(f"✏️ Editar Datos", key=f"btn_edit_{cedula_curr}", use_container_width=True):
                                    st.session_state[f"modo_edit_{cedula_curr}"] = not st.session_state.get(f"modo_edit_{cedula_curr}", False)

                        if tiene_permiso("eliminar_habitantes"):
                            with btn_col2:
                                if st.button(f"🗑️ Eliminar Registro", key=f"btn_del_{cedula_curr}", type="primary", use_container_width=True):
                                    eliminar_habitante(cedula_curr)
                                    st.success(f"Habitante con cédula {cedula_curr} eliminado.")
                                    st.rerun()

                        # Formulario In-Situ para Editar Datos
                        if st.session_state.get(f"modo_edit_{cedula_curr}", False):
                            st.markdown("---")
                            st.subheader(f"🛠️ Editar Datos de {nombre_completo}")
                            
                            with st.form(key=f"form_insitu_edit_{cedula_curr}"):
                                col_ins1, col_ins2 = st.columns(2)
                                with col_ins1:
                                    e_ced = st.text_input("Cédula:", value=hab['cedula'])
                                    e_nom = st.text_input("Nombres:", value=hab['nombres'])
                                    e_ape = st.text_input("Apellidos:", value=hab['apellidos'])
                                    e_tel = st.text_input("Teléfono:", value=hab['telefono'])
                                with col_ins2:
                                    e_sex = st.selectbox("Sexo:", ["Femenino", "Masculino", "Otro"], index=0 if hab['sexo']=="Femenino" else (1 if hab['sexo']=="Masculino" else 2))
                                    # LÍMITE DESDE 1900 APLICADO AQUÍ
                                    e_fn = st.date_input(
                                        "Fecha Nacimiento:", 
                                        value=parsear_fecha_bd(hab['fecha_nac']), 
                                        min_value=datetime(1900, 1, 1).date(), 
                                        max_value=datetime.now().date(), 
                                        format="DD/MM/YYYY"
                                    )
                                    e_fl = st.date_input(
                                        "Fecha Llegada:", 
                                        value=parsear_fecha_bd(hab['fecha_llegada']), 
                                        min_value=datetime(1900, 1, 1).date(), 
                                        max_value=datetime.now().date(), 
                                        format="DD/MM/YYYY"
                                    )
                                
                                e_man = st.text_input("Manzana:", value=hab['manzana'])
                                e_dir = st.text_area("Dirección:", value=hab['direccion'])
                                e_sal = st.text_input("Condición Salud:", value=hab['condicion_salud'])
                                e_detsal = st.text_input("Detalle Salud:", value=hab['detalle_salud'])
                                
                                if st.form_submit_button("💾 Guardar Cambios", type="primary", use_container_width=True):
                                    datos_actualizados = (
                                        e_ced.strip(), e_nom.strip(), e_ape.strip(), e_sex,
                                        e_fn.strftime("%Y-%m-%d"), e_fl.strftime("%Y-%m-%d"),
                                        e_dir.strip(), e_man.strip(), e_tel.strip(),
                                        e_sal.strip(), e_detsal.strip(), hab['campos_adicionales']
                                    )
                                    actualizar_habitante_completo(cedula_curr, datos_actualizados)
                                    st.session_state[f"modo_edit_{cedula_curr}"] = False
                                    st.success("✅ Cambios guardados correctamente.")
                                    st.rerun()

            else:
                # VISTA TABULAR COMPACTA
                df_tabla = df_filtrado.copy()
                df_tabla["Edad"] = df_tabla["edad_num"]
                df_tabla["Años Comunidad"] = df_tabla["tiempo_comunidad_num"]
                df_tabla["fecha_nac"] = df_tabla["fecha_nac"].apply(formato_fecha_pantalla)
                df_tabla["fecha_llegada"] = df_tabla["fecha_llegada"].apply(formato_fecha_pantalla)
                
                cols_mostrar = ["cedula", "nombres", "apellidos", "sexo", "Edad", "Años Comunidad", "manzana", "telefono", "condicion_salud"]
                st.dataframe(df_tabla[cols_mostrar], use_container_width=True, hide_index=True)
        else:
            st.info("No hay registros cargados en la base de datos.")

# -----------------------------------------------------------------------------
# TAB: BITÁCORA DE DOCUMENTOS (CONSTANCIAS / CARTAS)
# -----------------------------------------------------------------------------
if "📜 Bitácora de Documentos" in pestañas:
    with tabs[pestañas.index("📜 Bitácora de Documentos")]:
        st.subheader("📜 Registro y Bitácora de Emitidos (Cartas y Constancias)")
        df_bit = cargar_habitantes()
        
        if not df_bit.empty:
            col_b1, col_b2 = st.columns([1, 2])
            
            with col_b1:
                st.markdown("### ✍️ Emitir / Registrar Documento")
                habitante_sel = st.selectbox(
                    "Seleccione Habitante:", 
                    options=df_bit["cedula"].tolist(),
                    format_func=lambda c: f"{c} - {df_bit[df_bit['cedula']==c]['nombres'].values[0]} {df_bit[df_bit['cedula']==c]['apellidos'].values[0]}"
                )
                
                with st.form("form_registro_bitacora", clear_on_submit=True):
                    tipo_doc = st.selectbox("Tipo de Documento:", [
                        "Constancia de Residencia",
                        "Carta de Buena Conducta",
                        "Constancia de Soltería",
                        "Permiso de Mudanza",
                        "Aval Comunitario",
                        "Otro Documento"
                    ])
                    desc_doc = st.text_area("Observaciones / Detalles del Trámite:")
                    btn_bit = st.form_submit_button("📜 Registrar en Bitácora", type="primary", use_container_width=True)
                    
                    if btn_bit:
                        registrar_documento_bitacora(habitante_sel, tipo_doc, desc_doc.strip(), st.session_state.usuario_actual)
                        st.success("✅ Trámite registrado en la bitácora del habitante.")
                        st.rerun()

            with col_b2:
                st.markdown(f"### 📑 Historial de Trámites del Habitante (`Cédula: {habitante_sel}`)")
                df_historial = obtener_bitacora_habitante(habitante_sel)
                
                if not df_historial.empty:
                    df_historial["fecha_emision"] = df_historial["fecha_emision"].apply(formato_fecha_pantalla)
                    df_historial.columns = ["ID", "Documento", "Detalles", "Fecha Emisión", "Emitido Por"]
                    st.dataframe(df_historial, use_container_width=True, hide_index=True)
                else:
                    st.info("No se han emitido constancias ni documentos previos para este habitante.")
        else:
            st.info("Registre habitantes para utilizar el módulo de bitácora.")

# -----------------------------------------------------------------------------
# TAB: REGISTRAR HABITANTE
# -----------------------------------------------------------------------------
if "📝 Registrar Habitante" in pestañas:
    with tabs[pestañas.index("📝 Registrar Habitante")]:
        st.subheader("📝 Formulario Unificado de Registro de Habitante")
        
        datos_extra = {}
        
        with st.form("form_censo_unificado", clear_on_submit=True):
            st.markdown("### 👤 Datos Personales e Identificación")
            col1, col2 = st.columns(2)
            with col1:
                cedula = renderizar_campo_dinamico("cedula", cfg_campos, key_suffix="reg")
                nombres = renderizar_campo_dinamico("nombres", cfg_campos, key_suffix="reg")
                apellidos = renderizar_campo_dinamico("apellidos", cfg_campos, key_suffix="reg")
            with col2:
                sexo = renderizar_campo_dinamico("sexo", cfg_campos, key_suffix="reg")
                lbl_fn = cfg_campos.get("fecha_nac", {}).get("etiqueta", "Fecha de Nacimiento")
                # LÍMITE DESDE 1900 APLICADO AQUÍ
                fecha_nac = st.date_input(
                    f"{lbl_fn} (DD/MM/YYYY)", 
                    min_value=datetime(1900, 1, 1).date(), 
                    max_value=datetime.now().date(), 
                    value=datetime(1990, 1, 1).date(), 
                    format="DD/MM/YYYY"
                )
                telefono = renderizar_campo_dinamico("telefono", cfg_campos, key_suffix="reg")

            st.markdown("---")

            st.markdown("### 🏠 Ubicación y Vivienda")
            col3, col4 = st.columns(2)
            with col3:
                manzana = renderizar_campo_dinamico("manzana", cfg_campos, key_suffix="reg")
                lbl_fl = cfg_campos.get("fecha_llegada", {}).get("etiqueta", "Fecha de Llegada")
                fecha_llegada = st.date_input(
                    f"{lbl_fl} (DD/MM/YYYY)", 
                    min_value=datetime(1900, 1, 1).date(), 
                    max_value=datetime.now().date(), 
                    value=datetime(2010, 1, 1).date(), 
                    format="DD/MM/YYYY"
                )
            with col4:
                direccion = renderizar_campo_dinamico("direccion", cfg_campos, key_suffix="reg")

            st.markdown("---")

            st.markdown("### ⚕️ Salud y Vulnerabilidad")
            col5, col6 = st.columns(2)
            with col5:
                condicion_salud = renderizar_campo_dinamico("condicion_salud", cfg_campos, key_suffix="reg")
            with col6:
                detalle_salud = renderizar_campo_dinamico("detalle_salud", cfg_campos, key_suffix="reg")

            st.markdown("---")

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
                            d_extra = st.date_input(
                                f"{nom_c} (DD/MM/YYYY):", 
                                min_value=datetime(1900, 1, 1).date(), 
                                max_value=datetime.now().date(), 
                                format="DD/MM/YYYY"
                            )
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
# TAB: ESTADÍSTICAS
# -----------------------------------------------------------------------------
if "📈 Estadísticas" in pestañas:
    with tabs[pestañas.index("📈 Estadísticas")]:
        st.subheader("📈 Resumen Estadístico e Indicadores Demográficos")
        df_stat = cargar_habitantes()
        
        if not df_stat.empty:
            df_stat["edad"] = df_stat["fecha_nac"].apply(calcular_edad)
            
            # Clasificación de rangos de edad
            def clasificar_rango_edad(edad):
                if edad <= 12: return "0 a 12 años"
                elif 13 <= edad <= 15: return "13 a 15 años"
                elif 16 <= edad <= 17: return "16 a 17 años"
                elif 18 <= edad < 60: return "18 a 59 años"
                else: return "60+ años"
            
            df_stat["rango_etario"] = df_stat["edad"].apply(clasificar_rango_edad)
            
            # Filtro por Sexo opcional
            st.markdown("##### 🔍 Filtrar Estadísticas por Sexo")
            opciones_sexo = ["Todos"] + list(df_stat["sexo"].unique())
            sexo_filtro = st.selectbox("Seleccione para filtrar las métricas:", opciones_sexo)
            
            if sexo_filtro != "Todos":
                df_stat_calc = df_stat[df_stat["sexo"] == sexo_filtro]
            else:
                df_stat_calc = df_stat.copy()

            st.markdown("---")
            
            # Métricas
            kpi_e1, kpi_e2, kpi_e3, kpi_e4, kpi_e5 = st.columns(5)
            kpi_e1.metric("Población Seleccionada", len(df_stat_calc))
            kpi_e2.metric("Niños (0 a 12 años)", len(df_stat_calc[df_stat_calc["edad"] <= 12]))
            kpi_e3.metric("Mayores de 15 años", len(df_stat_calc[df_stat_calc["edad"] > 15]))
            kpi_e4.metric("Mayores de 18 años", len(df_stat_calc[df_stat_calc["edad"] >= 18]))
            kpi_e5.metric("Mayores de 60 años", len(df_stat_calc[df_stat_calc["edad"] >= 60]))

            st.markdown("---")
            
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                st.markdown("##### 📊 Rangos de Edad Distribuidos por Sexo")
                df_edad_sexo = df_stat.groupby(["rango_etario", "sexo"]).size().reset_index(name="Cantidad")
                fig_edad_sexo = px.bar(
                    df_edad_sexo, 
                    x="rango_etario", 
                    y="Cantidad", 
                    color="sexo", 
                    barmode="group",
                    title="Comparativa de Edades por Sexo",
                    color_discrete_sequence=px.colors.qualitative.Set2
                )
                st.plotly_chart(fig_edad_sexo, use_container_width=True)

                st.markdown("##### 👥 Distribución Total por Sexo / Género")
                fig_sexo = px.pie(df_stat, names="sexo", hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig_sexo, use_container_width=True)

            with col_g2:
                st.markdown("##### 🏘️ Habitantes por Manzana y Sexo")
                df_manzana_sexo = df_stat.groupby(["manzana", "sexo"]).size().reset_index(name="Habitantes")
                fig_manz_sexo = px.bar(
                    df_manzana_sexo, 
                    x="manzana", 
                    y="Habitantes", 
                    color="sexo", 
                    title="Habitantes por Manzana desglosados por Sexo",
                    color_discrete_sequence=px.colors.qualitative.Safe
                )
                st.plotly_chart(fig_manz_sexo, use_container_width=True)

                st.markdown("##### ⚕️ Condición de Salud por Sexo")
                df_salud_sexo = df_stat[df_stat["condicion_salud"] != "Ninguna"].groupby(["condicion_salud", "sexo"]).size().reset_index(name="Casos")
                if not df_salud_sexo.empty:
                    fig_salud_sex = px.bar(
                        df_salud_sexo, 
                        x="condicion_salud", 
                        y="Casos", 
                        color="sexo", 
                        title="Afectaciones de Salud por Sexo"
                    )
                    st.plotly_chart(fig_salud_sex, use_container_width=True)
                else:
                    st.info("No hay condiciones de salud especiales registradas.")
        else:
            st.info("📊 No hay datos suficientes para generar estadísticas.")

# -----------------------------------------------------------------------------
# TAB: PERSONALIZAR FORMULARIO
# -----------------------------------------------------------------------------
if "✏️ Personalizar Formulario" in pestañas:
    with tabs[pestañas.index("✏️ Personalizar Formulario")]:
        st.subheader("✏️ Configurar Campos y Listas Desplegables del Formulario")
        
        with st.form("form_config_campos_avanzado"):
            for clave, (etiqueta_def, tipo_def, opciones_def) in CAMPOS_BASE_DEFAULT.items():
                st.markdown(f"#### ⚙️ Campo: `{clave}`")
                c_data = cfg_campos.get(clave, {"etiqueta": etiqueta_def, "tipo_control": tipo_def, "opciones": json.loads(opciones_def)})
                
                col_c1, col_c2, col_c3 = st.columns([2, 1.5, 3])
                with col_c1:
                    st.text_input(f"Nombre del campo ({clave}):", value=c_data["etiqueta"], key=f"cfg_lbl_{clave}")
                with col_c2:
                    st.selectbox(
                        "Tipo de control:",
                        ["texto", "desplegable"],
                        index=0 if c_data["tipo_control"] == "texto" else 1,
                        key=f"cfg_tipo_{clave}"
                    )
                with col_c3:
                    str_opciones_actuales = ", ".join(c_data["opciones"])
                    st.text_input(
                        "Opciones (separadas por comas):",
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
                
                st.success("✅ Configuración guardada correctamente.")
                st.rerun()

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
                
                st.markdown("#### 🔑 Permisos:")
                nuevos_permisos = {}
                for perm in LISTA_PERMISOS:
                    val_check = perm_actuales.get(perm, False)
                    nuevos_permisos[perm] = st.checkbox(f"Permitir: `{perm}`", value=val_check)
                
                if st.form_submit_button("💾 Guardar Usuario y Permisos", type="primary", use_container_width=True):
                    target_user = u_username.strip() if user_sel == "-- Crear Nuevo --" else user_sel
                    if target_user:
                        guardar_usuario(target_user, u_pass, u_nombre.strip(), u_rol, nuevos_permisos)
                        st.success(f"✅ Usuario {target_user} guardado.")
                        st.rerun()
                    else:
                        st.error("Ingrese un usuario válido.")

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
# TAB: RESPALDOS Y BORRADO TOTAL
# -----------------------------------------------------------------------------
if "💾 Respaldos y Borrado" in pestañas:
    with tabs[pestañas.index("💾 Respaldos y Borrado")]:
        st.subheader("💾 Gestión de Respaldos e Importación")
        
        col_res1, col_res2 = st.columns(2)
        
        with col_res1:
            st.markdown("### 📤 Exportar Datos General")
            df_exp = cargar_habitantes()
            if not df_exp.empty:
                csv_bytes = df_exp.to_csv(index=False, sep=";", encoding="utf-8-sig")
                st.download_button("📥 Descargar Censo Completo (CSV)", csv_bytes, "censo_comunidad_completo.csv", "text/csv")
                
                buffer_exc = io.BytesIO()
                with pd.ExcelWriter(buffer_exc, engine='openpyxl') as writer:
                    df_exp.to_excel(writer, index=False, sheet_name="Censo")
                st.download_button("📊 Descargar Censo Completo (Excel)", buffer_exc.getvalue(), "censo_comunidad_completo.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

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
        confirmar_borrado = st.checkbox("Confirmo que deseo borrar todos los datos del censo definitivamente.")
        
        if st.button("💣 BORRAR TODO EL CENSO", type="primary", use_container_width=True):
            if confirmar_borrado:
                borrar_todo_el_censo()
                st.success("🔥 Base de datos vaciada completamente.")
                st.rerun()
            else:
                st.warning("Marque la casilla para confirmar.")
