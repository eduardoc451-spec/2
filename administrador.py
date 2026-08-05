import json
import os
import streamlit as st
from datetime import datetime

# SENHA MASTER PARA ACESSAR O PAINEL DE ADMINISTRAÇÃO
SENHA_ADMIN = "fidelios"
ARQUIVO_DADOS = "usuarios_e_logs.json"

# ESTRUTURA INICIAL PADRÃO (SE O ARQUIVO NÃO EXISTIR)
DADOS_INICIAIS = {
    "usuarios": [
        {"id": 1, "usuario": "admin", "senha": "123", "perfil": "Administrador"},
        {"id": 2, "usuario": "auditor", "senha": "456", "perfil": "Auditor"},
        {"id": 3, "usuario": "gestor", "senha": "789", "perfil": "Gestor"}
    ],
    "logs": []
}

def carregar_dados_json():
    """Lê os usuários e logs do arquivo JSON local (Sem BD)."""
    if not os.path.exists(ARQUIVO_DADOS):
        salvar_dados_json(DADOS_INICIAIS)
        return DADOS_INICIAIS
    try:
        with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DADOS_INICIAIS

def salvar_dados_json(dados):
    """Grava as alterações no arquivo JSON local."""
    with open(ARQUIVO_DADOS, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)

def registrar_login(usuario_nome):
    """Registra o início do acesso no JSON local e retorna o ID do log."""
    dados = carregar_dados_json()
    novo_id = len(dados["logs"]) + 1
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    novo_log = {
        "id": novo_id,
        "usuario": usuario_nome,
        "data_hora_login": now_str,
        "data_hora_logout": "Sessão Ativa",
        "duracao_minutos": 0.0,
        "status": "Ativo"
    }
    
    dados["logs"].append(novo_log)
    salvar_dados_json(dados)
    return novo_id

def registrar_logout(log_id):
    """Encerra a sessão e calcula o tempo total de permanência logado."""
    if not log_id:
        return
    dados = carregar_dados_json()
    for log in dados["logs"]:
        if log["id"] == log_id and log["status"] == "Ativo":
            dt_login = datetime.strptime(log["data_hora_login"], "%d/%m/%Y %H:%M:%S")
            dt_logout = datetime.now()
            
            duracao = round((dt_logout - dt_login).total_seconds() / 60.0, 2)
            
            log["data_hora_logout"] = dt_logout.strftime("%d/%m/%Y %H:%M:%S")
            log["duracao_minutos"] = duracao
            log["status"] = "Encerrada"
            break
            
    salvar_dados_json(dados)

def verificar_autenticacao_admin():
    """Valida o acesso de Administrador."""
    if "admin_autenticado" not in st.session_state:
        st.session_state["admin_autenticado"] = False

    if not st.session_state["admin_autenticado"]:
        st.markdown("## 🛡️ Painel Administrador — Controle de Acessos")
        st.info("Acesso restrito para consulta de credenciais, logs e tempo de sessão.")

        col1, col2 = st.columns([2, 1])
        with col1:
            senha_input = st.text_input("Digite a senha de Administrador:", type="password", key="input_senha_admin")
        with col2:
            st.write("")
            st.write("")
            btn_acessar = st.button("🔓 Acessar Módulo", use_container_width=True, key="btn_admin_login")

        if btn_acessar or senha_input:
            if senha_input == SENHA_ADMIN:
                st.session_state["admin_autenticado"] = True
                st.success("Acesso liberado!")
                st.rerun()
            else:
                st.error("Senha de administrador incorreta!")
        return False
    return True

def mostrar_painel_admin():
    if not verificar_autenticacao_admin():
        return

    # Cabeçalho
    col_head, col_logout = st.columns([5, 1])
    with col_head:
        st.markdown("## 🔑 Módulo Administrador — Usuários & Sessões")
        st.caption("Gerenciamento sem Banco de Dados (Armazenamento via JSON Local)")
    with col_logout:
        st.write("")
        if st.button("🔒 Sair", use_container_width=True, key="btn_logout_admin"):
            st.session_state["admin_autenticado"] = False
            st.rerun()

    st.markdown("---")

    # Carrega dados do JSON
    dados = carregar_dados_json()
    usuarios = dados.get("usuarios", [])
    logs = dados.get("logs", [])

    # Métricas do Topo
    c1, c2, c3 = st.columns(3)
    c1.metric("Usuários Cadastrados", len(usuarios))
    c2.metric("Total de Acessos Registrados", len(logs))
    
    # Tempo Médio
    duracoes = [l["duracao_minutos"] for l in logs if l["duracao_minutos"] > 0]
    media_tempo = round(sum(duracoes) / len(duracoes), 1) if duracoes else 0.0
    c3.metric("Tempo Médio de Permanência", f"{media_tempo} min")

    st.markdown("---")

    tab1, tab2 = st.tabs(["🔐 Visualização de Senhas & Usuários", "⏱️ Histórico de Logins & Permanência"])

    # TAB 1: VISUALIZAÇÃO E ALTERAÇÃO DE SENHAS
    with tab1:
        st.subheader("Lista de Credenciais dos Usuários")
        st.dataframe(usuarios, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🔑 Alterar Senha de Usuário")
        
        lista_nomes_user = [u["usuario"] for u in usuarios]
        col_u, col_p, col_b = st.columns([2, 2, 1])
        
        with col_u:
            user_sel = st.selectbox("Selecione o Usuário:", lista_nomes_user)
        with col_p:
            nova_senha = st.text_input("Nova Senha:", type="password", key="input_nova_senha_json")
        with col_b:
            st.write("")
            st.write("")
            if st.button("Salvar Nova Senha", use_container_width=True):
                if nova_senha.strip():
                    for u in usuarios:
                        if u["usuario"] == user_sel:
                            u["senha"] = nova_senha
                            break
                    salvar_dados_json(dados)
                    st.success(f"Senha do usuário **{user_sel}** alterada com sucesso!")
                    st.rerun()
                else:
                    st.warning("Preencha a nova senha.")

    # TAB 2: TEMPO DE PERMANÊNCIA E LOGINS
    with tab2:
        st.subheader("Rastreamento de Sessões de Usuários")

        if not logs:
            st.info("Nenhum histórico de acesso registrado até o momento.")
        else:
            st.dataframe(
                logs,
                column_config={
                    "id": "ID Sessão",
                    "usuario": "Usuário Logado",
                    "data_hora_login": "Início da Sessão",
                    "data_hora_logout": "Fim da Sessão",
                    "duracao_minutos": st.column_config.NumberColumn("Tempo Logado (Min)", format="%.2f min"),
                    "status": "Status da Sessão"
                },
                use_container_width=True,
                hide_index=True
            )

def main():
    mostrar_painel_admin()

if __name__ == "__main__":
    main()
