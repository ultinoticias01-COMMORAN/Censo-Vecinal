import streamlit as st
import pandas as pd
import json
import os

# Archivo local para persistir la configuración de campos personalizados
CONFIG_FILE = "campos_personalizados.json"
DATA_FILE = "habitantes.csv"

# --- FUNCIONES DE SOPORTE PARA CAMPOS PERSONALIZADOS ---
def cargar_campos():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return ["Teléfono", "Ocupación"]  # Campos por defecto

def guardar_campos(campos):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(campos, f, ensure_ascii=False, indent=4)

# --- FUNCIONES DE SOPORTE PARA DATOS DE HABITANTES ---
def cargar_habitantes():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    return pd.DataFrame(columns=["Nombre", "Cédula", "Rol", "Jefe_Hogar_Cedula"])

def guardar_habitante(nuevo_registro):
    df = cargar_habitantes()
    df = pd.concat([df, pd.DataFrame([nuevo_registro])], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

# --- INTERFAZ PRINCIPAL ---
st.set_page_config(page_title="Censo Digital - Gestión de Habitantes", layout="wide")
st.title("🏛️ Censo Digital - Control de Núcleos Familiares")

menu = st.sidebar.selectbox("Selecciona una opción", ["Registro de Habitantes", "Gestión de Campos Personalizados", "Ver Registros"])

# -----------------------------------------------------------------------------
# 1. GESTIÓN DE CAMPOS PERSONALIZADOS
# -----------------------------------------------------------------------------
if menu == "Gestión de Campos Personalizados":
    st.header("⚙️ Configuración de Campos Personalizados")
    st.write("Agrega, edita o elimina campos dinámicos para el formulario de registro.")

    campos = cargar_campos()

    # Visualizar y Eliminar / Editar
    st.subheader("Campos Actuales")
    
    col1, col2 = st.columns([3, 1])
    
    campos_a_conservar = []
    for idx, campo in enumerate(campos):
        col_nombre, col_btn = st.columns([3, 1])
        with col_nombre:
            nuevo_nombre = st.text_input(f"Campo #{idx+1}", value=campo, key=f"campo_{idx}")
            campos_a_conservar.append(nuevo_nombre)
        with col_btn:
            st.write("") # Espaciador
            st.write("")
            if st.button("❌ Eliminar", key=f"del_{idx}"):
                campos.pop(idx)
                guardar_campos(campos)
                st.rerun()

    # Guardar cambios en nombres editados
    if st.button("💾 Guardar Cambios en Nombres"):
        guardar_campos(campos_a_conservar)
        st.success("¡Campos actualizados correctamente!")
        st.rerun()

    st.markdown("---")
    # Agregar Nuevo Campo
    st.subheader("➕ Agregar Nuevo Campo")
    nuevo_campo_nombre = st.text_input("Nombre del nuevo campo (Ej: Discapacidad, Nivel Educativo)")
    if st.button("Agregar Campo"):
        if nuevo_campo_nombre and nuevo_campo_nombre not in campos:
            campos.append(nuevo_campo_nombre)
            guardar_campos(campos)
            st.success(f"Campo '{nuevo_campo_nombre}' agregado con éxito.")
            st.rerun()
        elif nuevo_campo_nombre in campos:
            st.warning("Ese campo ya existe.")

# -----------------------------------------------------------------------------
# 2. VINCULAR HABITANTES AL NÚCLEO FAMILIAR (REGISTRO)
# -----------------------------------------------------------------------------
elif menu == "Registro de Habitantes":
    st.header("👤 Registro de Habitante")

    df_habitantes = cargar_habitantes()
    campos_dinamicos = cargar_campos()

    with st.form("form_registro", clear_on_submit=True):
        st.subheader("Datos Básicos")
        nombre = st.text_input("Nombre Completo")
        cedula = st.text_input("Cédula / Documento de Identidad")

        st.subheader("Condición Familiar")
        rol = st.radio(
            "Seleccione la condición del habitante en el hogar:",
            ["Jefe de hogar", "Núcleo familiar"],
            horizontal=True
        )

        # Menú desplegable dinámico para el Jefe de Hogar
        jefe_seleccionado = None
        if rol == "Núcleo familiar":
            # Filtrar solo las personas registradas como 'Jefe de hogar'
            jefes_df = df_habitantes[df_habitantes["Rol"] == "Jefe de hogar"]
            
            if not jefes_df.empty:
                opciones_jefes = {
                    f"{row['Nombre']} (C.I. {row['Cédula']})": row['Cédula'] 
                    for _, row in jefes_df.iterrows()
                }
                jefe_label = st.selectbox(
                    "Seleccione el Jefe de Hogar al que pertenece:",
                    options=list(opciones_jefes.keys())
                )
                jefe_seleccionado = opciones_jefes[jefe_label]
            else:
                st.warning("⚠️ No hay Jefes de hogar registrados aún. Debe registrar un Jefe de hogar primero.")

        # Renderizado de Campos Dinámicos
        valores_dinamicos = {}
        if campos_dinamicos:
            st.subheader("Información Adicional (Campos Personalizados)")
            for campo in campos_dinamicos:
                valores_dinamicos[campo] = st.text_input(f"{campo}")

        # Botón para registrar
        submitted = st.form_submit_button("Guardar Habitante")

        if submitted:
            if not nombre or not cedula:
                st.error("Por favor, ingrese al menos el nombre y la cédula.")
            elif rol == "Núcleo familiar" and not jefe_seleccionado:
                st.error("Debe seleccionar un Jefe de Hogar válido para enlazar este habitante.")
            else:
                registro = {
                    "Nombre": nombre,
                    "Cédula": cedula,
                    "Rol": rol,
                    "Jefe_Hogar_Cedula": jefe_seleccionado if rol == "Núcleo familiar" else cedula
                }
                # Unir campos estáticos con los personalizados
                registro.update(valores_dinamicos)
                guardar_habitante(registro)
                st.success(f"¡Habitante **{nombre}** registrado con éxito!")

# -----------------------------------------------------------------------------
# 3. VISUALIZACIÓN DE REGISTROS
# -----------------------------------------------------------------------------
elif menu == "Ver Registros":
    st.header("📋 Lista de Habitantes Registrados")
    df = cargar_habitantes()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No hay habitantes registrados todavía.")
