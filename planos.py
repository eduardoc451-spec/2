import json
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime

SENHA_ACESSO = "fidelios"

# --- LISTA OFICIAL DE PLANOS MUNICIPAIS DE FRANCISCO MORATO ---
PLANOS_MUNICIPAIS = [
    "Plancon 2025-2026",
    "Plano de Educação Permanente do SUAS",
    "Plano Municipal de Educação",
    "Plano Diretor de TI",
    "Plano de Mobilidade Urbana",
    "Plano Municipal da Criança com Deficiência, TEA, Altas Habilidades e Superdotação",
    "Plano Municipal de Segurança Alimentar 2026-2030",
    "Plano Municipal da Primeira Infância",
    "Plano de Adaptação e Resiliência à Mudança do Clima",
    "Plano Municipal Decenal para a Infância e Adolescência",
    "Plano Municipal de Segurança Pública",
    "PPA Participativo 2026-2030",
    "Outro Plano Setorial / Especial"
]

CRITERIOS_MONITORAMENTO = [
    "1. A unidade gestora possui relatório oficial e periódico de monitoramento de metas publicado?",
    "2. Os indicadores de desempenho possuem fontes de dados confiáveis e auditáveis?",
    "3. Há justificativa técnica aprovada para as metas que apresentaram atraso ou não atingimento?",
    "4. As metas do plano para o exercício foram refletidas em ações/programas na LOA e PPA?",
    "5. O Conselho Municipal da área apreciou e emitiu parecer sobre o cumprimento das metas?",
]

def init_db():
    """Inicializa a tabela de monitoramento focado em metas no banco SQLite."""
    conn = sqlite3.connect("sistema_gestao.db")
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoramento_metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ano INTEGER,
            data_avaliacao TEXT,
            nome_plano TEXT,
            secretaria_responsavel TEXT,
            auditor_responsavel TEXT,
            taxa_execucao_media REAL,
            qtd_metas_avaliadas INTEGER,
            qtd_metas_criticas INTEGER,
            parecer_monitoramento TEXT,
            dados_metas TEXT,
            dados_questionario TEXT
        )
        """
    )
    conn.commit()
    conn.close()

def salvar_monitoramento(ano, data_avaliacao, nome_plano, secretaria_responsavel, auditor_responsavel, taxa_execucao_media, qtd_metas, qtd_criticas, parecer, dados_metas, dados_quest):
    conn = sqlite3.connect("sistema_gestao.db")
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO monitoramento_metas (
            ano, data_avaliacao, nome_plano, secretaria_responsavel, auditor_responsavel,
            taxa_execucao_media, qtd_metas_avaliadas, qtd_metas_criticas,
            parecer_monitoramento, dados_metas, dados_questionario
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ano, data_avaliacao, nome_plano, secretaria_responsavel, auditor_responsavel,
            taxa_execucao_media, qtd_metas, qtd_criticas, parecer,
            json.dumps(dados_metas, ensure_ascii=False),
            json.dumps(dados_quest, ensure_ascii=False)
        ),
    )
    conn.commit()
    conn.close()

def carregar_monitoramentos(ano):
    conn = sqlite3.connect("sistema_gestao.db")
    df = pd.read_sql_query(
        """
        SELECT 
            id, data_avaliacao, nome_plano, secretaria_responsavel, auditor_responsavel,
            taxa_execucao_media, qtd_metas_avaliadas, qtd_metas_criticas, parecer_monitoramento
        FROM monitoramento_metas 
        WHERE ano = ? 
        ORDER BY id DESC
        """,
        conn,
        params=(ano,),
    )
    conn.close()
    return df

def verificar_autenticacao():
    if "planos_autenticado" not in st.session_state:
        st.session_state["planos_autenticado"] = False

    if not st.session_state["planos_autenticado"]:
        st.markdown("## 🔒 Acesso Restrito — Auditoria e Monitoramento de Metas")
        st.info("Módulo focado no Acompanhamento e Monitoramento de Metas dos Planos Municipais de Francisco Morato.")
        
        col1, col2 = st.columns([2, 1])
        with col1:
            senha_input = st.text_input("Digite a senha de acesso:", type="password", key="input_senha_planos")
        with col2:
            st.write("")
            st.write("")
            btn_acessar = st.button("🔓 Acessar Módulo", use_container_width=True, key="btn_planos_login")

        if btn_acessar or senha_input:
            if senha_input == SENHA_ACESSO:
                st.session_state["planos_autenticado"] = True
                st.success("Acesso liberado!")
                st.rerun()
            else:
                st.error("Senha incorreta!")
        return False
    return True

def mostrar_painel_planos(year):
    init_db()

    if not verificar_autenticacao():
        return

    col_head, col_logout = st.columns([5, 1])
    with col_head:
        st.markdown("## 🎯 Controle Interno — Monitoramento de Metas dos Planos Municipais")
        st.caption(f"Município de Francisco Morato — Exercício de Auditoria: **{year}**")
    with col_logout:
        st.write("")
        if st.button("🔒 Sair", use_container_width=True, key="btn_logout_planos"):
            st.session_state["planos_autenticado"] = False
            st.rerun()

    tab1, tab2 = st.tabs(["🎯 Auditoria de Metas do Plano", "📊 Diagnóstico de Desempenho"])

    with tab1:
        st.subheader("1. Identificação do Plano Municipal")
        col1, col2 = st.columns(2)
        with col1:
            nome_plano_sel = st.selectbox("Selecione o Plano Municipal", PLANOS_MUNICIPAIS)
            if nome_plano_sel == "Outro Plano Setorial / Especial":
                nome_plano = st.text_input("Nome Específico do Plano:", placeholder="Ex: Plano Municipal de Esporte")
            else:
                nome_plano = nome_plano_sel

            data_eval = st.date_input("Data do Monitoramento", datetime.now(), format="DD/MM/YYYY")

        with col2:
            secretaria_responsavel = st.text_input("Secretaria Gestora / Executora", placeholder="Ex: Secretaria de Assistência Social")
            auditor_responsavel = st.text_input("Servidor / Auditor Responsável", placeholder="Ex: Maria Oliveira")

        st.markdown("---")
        st.subheader("2. Avaliação Qualitativa do Sistema de Monitoramento")
        
        respostas_qualitativas = {}
        for idx, crit in enumerate(CRITERIOS_MONITORAMENTO):
            st.markdown(f"**{crit}**")
            col_r, col_o = st.columns([1, 2])
            with col_r:
                resp = st.radio("Situação:", ["Sim", "Parcialmente", "Não"], key=f"mon_qual_{idx}", horizontal=True)
            with col_o:
                obs = st.text_input("Observação / Evidência:", key=f"mon_obs_{idx}", placeholder="Ex: Publicado no Diário Oficial / Doc fls. 12")
            respostas_qualitativas[crit] = {"resposta": resp, "observacao": obs}

        st.markdown("---")
        st.subheader("3. Detalhamento e Verificação das Metas Específicas")
        st.caption("Cadastre e monitore as metas do plano selecionado para calcular a taxa de cumprimento real.")

        # Gerenciador dinâmico de metas no session_state
        if "lista_metas_auditadas" not in st.session_state:
            st.session_state["lista_metas_auditadas"] = [
                {"codigo": "Meta 1", "descricao": "", "previsto": 100.0, "realizado": 0.0, "gargalo": ""}
            ]

        col_add, col_rem = st.columns([1, 1])
        with col_add:
            if st.button("➕ Adicionar Nova Meta para Auditar"):
                nova_meta_num = len(st.session_state["lista_metas_auditadas"]) + 1
                st.session_state["lista_metas_auditadas"].append(
                    {"codigo": f"Meta {nova_meta_num}", "descricao": "", "previsto": 100.0, "realizado": 0.0, "gargalo": ""}
                )
                st.rerun()
        with col_rem:
            if len(st.session_state["lista_metas_auditadas"]) > 1:
                if st.button("➖ Remover Última Meta"):
                    st.session_state["lista_metas_auditadas"].pop()
                    st.rerun()

        dados_metas_finais = []
        soma_porcentagens = 0
        qtd_criticas = 0

        for idx, m in enumerate(st.session_state["lista_metas_auditadas"]):
            with st.expander(f"📌 {m['codigo']}", expanded=True):
                c_cod, c_desc = st.columns([1, 3])
                with c_cod:
                    cod = st.text_input("Identificador / Código", value=m["codigo"], key=f"cod_{idx}")
                with c_desc:
                    desc = st.text_input("Descrição da Meta", value=m["descricao"], key=f"desc_{idx}", placeholder="Ex: Capacitar 100% dos servidores da assistência social.")

                c_p, c_r, c_pct = st.columns(3)
                with c_p:
                    prev = st.number_input("Previsto / Programado (Qtd ou %)", value=m["previsto"], key=f"prev_{idx}")
                with c_r:
                    real = st.number_input("Realizado / Executado (Qtd ou %)", value=m["realizado"], key=f"real_{idx}")
                
                # Cálculo de porcentagem de atingimento da meta
                pct_atingido = (real / prev * 100) if prev > 0 else 0
                soma_porcentagens += pct_atingido
                
                if pct_atingido < 50:
                    qtd_criticas += 1

                with c_pct:
                    st.metric("Atingimento da Meta", f"{pct_atingido:.1f}%")

                gargalo = st.text_area("Causa do Não Atingimento / Obstáculo Identificado:", value=m["gargalo"], key=f"gar_{idx}", height=60, placeholder="Ex: Contingenciamento orçamentário, atraso no certame licitatório...")

                dados_metas_finais.append({
                    "codigo": cod,
                    "descricao": desc,
                    "previsto": prev,
                    "realizado": real,
                    "atingimento_pct": round(pct_atingido, 1),
                    "gargalo": gargalo
                })

        # Totais
        total_metas = len(dados_metas_finais)
        media_execucao = soma_porcentagens / total_metas if total_metas > 0 else 0

        st.markdown("---")
        st.subheader("📊 Painel Consolidado da Auditoria de Metas")
        m1, m2, m3 = st.columns(3)
        m1.metric("Taxa Média de Cumprimento das Metas", f"{media_execucao:.1f}%")
        m2.metric("Total de Metas Auditadas", total_metas)
        m3.metric("Metas Críticas (<50% de Execução)", qtd_criticas, delta_color="inverse")

        parecer = st.text_area(
            "Recomendações e Determinações do Controle Interno:",
            placeholder="Descreva as orientações e prazos para a secretaria corrigir os gargalos das metas em atraso...",
            height=100
        )

        if st.button("💾 Finalizar e Salvar Auditoria de Metas", use_container_width=True):
            if not auditor_responsavel or not nome_plano:
                st.error("Preencha o Nome do Plano e o Auditor Responsável antes de salvar.")
            else:
                salvar_monitoramento(
                    year,
                    data_eval.strftime("%d/%m/%Y"),
                    nome_plano,
                    secretaria_responsavel,
                    auditor_responsavel,
                    round(media_execucao, 1),
                    total_metas,
                    qtd_criticas,
                    parecer,
                    dados_metas_finais,
                    respostas_qualitativas
                )
                st.balloons()
                st.success(f"Relatório de Monitoramento do **{nome_plano}** salvo com sucesso no sistema!")

    with tab2:
        st.subheader("Histórico de Auditorias de Metas em Francisco Morato")
        df = carregar_monitoramentos(year)

        if df.empty:
            st.info(f"Nenhuma auditoria de metas registrada em {year}.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Total de Planos Acompanhados", len(df))
            c2.metric("Média Geral de Cumprimento", f"{df['taxa_execucao_media'].mean():.1f}%")
            c3.metric("Total de Metas Críticas Acumuladas", df['qtd_metas_criticas'].sum())

            st.markdown("---")
            st.dataframe(
                df,
                column_config={
                    "id": "ID",
                    "data_avaliacao": "Data",
                    "nome_plano": "Plano Municipal",
                    "secretaria_responsavel": "Secretaria Gestora",
                    "auditor_responsavel": "Auditor",
                    "taxa_execucao_media": st.column_config.NumberColumn("Cumprimento Médio (%)", format="%.1f%%"),
                    "qtd_metas_avaliadas": "Metas Auditadas",
                    "qtd_metas_criticas": "Metas Críticas (<50%)",
                    "parecer_monitoramento": "Determinações do Controle Interno",
                },
                use_container_width=True,
                hide_index=True,
            )

def main():
    mostrar_painel_planos(datetime.now().year)

if __name__ == "__main__":
    main()