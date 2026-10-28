"""Ponto de entrada do Atlas Eleitoral na navegação automática Streamlit.

Executa a página de apuração original no MESMO contexto do script principal.
Não há st.navigation/st.Page: isso preserva o ciclo de vida do st_folium e
os eventos de zoom/clique existentes. Usar somente via Makefile.
"""
from pathlib import Path

# O código e os callbacks existentes ficam centralizados em app.py, inalterado.
original = Path(__file__).resolve().with_name("app.py")
exec(compile(original.read_text(encoding="utf-8"), str(original), "exec"), globals())
