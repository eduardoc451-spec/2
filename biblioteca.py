import os
import streamlit as st

# Nome da pasta raiz no sistema de arquivos
RAIZ_BIBLIOTECA = "biblioteca"

# Lista de dimensões/pastas principais oficiais do projeto
PASTAS_PRINCIPAIS = [
    "i-fiscal",
    "i-plan",
    "i-educ",
    "i-saúde",
    "i-govti",
    "i-cidade",
    "i-amb",
    "relatorios tce",
    "leis e decretos",
    "provas fotográficas",
    "diversos"
]

# Lista de anos obrigatórios para as subpastas
ANOS_DISPONIVEIS = ["2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"]

def inicializar_estrutura_pastas():
    """Garante que a árvore de diretórios física exista com as subpastas de anos."""
    if not os.path.exists(RAIZ_BIBLIOTECA):
        os.makedirs(RAIZ_BIBLIOTECA)
        
    for pasta in PASTAS_PRINCIPAIS:
        caminho_pasta = os.path.join(RAIZ_BIBLIOTECA, pasta)
        if not os.path.exists(caminho_pasta):
            os.makedirs(caminho_pasta)
            
        for ano in ANOS_DISPONIVEIS:
            caminho_ano = os.path.join(caminho_pasta, ano)
            if not os.path.exists(caminho_ano):
                os.makedirs(caminho_ano)

# Inicializa as pastas no HD
inicializar_estrutura_pastas()


def gerenciar_upload_e_arquivos():
    """Painel de controle em formato de árvore de arquivos com botão manual de atualização."""
    
    # Força o recarregamento limpo do Streamlit
    col_titulo, col_btn_refresh = st.columns([0.7, 0.3])
    with col_titulo:
        st.markdown("### 🔍 Varredura e Busca Rápida")
    with col_btn_refresh:
        if st.button("🔄 Atualizar Biblioteca", use_container_width=True, key="global_refresh_btn"):
            st.rerun()

    busca = st.text_input("Procurar arquivo em qualquer diretório ou ano:", placeholder="Digite o nome do documento...").strip().lower()

    if busca:
        st.markdown(f"📂 *Resultados da pesquisa para:* `{busca}`")
        encontrou_algo = False
        
        for pasta_p in PASTAS_PRINCIPAIS:
            for ano_s in ANOS_DISPONIVEIS:
                dir_busca = os.path.join(RAIZ_BIBLIOTECA, pasta_p, ano_s)
                if os.path.exists(dir_busca):
                    for arq in os.listdir(dir_busca):
                        if not arq.startswith('.') and busca in arq.lower():
                            encontrou_algo = True
                            caminho_arq = os.path.join(dir_busca, arq)
                            
                            with open(caminho_arq, "rb") as f:
                                b_conteudo = f.read()
                                
                            col_txt, col_op = st.columns([0.7, 0.3])
                            with col_txt:
                                st.markdown(f"📄 **{arq}** \n↳ Local: `{pasta_p}` / Ano: `{ano_s}`")
                            with col_op:
                                sub_col1, sub_col2 = st.columns(2)
                                with sub_col1:
                                    st.download_button("📥 Abrir", data=b_conteudo, file_name=arq, key=f"s_down_{pasta_p}_{ano_s}_{arq}")
                                with sub_col2:
                                    if st.button("❌", key=f"s_del_{pasta_p}_{ano_s}_{arq}"):
                                        os.remove(caminho_arq)
                                        st.rerun()
                            st.markdown("---")
        if not encontrou_algo:
            st.warning("Nenhum arquivo correspondente foi localizado.")
        st.markdown("---")

    # 2. ÁRVORE DE DIRETÓRIOS ESTILO COMPUTADOR
    st.markdown("### 🗁 Árvore de Diretórios e Documentos")
    st.write("Clique nas pastas abaixo para abrir as subpastas de anos e gerenciar seus arquivos:")

    for pasta_p in sorted(PASTAS_PRINCIPAIS):
        with st.expander(f"📁 {pasta_p.upper()}", expanded=False):
            
            for ano_s in ANOS_DISPONIVEIS:
                caminho_sub = os.path.join(RAIZ_BIBLIOTECA, pasta_p, ano_s)
                
                with st.expander(f"📅 Ano {ano_s}", expanded=False):
                    
                    key_uploader = f"up_{pasta_p}_{ano_s}"
                    arquivos_enviados = st.file_uploader(
                        "Anexar novas evidências para este ano:", 
                        accept_multiple_files=True,
                        key=key_uploader
                    )
                    
                    if arquivos_enviados:
                        arquivos_salvos_agora = False
                        for arquivo in arquivos_enviados:
                            caminho_salvar = os.path.join(caminho_sub, arquivo.name)
                            if not os.path.exists(caminho_salvar):
                                with open(caminho_salvar, "wb") as f:
                                    f.write(arquivo.getbuffer())
                                arquivos_salvos_agora = True
                        
                        if arquivos_salvos_agora:
                            st.success("Novos arquivos guardados! Clique no botão 'Atualizar Biblioteca' no topo para atualizar a lista.")
                    
                    st.markdown("---")
                    
                    if os.path.exists(caminho_sub):
                        arquivos_locais = [a for a in os.listdir(caminho_sub) if not a.startswith('.')]
                    else:
                        arquivos_locais = []
                        
                    if arquivos_locais:
                        for arquivo in arquivos_locais:
                            caminho_completo_arq = os.path.join(caminho_sub, arquivo)
                            
                            with open(caminho_completo_arq, "rb") as file_ready:
                                conteudo_bytes = file_ready.read()
                            
                            col_icon, col_name, col_down, col_del = st.columns([0.05, 0.55, 0.2, 0.2])
                            with col_icon:
                                st.markdown("📄")
                            with col_name:
                                st.markdown(f"*{arquivo}*")
                            with col_down:
                                st.download_button(
                                    label="📥 Abrir",
                                    data=conteudo_bytes,
                                    file_name=arquivo,
                                    key=f"dl_{pasta_p}_{ano_s}_{arquivo}"
                                )
                            with col_del:
                                if st.button("❌ Deletar", key=f"del_{pasta_p}_{ano_s}_{arquivo}"):
                                    os.remove(caminho_completo_arq)
                                    st.rerun()
                    else:
                        st.info("Pasta vazia. Nenhum documento enviado.")