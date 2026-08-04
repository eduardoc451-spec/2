import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st

# ==========================================
# 1. CONFIGURAÇÕES E ESTRUTURA DE DADOS
# ==========================================

# Mapeamento de faixas e cores do IEGM
FAIXAS_IEGM = {
    "C": {"min": 0.0, "max": 50.0, "cor": "#FF0000", "descricao": "Baixo nível de adequação"},
    "C+": {"min": 50.01, "max": 60.0, "cor": "#FFA500", "descricao": "Em fase de adequação"},
    "B": {"min": 60.01, "max": 75.0, "cor": "#FFFF00", "descricao": "Efetivo"},
    "B+": {"min": 75.01, "max": 90.0, "cor": "#90EE90", "descricao": "Muito efetivo"},
    "A": {"min": 90.01, "max": 100.0, "cor": "#008000", "descricao": "Altamente efetivo"}
}

# Teto de pontuação máxima por dimensão (Exemplo)
TETOS_PONTUACAO = {
    "iCidade": 100,
    "iGov-Ti": 120,
    "i-Amb": 90
}

# BANCOS DE DADOS POR DIMENSÃO
BANCOS_DADOS = {
    "iCidade": "dados_iegm_web.db",
    "iGov-Ti": "dados_igov_ti.db",
    "i-Amb": "dados_iamb.db"
}

# ==========================================
# 2. FUNÇÕES DE SUPORTE E BANCO DE DADOS
# ==========================================

def obter_conexao(dimensao):
    """Retorna a conexão com o banco SQLite correspondente à dimensão."""
    db_name = BANCOS_DADOS.get(dimensao, "dados_iegm_web.db")
    return sqlite3.connect(db_name)

def obter_faixa_e_cor(percentual):
    """Retorna a faixa de classificação e a cor correspondente com base no percentual."""
    for faixa, info in FAIXAS_IEGM.items():
        if info["min"] <= percentual <= info["max"]:
            return faixa, info["cor"]
    return "C", FAIXAS_IEGM["C"]["cor"]

def calcular_evolucao_pontos(df, dimensao):
    """Calcula a pontuação líquida, percentual do teto e faixa para cada ano."""
    teto = TETOS_PONTUACAO.get(dimensao, 100)
    
    # Agrupa pontuação por ano
    df_evolucao = df.groupby('ano')['pontos'].sum().reset_index()
    df_evolucao.rename(columns={'pontos': 'pontos_obtidos'}, inplace=True)
    
    # Cálculos
    df_evolucao['percentual'] = (df_evolucao['pontos_obtidos'] / teto) * 100
    df_evolucao['percentual'] = df_evolucao['percentual'].clip(lower=0, upper=100)
    
    res_faixas = df_evolucao['percentual'].apply(obter_faixa_e_cor)
    df_evolucao['faixa'] = [r[0] for r in res_faixas]
    df_evolucao['cor'] = [r[1] for r in res_faixas]
    
    return df_evolucao

def analisar_pontos_fracos(df_questoes):
    """
    Identifica oportunidades de melhoria (gaps) e penalidades aplicadas nas questões.
    """
    pontos_fracos = []
    
    for _, row in df_questoes.iterrows():
        p_obtido = row.get('pontos', 0)
        p_max = row.get('pontos_max', 0)
        questao_id = row.get('id_questao', 'N/A')
        descricao = row.get('descricao', 'Sem descrição')
        
        # Perda por não atingir o máximo
        if p_obtido < p_max:
            gap = p_max - p_obtido
            pontos_fracos.append({
                'id': questao_id,
                'descricao': descricao,
                'tipo': 'Oportunidade de Ganho',
                'impacto': gap,
                'detalhe': f"Obteve {p_obtido} de {p_max} pts (Perdeu {gap:.1f} pts)"
            })
        
        # Penalidade ativa (pontos negativos)
        if p_obtido < 0:
            pontos_fracos.append({
                'id': questao_id,
                'descricao': descricao,
                'tipo': 'Penalidade Aplicada',
                'impacto': abs(p_obtido),
                'detalhe': f"Penalizado em {p_obtido} pts"
            })
            
    # Ordena pelo maior impacto
    return sorted(pontos_fracos, key=lambda x: x['impacto'], reverse=True)

# ==========================================
# 3. INTERFACE STREAMLIT (SISTEMA HAL)
# ==========================================

def injetar_css():
    """Injeta estilos CSS para layout de Chat/Dashboard."""
    st.markdown("""
        <style>
        .chat-wrapper {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .avatar-ia {
            font-weight: bold;
            color: #007bff;
            margin-bottom: 5px;
        }
        .chat-bubble-user {
            background-color: #e2e3e5;
            padding: 10px 15px;
            border-radius: 8px;
            margin-bottom: 10px;
        }
        .card-ponto-fraco {
            background-color: #ffffff;
            border-left: 4px solid #dc3545;
            padding: 10px 15px;
            margin-bottom: 8px;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        </style>
    """, unsafe_allow_html=True)

def mostrar_chat_hal(dimensao, df_dados):
    """Renderiza a análise do HAL com gráficos e diagnósticos."""
    injetar_css()
    
    st.markdown('<div class="avatar-ia">🤖 Sistema HAL - Diagnóstico Estratégico</div>', unsafe_allow_html=True)
    
    if df_dados.empty:
        st.warning(f"Não há dados disponíveis para a dimensão **{dimensao}**.")
        return

    # Processamento de Dados
    df_evolucao = calcular_evolucao_pontos(df_dados, dimensao)
    pontos_fracos = analisar_pontos_fracos(df_dados)
    
    # 1. Gráfico de Evolução (Plotly)
    st.subheader(f"📈 Evolução do Desempenho - {dimensao}")
    
    fig = px.bar(
        df_evolucao,
        x='ano',
        y='percentual',
        text='faixa',
        title=f"Aproveitamento % em {dimensao} por Ano",
        labels={'ano': 'Ano', 'percentual': '% Aproveitamento'},
        color='faixa',
        color_discrete_map={k: v['cor'] for k, v in FAIXAS_IEGM.items()}
    )
    
    fig.update_traces(textposition='outside')
    fig.update_layout(yaxis_range=[0, 105])
    
    st.plotly_chart(fig, use_container_width=True)
    
    ---
    
    # 2. Resumo de Oportunidades / Pontos Fracos
    st.subheader("🎯 Principais Gargalos e Oportunidades de Melhora")
    
    if pontos_fracos:
        for item in pontos_fracos[:5]: # Exibe os 5 de maior impacto
            st.markdown(f"""
                <div class="card-ponto-fraco">
                    <strong>Questão {item['id']}</strong> - <em>{item['tipo']}</em><br>
                    <small>{item['descricao']}</small><br>
                    <span style="color: #dc3545; font-weight: bold;">{item['detalhe']}</span>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.success("Excelente! Nenhum ponto fraco crítico ou penalidade foi identificado nesta dimensão.")

# ==========================================
# 4. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    st.set_page_config(page_title="Sistema HAL - IEGM", layout="wide")
    st.title("🛡️ Painel de Controle e Auditoria IEGM")
    
    # Seletor de Dimensão
    dimensao_selecionada = st.sidebar.selectbox(
        "Selecione a Dimensão para Análise:",
        ["iCidade", "iGov-Ti", "i-Amb"]
    )
    
    # Exemplo de DataFrame mockup para teste (substituir pela consulta SQLite real se necessário)
    dados_mock = pd.DataFrame({
        'ano': [2021, 2022, 2023, 2024],
        'id_questao': ['Q1', 'Q2', 'Q3', 'Q4'],
        'descricao': ['Plano Diretor Atualizado', 'Capacitação em TI', 'Gestão de Resíduos', 'Licenciamento Ambiental'],
        'pontos': [30, 45, -5, 80],
        'pontos_max': [50, 50, 10, 100]
    })
    
    mostrar_chat_hal(dimensao_selecionada, dados_mock)
