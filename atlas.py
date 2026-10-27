"""Atlas Eleitoral — navegação explícita, sem renomear o app histórico.

A execução permanece exclusivamente pelo Makefile. Este arquivo é o entrypoint
Streamlit; as páginas mantêm lógica, estilos e controles próprios.
"""
import streamlit as st

pages = [
    st.Page("app.py", title="Atlas Eleitoral", icon="🗳️", default=True),
    st.Page("pages/1_Deltas_e_viradas.py", title="Deltas e viradas", icon="📈"),
]
st.navigation(pages).run()
