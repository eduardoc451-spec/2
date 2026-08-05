import json
import os
import pandas as pd
import streamlit as st

# Configuração da página precisa ser a PRIMEIRA instrução Streamlit
st.set_page_config(page_title="Auditoria i-Plan Completa", layout="wide")

# --- CONEXÃO COM OS ARQUIVOS ORIGINAIS ---
ARQUIVO_P1 = "dados_auditoria.json"
ARQUIVO_P2 = "dados_auditoria_p2.json"

UNIDADES_MEDIDA = ["Unidade / Mensurável", "Não Mensurável"]

# --- FUNÇÕES DE PERSISTÊNCIA E CACHE (OTIMIZADAS) ---
@st.cache_data(show_spinner=False)
def ler_json_disco(caminho_arquivo):
    """Lê o arquivo do disco apenas 1 vez e armazena na memória (Cache)"""
    if os.path.exists(caminho_arquivo):
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def salvar_p1():
    with open(ARQUIVO_P1, "w", encoding="utf-8") as f:
        # Removido indent=4 para gravação ultra-rápida (Compact JSON)
        json.dump(st.session_state.programas, f, ensure_ascii=False)
    ler_json_disco.clear() # Limpa o cache após alterar o arquivo
    st.sidebar.success("💾 Dados do P1 Salvos!")

def carregar_p1():
    st.session_state.programas = ler_json_disco(ARQUIVO_P1)

def salvar_p2():
    with open(ARQUIVO_P2, "w", encoding="utf-8") as f:
        json.dump(st.session_state.programas_p2, f, ensure_ascii=False)
    ler_json_disco.clear()
    st.sidebar.success("💾 Dados do P2 Salvos!")

def carregar_p2():
    st.session_state.programas_p2 = ler_json_disco(ARQUIVO_P2)

# --- FUNÇÕES MATEMÁTICAS P1 (VETORIZADAS/SIMPLIFICADAS) ---
def calcular_e1_p1(indicadores):
    if not indicadores: return 0.0
    return sum(min(i['B'] / i['A'], 1.0) if i['A'] > 0 else 0.0 for i in indicadores) / len(indicadores)

def calcular_e2_p1(acoes):
    if not acoes: return 0.0
    valores = [
        0.0 if a.get('unidade') == "Não Mensurável" 
        else (min(a['D'] / a['C'], 1.0) if a['C'] > 0 else 0.0) 
        for a in acoes
    ]
    return sum(valores) / len(valores)

# --- FUNÇÕES MATEMÁTICAS P2 ---
def calcular_h1_p2(acoes):
    return calcular_e2_p1(acoes)

def calcular_h2_p2(acoes):
    if not acoes: return 0.0
    return sum(min(a['G'] / a['F'], 1.0) if a['F'] > 0 else 0.0 for a in acoes) / len(acoes)

def pontuacao(valor):
    if valor <= 0.2: return 250.0
    elif valor >= 0.4: return 0.0
    else: return ((0.4 - valor) / 0.2) * 250.0

# --- INTERFACE PRINCIPAL ---
def mostrar_formulario_atividade():
    st.title("📊 Painel Integrado de Auditoria i-Plan (P1 e P2)")

    # Inicialização Única dos estados globais
    if "programas" not in st.session_state:
        carregar_p1()
    if "programas_p2" not in st.session_state:
        carregar_p2()

    # Estados temporários
    for key in ["edit_idx_p1_ind", "edit_idx_p1_ac", "edit_idx_p2_ac", "prev_p1_prog", "prev_p2_prog"]:
        if key not in st.session_state:
            st.session_state[key] = None

    # Sidebar única
    st.sidebar.header("⚙️ Controle de Arquivos")
    if st.sidebar.button("💾 Salvar Tudo (P1 e P2)", use_container_width=True):
        salvar_p1()
        salvar_p2()
    
    if st.sidebar.button("🔄 Recarregar Backups", use_container_width=True):
        ler_json_disco.clear()
        carregar_p1()
        carregar_p2()
        st.rerun()

    tab_modulo_p1, tab_modulo_p2 = st.tabs([
        "📉 Módulo P1 - Coerência Planejamento", 
        "💰 Módulo P2 - Confronto Físico x Financeiro"
    ])

    # =========================================================================
    # CONTEÚDO DA ABA P1
    # =========================================================================
    with tab_modulo_p1:
        st.header("📉 P1: Resultados dos Indicadores vs Metas das Ações")
        
        with st.sidebar.form("form_add_p1"):
            p1_prog = st.text_input("Novo Programa para o P1:").strip()
            if st.form_submit_button("Adicionar no P1") and p1_prog:
                if p1_prog not in st.session_state.programas:
                    st.session_state.programas[p1_prog] = {"indicadores": [], "acoes": []}
                    st.rerun()

        if not st.session_state.programas:
            st.info("💡 Clique no botão '🔄 Recarregar Backups' para carregar os dados.")
        else:
            p_ativo_p1 = st.selectbox("Selecione o Programa em Execução (P1):", list(st.session_state.programas.keys()), key="sel_p1")
            
            if st.session_state.prev_p1_prog != p_ativo_p1:
                st.session_state.edit_idx_p1_ind = None
                st.session_state.edit_idx_p1_ac = None
                st.session_state.prev_p1_prog = p_ativo_p1
            
            col_f1, col_f2 = st.columns(2)
            
            # --- FORMULÁRIO INDICADORES P1 ---
            with col_f1:
                idx_ind = st.session_state.edit_idx_p1_ind
                if idx_ind is not None and idx_ind >= len(st.session_state.programas[p_ativo_p1]["indicadores"]):
                    idx_ind = None
                    st.session_state.edit_idx_p1_ind = None

                dados_ind = st.session_state.programas[p_ativo_p1]["indicadores"][idx_ind] if idx_ind is not None else {"nome": "", "A": 0.0, "B": 0.0}
                
                with st.form("f_ind_p1", clear_on_submit=True):
                    st.markdown(f"**{'✍️ Editar' if idx_ind is not None else '➕ Cadastrar'} Indicador**")
                    n_i = st.text_input("Nome do Indicador:", value=dados_ind["nome"])
                    va = st.number_input("Previsto Inicial (A):", value=float(dados_ind["A"]), key="p1_a")
                    vb = st.number_input("Realizado Eficiente (B):", value=float(dados_ind["B"]), key="p1_b")
                    
                    if st.form_submit_button("Salvar Alterações" if idx_ind is not None else "Inserir Indicador"):
                        if n_i:
                            nova_est = {"nome": n_i, "A": va, "B": vb}
                            if idx_ind is not None:
                                st.session_state.programas[p_ativo_p1]["indicadores"][idx_ind] = nova_est
                                st.session_state.edit_idx_p1_ind = None
                            else:
                                st.session_state.programas[p_ativo_p1]["indicadores"].append(nova_est)
                            st.rerun()

            # --- FORMULÁRIO AÇÕES P1 ---
            with col_f2:
                idx_ac_p1 = st.session_state.edit_idx_p1_ac
                if idx_ac_p1 is not None and idx_ac_p1 >= len(st.session_state.programas[p_ativo_p1]["acoes"]):
                    idx_ac_p1 = None
                    st.session_state.edit_idx_p1_ac = None

                dados_ac_p1 = st.session_state.programas[p_ativo_p1]["acoes"][idx_ac_p1] if idx_ac_p1 is not None else {"nome": "", "unidade": "Unidade / Mensurável", "C": 0.0, "D": 0.0}
                
                with st.form("f_ac_p1", clear_on_submit=True):
                    st.markdown(f"**{'✍️ Editar' if idx_ac_p1 is not None else '➕ Cadastrar'} Ação**")
                    n_a = st.text_input("Nome da Ação:", value=dados_ac_p1["nome"])
                    u_idx = UNIDADES_MEDIDA.index(dados_ac_p1["unidade"]) if dados_ac_p1["unidade"] in UNIDADES_MEDIDA else 0
                    uni = st.selectbox("Métrica Física:", UNIDADES_MEDIDA, index=u_idx, key="p1_uni")
                    vc = st.number_input("Meta Projetada (C):", value=float(dados_ac_p1["C"]), disabled=(uni=="Não Mensurável"), key="p1_c")
                    vd = st.number_input("Realizado Físico (D):", value=float(dados_ac_p1["D"]), disabled=(uni=="Não Mensurável"), key="p1_d")
                    
                    if st.form_submit_button("Salvar Alterações" if idx_ac_p1 is not None else "Inserir Ação"):
                        if n_a:
                            nova_est_ac = {
                                "nome": n_a, "unidade": uni, 
                                "C": 0.0 if uni=="Não Mensurável" else vc, 
                                "D": 0.0 if uni=="Não Mensurável" else vd
                            }
                            if idx_ac_p1 is not None:
                                st.session_state.programas[p_ativo_p1]["acoes"][idx_ac_p1] = nova_est_ac
                                st.session_state.edit_idx_p1_ac = None
                            else:
                                st.session_state.programas[p_ativo_p1]["acoes"].append(nova_est_ac)
                            st.rerun()

            # --- ÁREA DE GERENCIAMENTO GRANULAR ---
            st.markdown("### 🛠️ Gerenciar Lançamentos Registrados em: " + p_ativo_p1)
            c_lista1, c_lista2 = st.columns(2)
            
            with c_lista1:
                st.write("**Indicadores:**")
                for idx, i in enumerate(st.session_state.programas[p_ativo_p1].get("indicadores", [])):
                    c_txt, c_ed, c_ex = st.columns([3, 1, 1])
                    c_txt.write(f"• {i['nome']} (A: {i['A']} | B: {i['B']})")
                    if c_ed.button("📝", key=f"ed_ind_{idx}"):
                        st.session_state.edit_idx_p1_ind = idx
                        st.rerun()
                    if c_ex.button("❌", key=f"ex_ind_{idx}"):
                        st.session_state.programas[p_ativo_p1]["indicadores"].pop(idx)
                        st.rerun()

            with c_lista2:
                st.write("**Ações:**")
                for idx, a in enumerate(st.session_state.programas[p_ativo_p1].get("acoes", [])):
                    c_txt, c_ed, c_ex = st.columns([3, 1, 1])
                    c_txt.write(f"• {a['nome']} ({a['unidade']} | C: {a['C']} | D: {a['D']})")
                    if c_ed.button("📝", key=f"ed_ac_p1_{idx}"):
                        st.session_state.edit_idx_p1_ac = idx
                        st.rerun()
                    if c_ex.button("❌", key=f"ex_ac_p1_{idx}"):
                        st.session_state.programas[p_ativo_p1]["acoes"].pop(idx)
                        st.rerun()

            st.markdown("---")
            st.subheader("📋 Tabela Consolidada P1 (MUNICÍPIO)")
            
            tab_p1 = []
            lista_e = []
            tot_a, tot_c = 0, 0
            
            for p, d in st.session_state.programas.items():
                s_a = sum(i['A'] for i in d.get("indicadores", []))
                s_c = sum(a['C'] for a in d.get("acoes", []))
                tot_a += s_a; tot_c += s_c
                
                if not d.get("indicadores") or s_a == 0 or not d.get("acoes") or (s_c == 0 and not any(x['unidade']=="Não Mensurável" for x in d["acoes"])):
                    e_p = 1.0; m_e1 = 0.0; m_e2 = 0.0
                else:
                    m_e1 = calcular_e1_p1(d["indicadores"])
                    m_e2 = calcular_e2_p1(d["acoes"])
                    e_p = abs(m_e1 - m_e2)
                
                lista_e.append(e_p)
                tab_p1.append({"Programa": p, "μE1 (Média Ind)": round(m_e1, 4), "μE2 (Média Ações)": round(m_e2, 4), "Desvio E": round(e_p, 4)})
            
            if tab_p1:
                st.dataframe(pd.DataFrame(tab_p1), use_container_width=True, hide_index=True)
                ef = 1.0 if (tot_a == 0 or tot_c == 0 or not lista_e) else sum(lista_e) / len(lista_e)
                st.markdown("#### Resultado Consolidado Global P1")
                c1, c2 = st.columns(2)
                c1.metric("Ef Final do Município", f"{ef:.4f}")
                c2.metric("🏆 Pontuação Final P1 (Máx. 250)", f"{pontuacao(ef):.2f}")

    # =========================================================================
    # CONTEÚDO DA ABA P2
    # =========================================================================
    with tab_modulo_p2:
        st.header("💰 P2: Confronto entre Resultado Físico e Recursos Financeiros")
        
        with st.sidebar.form("form_add_p2"):
            p2_prog = st.text_input("Novo Programa para o P2:").strip()
            if st.form_submit_button("Adicionar no P2") and p2_prog:
                if p2_prog not in st.session_state.programas_p2:
                    st.session_state.programas_p2[p2_prog] = {"acoes": []}
                    st.rerun()

        if not st.session_state.programas_p2:
            st.info("Cadastre os programas para o Módulo P2 utilizando a barra lateral esquerda.")
        else:
            p_ativo_p2 = st.selectbox("Selecione o Programa em Execução (P2):", list(st.session_state.programas_p2.keys()), key="sel_p2")

            if st.session_state.prev_p2_prog != p_ativo_p2:
                st.session_state.edit_idx_p2_ac = None
                st.session_state.prev_p2_prog = p_ativo_p2

            idx_ac_p2 = st.session_state.edit_idx_p2_ac
            if idx_ac_p2 is not None and idx_ac_p2 >= len(st.session_state.programas_p2[p_ativo_p2]["acoes"]):
                idx_ac_p2 = None
                st.session_state.edit_idx_p2_ac = None

            dados_ac_p2 = st.session_state.programas_p2[p_ativo_p2]["acoes"][idx_ac_p2] if idx_ac_p2 is not None else {"nome": "", "unidade": "Unidade / Mensurável", "C": 0.0, "D": 0.0, "F": 0.0, "G": 0.0}

            with st.form("f_ac_p2", clear_on_submit=True):
                st.markdown(f"**{'✍️ Editar' if idx_ac_p2 is not None else '➕ Lançar'} Ação no P2**")
                n_a = st.text_input("Nome da Ação:", value=dados_ac_p2["nome"])
                u_idx_p2 = UNIDADES_MEDIDA.index(dados_ac_p2["unidade"]) if dados_ac_p2["unidade"] in UNIDADES_MEDIDA else 0
                uni = st.selectbox("Métrica Física:", UNIDADES_MEDIDA, index=u_idx_p2, key="p2_uni")
                
                col1, col2, col3, col4 = st.columns(4)
                with col1: vc = st.number_input("Meta Estimada (C):", value=float(dados_ac_p2["C"]), disabled=(uni=="Não Mensurável"), key="p2_c")
                with col2: vd = st.number_input("Realizado Físico (D):", value=float(dados_ac_p2["D"]), disabled=(uni=="Não Mensurável"), key="p2_d")
                with col3: vf = st.number_input("Orçamento Fixado (F):", value=float(dados_ac_p2["F"]), key="p2_f")
                with col4: vg = st.number_input("Gasto Liquidado (G):", value=float(dados_ac_p2["G"]), key="p2_g")
                
                if st.form_submit_button("Salvar Alterações" if idx_ac_p2 is not None else "Salvar Ação"):
                    if n_a:
                        nova_est_p2 = {
                            "nome": n_a, "unidade": uni,
                            "C": 0.0 if uni=="Não Mensurável" else vc, "D": 0.0 if uni=="Não Mensurável" else vd,
                            "F": vf, "G": vg
                        }
                        if idx_ac_p2 is not None:
                            st.session_state.programas_p2[p_ativo_p2]["acoes"][idx_ac_p2] = nova_est_p2
                            st.session_state.edit_idx_p2_ac = None
                        else:
                            st.session_state.programas_p2[p_ativo_p2]["acoes"].append(nova_est_p2)
                        st.rerun()

            # --- GERENCIAMENTO P2 ---
            st.markdown("### 🛠️ Gerenciar Ações do P2 Registradas em: " + p_ativo_p2)
            for idx, a in enumerate(st.session_state.programas_p2[p_ativo_p2].get("acoes", [])):
                c_txt, c_ed, c_ex = st.columns([4, 1, 1])
                c_txt.write(f"• **{a['nome']}** ({a['unidade']}) | C: {a['C']} | D: {a['D']} | F: {a['F']} | G: {a['G']}")
                if c_ed.button("📝", key=f"ed_ac_p2_{idx}"):
                    st.session_state.edit_idx_p2_ac = idx
                    st.rerun()
                if c_ex.button("❌", key=f"ex_ac_p2_{idx}"):
                    st.session_state.programas_p2[p_ativo_p2]["acoes"].pop(idx)
                    st.rerun()

            st.markdown("---")
            st.subheader("📋 Tabela Consolidada P2 (MUNICÍPIO)")
            
            tab_p2 = []
            lista_h = []
            tot_c_p2, tot_f_p2 = 0, 0
            
            for p, d in st.session_state.programas_p2.items():
                s_c = sum(a['C'] for a in d["acoes"])
                s_f = sum(a['F'] for a in d["acoes"])
                tot_c_p2 += s_c; tot_f_p2 += s_f
                
                if not d["acoes"] or (s_c == 0 and not any(x['unidade']=="Não Mensurável" for x in d["acoes"])) or s_f == 0:
                    h_p = 1.0; m_h1 = 0.0; m_h2 = 0.0
                else:
                    m_h1 = calcular_h1_p2(d["acoes"])
                    m_h2 = calcular_h2_p2(d["acoes"])
                    h_p = abs(m_h1 - m_h2)
                    
                lista_h.append(h_p)
                tab_p2.append({"Programa": p, "μH1 (Média Física)": round(m_h1, 4), "μH2 (Média Gasto)": round(m_h2, 4), "Desvio H": round(h_p, 4)})
                
            if tab_p2:
                st.dataframe(pd.DataFrame(tab_p2), use_container_width=True, hide_index=True)
                hf = 1.0 if (tot_c_p2 == 0 or tot_f_p2 == 0 or not lista_h) else sum(lista_h) / len(lista_h)
                st.markdown("#### Resultado Consolidado Global P2")
                c1, c2 = st.columns(2)
                c1.metric("Hf Final do Município", f"{hf:.4f}")
                c2.metric("🏆 Pontuação Final P2 (Máx. 250)", f"{pontuacao(hf):.2f}")

if __name__ == "__main__":
    mostrar_formulario_atividade()
