import streamlit as st
import pandas as pd
import sqlite3
import os

def somar_pontos_padrao(nome_banco, ano):
    """Calcula a soma padrão de pontos para os bancos (escala original de 0-1000)."""
    caminho_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), nome_banco)
    if not os.path.exists(caminho_db):
        return 0
    try:
        conn = sqlite3.connect(caminho_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='respostas';")
        if not cursor.fetchone():
            conn.close()
            return 0
        
        cursor.execute("PRAGMA table_info(respostas);")
        colunas = [col[1] for col in cursor.fetchall()]
        col_chave = "chave"
        for c in colunas:
            if c.lower() in ["id", "pergunta", "questao", "chave_pergunta"]:
                col_chave = c
                break
                
        cursor.execute(f"SELECT pontos FROM respostas WHERE ano = ? AND {col_chave} NOT LIKE 'COM_%'", (ano,))
        linhas = cursor.fetchall()
        conn.close()
        
        if not linhas:
            return 0
        
        total = sum(float(row[0]) for row in linhas if row[0] is not None and str(row[0]).strip() != "")
        return int(round(total))
    except Exception:
        return 0

def puxar_nota_icidade(ano):
    return somar_pontos_padrao("dados_iegm_web.db", ano)

def puxar_nota_igov(ano):
    return somar_pontos_padrao("dados_igov_ti.db", ano)

def puxar_nota_iamb(ano):
    return somar_pontos_padrao("dados_iamb.db", ano)

def puxar_nota_iplan(ano):
    return somar_pontos_padrao("dados_iplan.db", ano)

def puxar_nota_isaude(ano):
    return somar_pontos_padrao("dados_isaude.db", ano)

def puxar_nota_ieduc(ano):
    return somar_pontos_padrao("dados_ieduc.db", ano)

def puxar_nota_ifiscal(ano):
    """Acessa o dados_ifiscal.db aplicando o rebaixamento crítico e mantendo escala 0-1000."""
    caminho_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados_ifiscal.db")
    if not os.path.exists(caminho_db):
        return 0
    try:
        conn = sqlite3.connect(caminho_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='respostas';")
        if not cursor.fetchone():
            conn.close()
            return 0
            
        cursor.execute("SELECT pontos FROM respostas WHERE ano = ?", (ano,))
        linhas = cursor.fetchall()
        conn.close()
        
        if not linhas:
            return 0
            
        valores = []
        for row in linhas:
            if row[0] is not None and str(row[0]).strip() != "":
                valores.append(float(row[0]))
        
        if any(v <= -100.0 for v in valores):
            return 0
            
        total_pts = sum(v for v in valores if v > -100.0)
        return int(round(total_pts))
    except Exception:
        return 0

def calcular_nota_final(plan, fiscal, educ, saude, amb, cidade, gov):
    """Calcula a nota final na escala 0-1000 dividindo por 100 pura (Média Ponderada Direta)."""
    try:
        v_plan = float(plan or 0)
        v_fiscal = float(fiscal or 0)
        v_educ = float(educ or 0)
        v_saude = float(saude or 0)
        v_amb = float(amb or 0)
        v_cidade = float(cidade or 0)
        v_gov = float(gov or 0)
        
        soma_ponderada = (v_plan * 20) + (v_fiscal * 20) + (v_educ * 20) + (v_saude * 20) + (v_amb * 10) + (v_cidade * 5) + (v_gov * 5)
        nota_final = soma_ponderada / 100.0
        
        return int(round(nota_final))
    except Exception:
        return 0

def obter_faixa_classificacao(nota):
    if nota >= 900: return "A (Altamente Efetiva)", "#10B981"
    elif nota >= 750: return "B+ (Muito Efetiva)", "#3B82F6"
    elif nota >= 600: return "B (Efetiva)", "#F59E0B"
    elif nota >= 500: return "C+ (Em Fase de Adequação)", "#F97316"
    else: return "C (Baixo Nível de Adequação)", "#EF4444"

def mostrar_painel_iegm_final(ano_selecionado):
    st.subheader("🏆 Consolidação do Índice de Efetividade da Gestão Municipal (IEG-M)")
    
    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    registro_historico = []
    
    for ano in anos:
        plan = puxar_nota_iplan(ano)
        fiscal = puxar_nota_ifiscal(ano)
        educ = puxar_nota_ieduc(ano)
        saude = puxar_nota_isaude(ano)
        amb = puxar_nota_iamb(ano)
        cidade = puxar_nota_icidade(ano)
        gov = puxar_nota_igov(ano)
        
        nota_f = calcular_nota_final(plan, fiscal, educ, saude, amb, cidade, gov)
        faixa, cor = obter_faixa_classificacao(nota_f)
        
        registro_historico.append({
            "Ano": ano,
            "i-Plan": int(plan),
            "i-Fiscal": int(fiscal),
            "i-Educ": int(educ),
            "i-Saúde": int(saude),
            "i-Amb": int(amb),
            "i-Cidade": int(cidade),
            "i-Gov TI": int(gov),
            "Nota Final": int(nota_f),
            "Faixa": faixa.split(" (")[0]
        })
        
    df_historico = pd.DataFrame(registro_historico)
    
    # 1. Criação da coluna de Variação Percentual
    variacoes = ["-"]
    for i in range(1, len(df_historico)):
        nota_ant = df_historico.loc[i-1, "Nota Final"]
        nota_at = df_historico.loc[i, "Nota Final"]
        
        if nota_ant == 0:
            if nota_at > 0:
                variacoes.append("▲ +100.0%")
            else:
                variacoes.append("0.0%")
        else:
            pct = ((nota_at - nota_ant) / nota_ant) * 100
            if pct > 0:
                variacoes.append(f"▲ +{pct:.1f}%")
            elif pct < 0:
                variacoes.append(f"▼ {pct:.1f}%")
            else:
                variacoes.append("0.0%")
                
    df_historico["Variação %"] = variacoes
    
    # Reorganiza a ordem das colunas para bater com o layout desejado
    colunas_ordenadas = ["Ano", "i-Plan", "i-Fiscal", "i-Educ", "i-Saúde", "i-Amb", "i-Cidade", "i-Gov TI", "Nota Final", "Variação %", "Faixa"]
    df_historico = df_historico[colunas_ordenadas]
    
    # Filtra os dados do ano selecionado para os cards
    dados_ano_atual = df_historico[df_historico["Ano"] == ano_selecionado].iloc[0]
    nota_f_atual = dados_ano_atual["Nota Final"]
    faixa_atual, cor_atual = obter_faixa_classificacao(nota_f_atual)
    
    st.markdown("---")
    st.markdown(f"### Resultado Consolidado Real: Ano de Referência {ano_selecionado}")
    
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        st.metric(label="Nota Final Calculada", value=f"{int(nota_f_atual)} pts")
    with c2:
        st.markdown("**Faixa TCESP:**")
        st.markdown(f"<div style='padding: 8px; border-radius: 8px; background-color: {cor_atual}; color: white; text-align: center; font-weight: bold;'>{faixa_atual}</div>", unsafe_allow_html=True)
    with c3:
        st.info("💡 **Fórmula TCESP Multiplicada:** `(i-Plan×20 + i-Fiscal×20 + i-Educ×20 + i-Saúde×20 + i-Amb×10 + i-Cidade×5 + i-Gov TI×5) / 100`")

    st.markdown("#### Desempenho das Dimensões (Escala 0-1000)")
    dados_tabela_atual = pd.DataFrame({
        "Dimensão": ["i-Plan", "i-Fiscal", "i-Educ", "i-Saúde", "i-Amb", "i-Cidade", "i-Gov TI"],
        "Peso TCESP": ["20%", "20%", "20%", "20%", "10%", "5%", "5%"],
        "Pontuação Obtida": [
            dados_ano_atual["i-Plan"], dados_ano_atual["i-Fiscal"],
            dados_ano_atual["i-Educ"], dados_ano_atual["i-Saúde"],
            dados_ano_atual["i-Amb"], dados_ano_atual["i-Cidade"],
            dados_ano_atual["i-Gov TI"]
        ]
    })
    
    # Exibe a tabela de dimensões perfeitamente centralizada via Pandas Styler
    st.dataframe(
        dados_tabela_atual.style.set_properties(**{'text-align': 'center'}).hide(axis="index"),
        use_container_width=True
    )

    st.markdown("---")
    st.markdown("### 📊 Painel Evolutivo — Série Histórica Real (2023 a 2030)")
    
    # 2. Painel Evolutivo modificado estritamente para Gráfico de Barras
    df_grafico = df_historico.set_index("Ano")[["Nota Final"]]
    st.bar_chart(df_grafico)
    
    st.markdown("#### 📅 Matriz de Dados Históricos Consolidados")
    
    # 3. Exibição da Matriz com todas as propriedades, textos e números 100% centralizados
    df_exibicao = df_historico.set_index("Ano")
    st.dataframe(
        df_exibicao.style.set_properties(**{'text-align': 'center'}),
        use_container_width=True
    )