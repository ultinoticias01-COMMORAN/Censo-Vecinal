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

# Mapeo de nombres de columnas internas de BD <-> Nombres amigables para exportación
COLUMNAS_ORDENADAS = [
    "cedula",
    "nombre",
    "apellido",
    "fecha_nacimiento",
    "fecha_llegada",
    "direccion",
    "manzana",
    "telefono",
    "sexo",
    "condicion_salud",
    "detalle_salud",
    "campos_adicionales"
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
    
    # MIGRACIÓN AUTOMÁTICA DE COLUMNAS NUEVAS
    cursor.execute("PRAGMA table_info(habitantes)")
    columnas = [column[1] for column in cursor.fetchall()]
    
    nuevas_cols = {
        "sexo": "TEXT DEFAULT 'No especificado'",
        "condicion_salud": "TEXT DEFAULT 'Ninguna'",
        "detalle_salud": "TEXT DEFAULT ''",
        "campos_adicionales": "TEXT DEFAULT '{}'"
    }
    
    for col_nombre, col_tipo in nuevas_cols.items():
        if col_nombre not in columnas:
            cursor.execute(f"ALTER TABLE habitantes ADD COLUMN {col_nombre} {col_tipo}")
    
    # Tabla de Usuarios y Roles
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            username TEXT PRIMARY KEY,
            password TEXT,
            nombre_completo TEXT,
            rol TEXT
        )
    """)
    
    # Tabla de Bitácora / Historial
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
    
    # Tabla de Configuración de Campos Personalizados
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_campos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_campo TEXT UNIQUE,
            tipo_campo TEXT
        )
    """)
    
    # Usuarios por defecto
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?)", ("master", "master123", "Usuario Master", "Master"))
        cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?)", ("admin", "admin123", "Administrador Principal", "Administrador"))
        cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?)", ("user", "user123", "Visualizador Invitado", "Visualizador"))
    
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# 2. FUNCIONES DE BASE DE DATOS
# -----------------------------------------------------------------------------

def cargar_habitantes():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM habitantes", conn)
    conn.close()
    
    # Asegurar valores por defecto en datos cargados
    df["sexo"] = df["sexo"].fillna("No especificado")
    df["condicion_salud"] = df["condicion_salud"].fillna("Ninguna")
    df["detalle_salud"] = df["detalle_salud"].fillna("")
    df["campos_adicionales"] = df["campos_adicionales"].fillna("{}")
    return df

def obtener_df_exportable(df):
    """Devuelve un DataFrame adaptado con las columnas solicitadas"""
    if df.empty:
        return pd.DataFrame(columns=COLUMNAS_ORDENADAS)
    
    df_exp = df.copy()
    df_exp = df_exp.rename(columns={
        "nombres": "nombre",
        "apellidos": "apellido",
        "fecha_nac": "fecha_nacimiento"
    })
    
    for col in COLUMNAS_ORDENADAS:
        if col not in df_exp.columns:
            df_exp[col] = ""
            
    return df_exp[COLUMNAS_ORDENADAS]

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

def eliminar_habitante(cedula):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM habitantes WHERE cedula = ?", (cedula,))
    cursor.execute("DELETE FROM bitacora_documentos WHERE cedula = ?", (cedula,))
    conn.commit()
    conn.close()

# --- Gestión de Campos Personalizados Dinámicos ---
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

def eliminar_campo_personalizado(nombre):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM configuracion_campos WHERE nombre_campo = ?", (nombre,))
    conn.commit()
    conn.close()

# --- Usuarios y Autenticación ---
def verificar_login(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, nombre_completo, rol FROM usuarios WHERE username = ? AND password = ?", (username, password))
    user = cursor.fetchone()
    conn.close()
    return user

def cargar_usuarios():
    conn = get_connection()
    df = pd.read_sql_query("SELECT username, nombre_completo, rol FROM usuarios", conn)
    conn.close()
    return df

def guardar_usuario(username, password, nombre_completo, rol):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?)", (username, password, nombre_completo, rol))
    conn.commit()
    conn.close()

def eliminar_usuario(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE username = ?", (username,))
    conn.commit()
    conn.close()

# --- Bitácora ---
def registrar_documento(cedula, tipo_doc, descripcion, emitido_por):
    conn = get_connection()
    cursor = conn.cursor()
    fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO bitacora_documentos (cedula, tipo_documento, descripcion, fecha_emision, emitido_por)
        VALUES (?, ?, ?, ?, ?)
    """, (cedula, tipo_doc, descripcion, fecha_hoy, emitido_por))
    conn.commit()
    conn.close()

def cargar_bitacora(cedula=None):
    conn = get_connection()
    if cedula:
        query = "SELECT * FROM bitacora_documentos WHERE cedula = ? ORDER BY id DESC"
        df = pd.read_sql_query(query, conn, params=(cedula,))
    else:
        query = """
            SELECT b.id, b.cedula, h.nombres || ' ' || h.apellidos AS habitante, 
                   b.tipo_documento, b.descripcion, b.fecha_emision, b.emitido_por
            FROM bitacora_documentos b
            LEFT JOIN habitantes h ON b.cedula = h.cedula
            ORDER BY b.id DESC
        """
        df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# -----------------------------------------------------------------------------
# 3. CÁLCULOS
# -----------------------------------------------------------------------------
def calcular_edad(fecha_nac_str):
    try:
        fecha_nac = datetime.strptime(str(fecha_nac_str).split()[0], "%Y-%m-%d").date()
        hoy = datetime.now().date()
        return hoy.year - fecha_nac.year - ((hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day))
    except:
        return 0

def calcular_tiempo_comunidad(fecha_llegada_str):
    try:
        fecha_llegada = datetime.strptime(str(fecha_llegada_str).split()[0], "%Y-%m-%d").date()
        hoy = datetime.now().date()
        años = hoy.year - fecha_llegada.year
        meses = hoy.month - fecha_llegada.month
        if hoy.day < fecha_llegada.day:
            meses -= 1
        if meses < 0:
            años -= 1
            meses += 12
        return f"{años} años, {meses} meses"
    except:
        return "N/A"

# -----------------------------------------------------------------------------
# 4. CONTROL DE SESIÓN Y LOGIN
# -----------------------------------------------------------------------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None
    st.session_state.rol_actual = None

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
                    st.session_state.usuario_actual = user_data[1]
                    st.session_state.username = user_data[0]
                    st.session_state.rol_actual = user_data[2]
                    st.success(f"¡Bienvenido {user_data[1]}!")
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas.")
    st.stop()

# -----------------------------------------------------------------------------
# 5. BARRA LATERAL (MENÚ, PERMISOS Y GESTOR DE CAMPOS)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("👤 Perfil de Usuario")
    st.write(f"**Usuario:** {st.session_state.usuario_actual}")
    st.write(f"**Rol:** `{st.session_state.rol_actual}`")
    
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.session_state.usuario_actual = None
        st.session_state.rol_actual = None
        st.rerun()
        
    st.markdown("---")
    
    # Sección para agregar dynamic fields
    if st.session_state.rol_actual in ["Master", "Administrador"]:
        st.subheader("➕ Agregar Nueva Pestaña / Campo")
        nuevo_nom = st.text_input("Nombre de Variable (ej. Ocupación):")
        nuevo_tipo = st.selectbox("Tipo de Dato:", ["Texto", "Número", "Fecha"])
        
        if st.button("Guardar Nueva Variable", use_container_width=True):
            if nuevo_nom.strip():
                agregar_campo_personalizado(nuevo_nom.strip(), nuevo_tipo)
                st.success("Variable agregada con éxito.")
                st.rerun()
            else:
                st.warning("Escriba un nombre válido.")

    st.caption("Sistema de Censo Comunitario v2.5")

# Permisos
ROL = st.session_state.rol_actual
ES_MASTER = ROL == "Master"
ES_ADMIN_OR_MASTER = ROL in ["Master", "Administrador"]

# -----------------------------------------------------------------------------
# 6. INTERFAZ PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🏡 Censo Digital de la Comunidad")

pestañas = ["📊 Consultar y Filtros", "📈 Estadísticas (Gráficos)"]

if ES_ADMIN_OR_MASTER:
    pestañas.insert(0, "📝 Registrar Habitante")
    pestañas.append("📄 Bitácora de Documentos")
    pestañas.append("⚙️ Editar / Eliminar")

if ES_MASTER:
    pestañas.append("👥 Gestión de Usuarios")
    pestañas.append("💾 Respaldos e Importación")

tabs = st.tabs(pestañas)

# -----------------------------------------------------------------------------
# TAB: REGISTRAR HABITANTE (Master, Administrador)
# -----------------------------------------------------------------------------
if ES_ADMIN_OR_MASTER and "📝 Registrar Habitante" in pestañas:
    with tabs[pestañas.index("📝 Registrar Habitante")]:
        st.subheader("Formulario de Registro de Habitante")
        
        # Pestañas internas del formulario
        tab_p1, tab_p2, tab_p3, tab_p4 = st.tabs([
            "👤 Datos Personales", 
            "🏠 Ubicación y Vivienda", 
            "⚕️ Salud y Vulnerabilidad", 
            "➕ Campos Adicionales"
        ])
        
        datos_extra = {}
        
        with st.form("form_censo_pestañas", clear_on_submit=True):
            with tab_p1:
                st.markdown("##### Información Personal e Identificación")
                col1, col2 = st.columns(2)
                with col1:
                    cedula = st.text_input("Cédula de Identidad*")
                    nombres = st.text_input("Nombres*")
                    apellidos = st.text_input("Apellidos*")
                with col2:
                    sexo = st.selectbox("Sexo / Género*", ["Femenino", "Masculino", "Otro"])
                    fecha_nac = st.date_input("Fecha de Nacimiento", min_value=datetime(1920, 1, 1), max_value=datetime.now())
                    telefono = st.text_input("Teléfono de Contacto")

            with tab_p2:
                st.markdown("##### Ubicación dentro de la Comunidad")
                col3, col4 = st.columns(2)
                with col3:
                    manzana = st.text_input("Manzana / Sector")
                    fecha_llegada = st.date_input("Fecha de Llegada a la Comunidad", min_value=datetime(1950, 1, 1), max_value=datetime.now())
                with col4:
                    direccion = st.text_area("Dirección Detallada de Habitación")

            with tab_p3:
                st.markdown("##### Condición de Salud y Bienestar")
                condicion_salud = st.selectbox(
                    "Condición / Afectación de Salud",
                    ["Ninguna", "Enfermedad Crónica", "Discapacidad", "Adulto Mayor Encamado", "Embarazada", "Población de Riesgo", "Otra"]
                )
                detalle_salud = st.text_input("Detalles adicionales o especificación de salud:")

            with tab_p4:
                st.markdown("##### Variables y Pestañas Personalizadas")
                campos_config = cargar_campos_personalizados()
                if campos_config:
                    for nom_c, tipo_c in campos_config:
                        if tipo_c == "Texto":
                            datos_extra[nom_c] = st.text_input(f"{nom_c}:")
                        elif tipo_c == "Número":
                            datos_extra[nom_c] = st.number_input(f"{nom_c}:", value=0)
                        elif tipo_c == "Fecha":
                            datos_extra[nom_c] = st.date_input(f"{nom_c}:").strftime("%Y-%m-%d")
                else:
                    st.info("No hay variables personalizadas configuradas. Puedes agregarlas desde el menú lateral.")

            st.markdown("---")
            guardar = st.form_submit_button("💾 Guardar Registro de Habitante", type="primary", use_container_width=True)

        if guardar:
            if nombres.strip() and apellidos.strip() and cedula.strip():
                json_extra = json.dumps(datos_extra, ensure_ascii=False)
                datos = (
                    cedula.strip(), nombres.strip(), apellidos.strip(), sexo,
                    fecha_nac.strftime("%Y-%m-%d"), fecha_llegada.strftime("%Y-%m-%d"),
                    direccion.strip(), manzana.strip(), telefono.strip(),
                    condicion_salud, detalle_salud.strip(), json_extra
                )
                guardar_habitante(datos)
                st.success(f"✅ ¡Habitante {nombres} {apellidos} guardado exitosamente!")
            else:
                st.error("⚠️ Ingrese los campos obligatorios marcados con (*).")

# -----------------------------------------------------------------------------
# TAB: CONSULTAR Y FILTROS (Todos)
# -----------------------------------------------------------------------------
with tabs[pestañas.index("📊 Consultar y Filtros")]:
    st.subheader("Consulta General de Habitantes")
    df = cargar_habitantes()
    
    if not df.empty:
        df["Edad"] = df["fecha_nac"].apply(calcular_edad)
        df["Tiempo Comunidad"] = df["fecha_llegada"].apply(calcular_tiempo_comunidad)
        
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1:
            busqueda = st.text_input("Buscar por Nombre, Apellido o Cédula")
        with col_f2:
            sector_sel = st.selectbox("Manzana / Sector", ["Todos"] + list(df["manzana"].dropna().unique()))
        with col_f3:
            sexo_sel = st.selectbox("Filtrar por Sexo", ["Todos"] + list(df["sexo"].dropna().unique()))
        with col_f4:
            salud_sel = st.selectbox("Filtrar por Salud", ["Todos"] + list(df["condicion_salud"].dropna().unique()))

        df_filtrado = df.copy()
        if busqueda:
            df_filtrado = df_filtrado[
                df_filtrado["nombres"].str.contains(busqueda, case=False, na=False) |
                df_filtrado["apellidos"].str.contains(busqueda, case=False, na=False) |
                df_filtrado["cedula"].str.contains(busqueda, case=False, na=False)
            ]
        if sector_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["manzana"] == sector_sel]
        if sexo_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["sexo"] == sexo_sel]
        if salud_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["condicion_salud"] == salud_sel]

        # Métricas
        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Personas", len(df_filtrado))
        m2.metric("Promedio Edad", f"{df_filtrado['Edad'].mean():.1f} años" if len(df_filtrado) > 0 else "N/A")
        m3.metric("Femenino", len(df_filtrado[df_filtrado["sexo"] == "Femenino"]))
        m4.metric("Con Afección de Salud", len(df_filtrado[df_filtrado["condicion_salud"] != "Ninguna"]))
        st.markdown("---")

        st.dataframe(df_filtrado, use_container_width=True, hide_index=True)
        
        df_exp_filtrado = obtener_df_exportable(df_filtrado)
        
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            csv_data = df_exp_filtrado.to_csv(index=False, sep=";", encoding="utf-8-sig")
            st.download_button(
                label="📥 Exportar Tabla Actual (CSV por Columnas)",
                data=csv_data,
                file_name="censo_filtrado.csv",
                mime="text/csv"
            )
        with col_exp2:
            buffer_exc = io.BytesIO()
            with pd.ExcelWriter(buffer_exc, engine='openpyxl') as writer:
                df_exp_filtrado.to_excel(writer, index=False, sheet_name="Habitantes")
            
            st.download_button(
                label="📊 Exportar Tabla Actual (Excel)",
                data=buffer_exc.getvalue(),
                file_name="censo_filtrado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.info("No hay habitantes cargados en la base de datos.")

# -----------------------------------------------------------------------------
# TAB: ESTADÍSTICAS Y GRÁFICOS (Todos)
# -----------------------------------------------------------------------------
with tabs[pestañas.index("📈 Estadísticas (Gráficos)")]:
    st.subheader("Análisis Demográfico y Condiciones de Salud")
    df_stat = cargar_habitantes()
    
    if not df_stat.empty:
        df_stat["Edad"] = df_stat["fecha_nac"].apply(calcular_edad)
        
        st.markdown("##### 🎯 Filtro por Rango de Edad")
        min_e, max_e = int(df_stat["Edad"].min()), int(df_stat["Edad"].max())
        max_e = max_e if max_e > min_e else min_e + 1
        
        rango_edad = st.slider("Selecciona el Rango de Edad que deseas analizar:", min_value=0, max_value=100, value=(min_e, max_e))
        df_range = df_stat[(df_stat["Edad"] >= rango_edad[0]) & (df_stat["Edad"] <= rango_edad[1])]
        
        st.write(f"Mostrando **{len(df_range)}** personas registradas.")
        
        if not df_range.empty:
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                fig_sexo = px.pie(
                    df_range, 
                    names="sexo", 
                    title="Distribución por Sexo",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Set2
                )
                fig_sexo.update_traces(textinfo="percent+label+value")
                st.plotly_chart(fig_sexo, use_container_width=True)
                
            with col_g2:
                fig_salud = px.pie(
                    df_range, 
                    names="condicion_salud", 
                    title="Distribución por Condiciones de Salud",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                fig_salud.update_traces(textinfo="percent+label+value")
                st.plotly_chart(fig_salud, use_container_width=True)
        else:
            st.warning("No hay registros en el rango seleccionado.")
    else:
        st.info("No hay datos para generar estadísticas.")

# -----------------------------------------------------------------------------
# TAB: BITÁCORA DE DOCUMENTOS (Master, Administrador)
# -----------------------------------------------------------------------------
if ES_ADMIN_OR_MASTER and "📄 Bitácora de Documentos" in pestañas:
    with tabs[pestañas.index("📄 Bitácora de Documentos")]:
        st.subheader("Emisión y Bitácora de Cartas / Documentos")
        
        df_hab = cargar_habitantes()
        if not df_hab.empty:
            col_b1, col_b2 = st.columns([1, 2])
            
            with col_b1:
                st.markdown("### 📝 Registrar Nuevo Documento")
                cedula_sel = st.selectbox("Seleccionar Habitante (Cédula):", df_hab["cedula"].unique())
                
                hab_info = df_hab[df_hab["cedula"] == cedula_sel].iloc[0]
                st.info(f"**Habitante:** {hab_info['nombres']} {hab_info['apellidos']}")
                
                tipo_doc = st.selectbox("Tipo de Documento:", [
                    "Carta de Residencia", 
                    "Carta de Buena Conducta", 
                    "Carta de Aval", 
                    "Constancia de Constatación", 
                    "Otro"
                ])
                descripcion_doc = st.text_area("Detalles / Motivo:")
                
                if st.button("💾 Guardar en Bitácora", use_container_width=True):
                    if descripcion_doc.strip():
                        registrar_documento(cedula_sel, tipo_doc, descripcion_doc.strip(), st.session_state.usuario_actual)
                        st.success("✅ Registro guardado en bitácora.")
                        st.rerun()
                    else:
                        st.warning("Escriba una descripción.")
            
            with col_b2:
                st.markdown("### 📜 Historial de Emisión")
                filtro_b_cedula = st.text_input("Filtrar historial por Cédula:")
                
                df_bitacora = cargar_bitacora(filtro_b_cedula.strip() if filtro_b_cedula else None)
                if not df_bitacora.empty:
                    st.dataframe(df_bitacora, use_container_width=True, hide_index=True)
                else:
                    st.info("No hay documentos registrados.")
        else:
            st.info("Debe registrar habitantes primero.")

# -----------------------------------------------------------------------------
# TAB: EDITAR / ELIMINAR REGISTROS (Master, Administrador)
# -----------------------------------------------------------------------------
if ES_ADMIN_OR_MASTER and "⚙️ Editar / Eliminar" in pestañas:
    with tabs[pestañas.index("⚙️ Editar / Eliminar")]:
        st.subheader("Modificar / Actualizar Habitantes")
        df_edit = cargar_habitantes()
        
        if not df_edit.empty:
            cedula_buscar = st.selectbox("Seleccione Cédula del habitante:", df_edit["cedula"].unique())
            hab = df_edit[df_edit["cedula"] == cedula_buscar].iloc[0]
            
            # Cargar datos JSON dinámicos si existen
            try:
                dict_dyn = json.loads(hab["campos_adicionales"])
            except:
                dict_dyn = {}

            tab_e1, tab_e2, tab_e3, tab_e4 = st.tabs(["👤 Datos Personales", "🏠 Ubicación", "⚕️ Salud", "➕ Personalizados"])

            with st.form("form_edit_tabs"):
                with tab_e1:
                    e_nombres = st.text_input("Nombres", value=hab['nombres'])
                    e_apellidos = st.text_input("Apellidos", value=hab['apellidos'])
                    
                    opciones_sexo = ["Femenino", "Masculino", "Otro"]
                    val_sexo = hab['sexo'] if hab['sexo'] in opciones_sexo else "Femenino"
                    e_sexo = st.selectbox("Sexo", opciones_sexo, index=opciones_sexo.index(val_sexo))
                    e_telefono = st.text_input("Teléfono", value=hab['telefono'])

                with tab_e2:
                    fn_dt = datetime.strptime(str(hab['fecha_nac']).split()[0], "%Y-%m-%d").date()
                    fl_dt = datetime.strptime(str(hab['fecha_llegada']).split()[0], "%Y-%m-%d").date()
                    
                    e_fn = st.date_input("Fecha Nacimiento", value=fn_dt)
                    e_fl = st.date_input("Fecha Llegada", value=fl_dt)
                    e_manzana = st.text_input("Manzana / Sector", value=hab['manzana'])
                    e_direccion = st.text_area("Dirección", value=hab['direccion'])

                with tab_e3:
                    opciones_salud = ["Ninguna", "Enfermedad Crónica", "Discapacidad", "Adulto Mayor Encamado", "Embarazada", "Población de Riesgo", "Otra"]
                    val_salud = hab['condicion_salud'] if hab['condicion_salud'] in opciones_salud else "Ninguna"
                    e_condicion_salud = st.selectbox("Condición de Salud", opciones_salud, index=opciones_salud.index(val_salud))
                    e_detalle_salud = st.text_input("Detalle Médicos", value=hab['detalle_salud'])

                with tab_e4:
                    e_dict_extra = {}
                    campos_cfg = cargar_campos_personalizados()
                    for nom_c, tipo_c in campos_cfg:
                        val_prev = dict_dyn.get(nom_c, "")
                        if tipo_c == "Texto":
                            e_dict_extra[nom_c] = st.text_input(nom_c, value=str(val_prev))
                        elif tipo_c == "Número":
                            e_dict_extra[nom_c] = st.number_input(nom_c, value=int(val_prev) if str(val_prev).isdigit() else 0)
                        elif tipo_c == "Fecha":
                            e_dict_extra[nom_c] = st.text_input(f"{nom_c} (YYYY-MM-DD)", value=str(val_prev))

                btn_mod = st.form_submit_button("💾 Actualizar Habitante", type="primary", use_container_width=True)
                
                if btn_mod:
                    datos_mod = (
                        cedula_buscar, e_nombres, e_apellidos, e_sexo,
                        e_fn.strftime("%Y-%m-%d"), e_fl.strftime("%Y-%m-%d"),
                        e_direccion, e_manzana, e_telefono,
                        e_condicion_salud, e_detalle_salud, json.dumps(e_dict_extra, ensure_ascii=False)
                    )
                    guardar_habitante(datos_mod)
                    st.success("✅ Registro actualizado.")
                    st.rerun()

            st.markdown("---")
            if st.button(f"🗑️ Eliminar a {hab['nombres']} {hab['apellidos']}", type="primary"):
                eliminar_habitante(cedula_buscar)
                st.warning("Registro eliminado con éxito.")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB: GESTIÓN DE USUARIOS (Solo Master)
# -----------------------------------------------------------------------------
if ES_MASTER and "👥 Gestión de Usuarios" in pestañas:
    with tabs[pestañas.index("👥 Gestión de Usuarios")]:
        st.subheader("Administración de Usuarios del Sistema")
        
        col_u1, col_u2 = st.columns([1, 2])
        
        with col_u1:
            st.markdown("### ➕ Crear o Modificar Usuario")
            with st.form("form_user"):
                u_user = st.text_input("Usuario (Username)")
                u_pass = st.text_input("Contraseña", type="password")
                u_name = st.text_input("Nombre Completo")
                u_rol = st.selectbox("Rol", ["Visualizador", "Administrador", "Master"])
                
                btn_save_user = st.form_submit_button("Guardar Usuario", use_container_width=True)
                
                if btn_save_user:
                    if u_user.strip() and u_pass.strip():
                        guardar_usuario(u_user.strip(), u_pass.strip(), u_name.strip(), u_rol)
                        st.success(f"✅ Usuario `{u_user}` guardado correctamente.")
                        st.rerun()
                    else:
                        st.error("Ingrese usuario y contraseña.")
        
        with col_u2:
            st.markdown("### 📋 Usuarios Registrados")
            df_users = cargar_usuarios()
            st.dataframe(df_users, use_container_width=True, hide_index=True)
            
            st.markdown("---")
            u_del = st.selectbox("Seleccionar usuario a eliminar:", [u for u in df_users["username"] if u != "master"])
            if st.button("🗑️ Eliminar Usuario", type="primary"):
                eliminar_usuario(u_del)
                st.success("Usuario eliminado.")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB: RESPALDOS E IMPORTACIÓN (Solo Master)
# -----------------------------------------------------------------------------
if ES_MASTER and "💾 Respaldos e Importación" in pestañas:
    with tabs[pestañas.index("💾 Respaldos e Importación")]:
        st.subheader("Respaldos y Carga Masiva")
        
        col_db1, col_db2 = st.columns(2)
        
        with col_db1:
            st.markdown("### 📤 Exportar Habitantes")
            df_exp_full = obtener_df_exportable(cargar_habitantes())
            
            csv_exp_full = df_exp_full.to_csv(index=False, sep=";", encoding="utf-8-sig")
            st.download_button("📥 Descargar Censo Completo (CSV)", csv_exp_full, "habitantes.csv", "text/csv")
            
            buffer_full = io.BytesIO()
            with pd.ExcelWriter(buffer_full, engine='openpyxl') as writer:
                df_exp_full.to_excel(writer, index=False, sheet_name="Habitantes")
                
            st.download_button(
                "📊 Descargar Censo Completo (Excel .xlsx)",
                buffer_full.getvalue(),
                "habitantes.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            st.markdown("---")
            st.markdown("### 💾 Respaldo Base de Datos")
            with open(DB_FILE, "rb") as f:
                bytes_db = f.read()
            st.download_button("💾 Descargar Base de Datos (.db)", bytes_db, "censo_backup.db", "application/octet-stream")

        with col_db2:
            st.markdown("### 📥 Importar Habitantes (CSV o Excel)")
            
            uploaded_file = st.file_uploader("Subir archivo de habitantes", type=["csv", "xlsx"])
            if uploaded_file is not None:
                if st.button("📥 Importar Habitantes al Sistema"):
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
                        renombres = {"nombres": "nombre", "apellidos": "apellido", "fecha_nac": "fecha_nacimiento"}
                        df_imp = df_imp.rename(columns=renombres)

                        registros_guardados = 0
                        for _, row in df_imp.iterrows():
                            guardar_habitante((
                                str(row.get("cedula", "")).strip(),
                                str(row.get("nombre", "")).strip(),
                                str(row.get("apellido", "")).strip(),
                                str(row.get("sexo", "No especificado")).strip(),
                                str(row.get("fecha_nacimiento", "")).strip(),
                                str(row.get("fecha_llegada", "")).strip(),
                                str(row.get("direccion", "")).strip(),
                                str(row.get("manzana", "")).strip(),
                                str(row.get("telefono", "")).strip(),
                                str(row.get("condicion_salud", "Ninguna")).strip(),
                                str(row.get("detalle_salud", "")).strip(),
                                str(row.get("campos_adicionales", "{}")).strip()
                            ))
                            registros_guardados += 1
                        st.success(f"✅ ¡Se importaron e insertaron {registros_guardados} habitantes!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al importar archivo: {e}")

            st.markdown("---")
            st.markdown("#### Restaurar Base de Datos (.db)")
            uploaded_db = st.file_uploader("Subir archivo .db", type=["db"])
            if uploaded_db is not None:
                if st.button("⚠️ Confirmar Reemplazo de BD"):
                    with open(DB_FILE, "wb") as f:
                        f.write(uploaded_db.getbuffer())
                    st.success("✅ Base de datos restaurada.")
                    st.rerun()
