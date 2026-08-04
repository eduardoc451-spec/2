import re
import streamlit as st
import plotly.graph_objects as go
from sqlalchemy import create_engine, text

# ==============================================================================
# CONFIGURAÇÃO INICIAL DO STREAMLIT (DEVE SER A PRIMEIRA LINHA STREAMLIT)
# ==============================================================================
st.set_page_config(page_title="HAL - Diagnóstico TCESP", layout="wide")

# ==============================================================================
# STRING DE CONEXÃO POSTGRESQL (NEON DB)
# ==============================================================================
DATABASE_URL = "postgresql://neondb_owner:npg_beMKhVR2N4wo@ep-divine-sky-awx1636y-pooler.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# ==============================================================================
# CLASSE PRINCIPAL SISTEMA HAL
# ==============================================================================
class SistemaHAL:
    def __init__(self):
        # Mapeamento Completo de Enunciados por Dimensão
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": "1.0 - Planejamento Urbano e Plano Diretor",
                "1.3": "1.3 - Zoneamento e Uso do Solo",
                "1.4": "1.4 - Regularização Fundiária Urbana (REURB)",
                "2.0": "2.0 - Mobilidade e Transporte Público",
                "2.1": "2.1 - Acessibilidade em Vias e Edificações",
                "2.2": "2.2 - Malha Cicloviária e Infraestrutura de Pedestres",
                "3.0": "3.0 - Saneamento Básico e Drenagem Urbana",
                "3.1.1": "3.1.1 - Coleta e Tratamento de Esgoto",
                "5.0": "5.0 - Gestão de Resíduos Sólidos e Coleta Seletiva",
                "7.0": "7.0 - Habitação de Interesse Social",
                "7.1": "7.1 - Mapeamento de Áreas de Risco",
                "7.2": "7.2 - Prevenção de Desastres e Defesa Civil",
                "7.3": "7.3 - Infraestrutura em Assentamentos Precários",
                "7.4": "7.4 - Programas de Melhoria Habitacional",
                "7.5": "7.5 - Cadastro Único de Habitação",
                "7.6": "7.6 - Parcerias para Habitação Popular",
                "8.0": "8.0 - Arborização Urbana e Áreas Verdes",
                "8.1.1.1": "8.1.1.1 - Preservação de Áreas de Proteção Ambiental",
                "8.2": "8.2 - Manutenção de Praças e Parques",
                "9.0": "9.0 - Iluminação Pública e Eficiência Energética",
                "15.0": "15.0 - Equipamentos Públicos de Lazer e Esporte",
                "16.0": "16.0 - Conservação do Patrimônio Histórico e Cultural",
                "C1.1": "C1.1 - Monitoramento de Obras e Intervenções Urbanas"
            },
            "iGov-Ti": {
                "1.0": "1.0 - Governança de TI e Alinhamento Estratégico",
                "1.1": "1.1 - Plano Diretor de Tecnologia da Informação (PDTI)",
                "1.2": "1.2 - Comitê Gestor de TI e Tomada de Decisão",
                "1.3": "1.3 - Gestão de Riscos de TI",
                "1.3.1": "1.3.1 - Mapeamento de Processos Críticos de TI",
                "1.4.1": "1.4.1 - Política de Segurança da Informação (POSI)",
                "1.4.2": "1.4.2 - Plano de Continuidade de Negócios e Contingência",
                "2.0": "2.0 - Conformidade com a LGPD e Proteção de Dados",
                "2.1": "2.1 - Encarregado de Dados (DPO) Designado",
                "2.2": "2.2 - Mapeamento do Fluxo de Dados Pessoais",
                "2.3": "2.3 - Gestão de Consentimento e Direitos do Titular",
                "3.0": "3.0 - Infraestrutura de Rede e Data Center",
                "3.1": "3.1 - Política de Backup e Restauração de Dados",
                "3.1.1": "3.1.1 - Testes Periódicos de Recuperação de Backup",
                "3.1.1.1": "3.1.1.1 - Armazenamento de Backup Off-site / Nuvem",
                "3.2.1": "3.2.1 - Controle de Acesso Físico aos Servidores",
                "3.3": "3.3 - Monitoramento e Redundância de Conexão de Internet",
                "3.4": "3.4 - Gestão de Licenciamento de Software",
                "3.5": "3.5 - Atualização e Patching de Sistemas Operacionais",
                "3.6": "3.6 - Inventário Atualizado de Ativos de TI",
                "4.0": "4.0 - Serviços Digitais e Governo Eletrônico",
                "6.0": "6.0 - Portal da Transparência e Acesso à Informação",
                "6.1": "6.1 - Disponibilidade de Dados Abertos em Formato Reutilizável",
                "6.2": "6.2 - Atualização das Informações de Receitas e Despesas",
                "6.3": "6.3 - Ferramentas de Acessibilidade Web para Cidadãos",
                "6.4": "6.4 - Atendimento ao Cidadão e Ouvidoria Digital (e-SIC)",
                "7.0": "7.0 - Capacitação e Treinamento do Quadro de TI",
                "7.1": "7.1 - Quadro de Pessoal Próprio de TI",
                "7.2": "7.2 - Plano de Treinamento em Segurança Cibernética",
                "7.3": "7.3 - Certificações Técnicas da Equipe de TI",
                "8.0": "8.0 - Gestão de Contratos de TI e Terceirização",
                "8.2.1": "8.2.1 - Fiscalização e Acompanhamento de Contratos de TI",
                "8.2.2": "8.2.2 - Níveis de Serviço (SLA) Estabelecidos em Contratos",
                "9.1": "9.1 - Interoperabilidade e Integração de Sistemas Municipais"
            },
            "i-Amb": {
                "1.1.2": "1.1.2 - Conselho Municipal do Meio Ambiente Ativo",
                "1.1.3": "1.1.3 - Fundo Municipal do Meio Ambiente Operacional",
                "1.2": "1.2 - Licenciamento e Fiscalização Ambiental Local",
                "2.0": "2.0 - Educação Ambiental na Rede de Ensino",
                "2.1": "2.1 - Programas Continuados de Conscientização Ambiental",
                "3.0": "3.0 - Gestão de Recursos Hídricos e Bacias Hidrográficas",
                "3.1": "3.1 - Proteção de Nascentes e Áreas de Preservação Permanente",
                "4.0": "4.0 - Monitoramento da Qualidade do Ar",
                "5.2.1": "5.2.1 - Controle de Queimadas e Incêndios Florestais",
                "6.0": "6.0 - Gestão do Saneamento Ambiental",
                "6.1": "6.1 - Percentual de Coleta e Tratamento de Esgoto Sanitário",
                "6.2": "6.2 - Controle de Perdas na Rede de Distribuição de Água",
                "7.2": "7.2 - Coleta Seletiva de Resíduos Sólidos Urbano",
                "7.3": "7.3 - Destinação Adequada de Resíduos de Saúde (RSS)",
                "7.3.1": "7.3.1 - Tratamento de Resíduos Perigosos",
                "7.4": "7.4 - Logística Reversa de Lixo Eletrônico e Baterias",
                "7.4.1": "7.4.1 - Pontos de Entrega Voluntária (PEV) Instalados",
                "7.5": "7.5 - Compostagem de Resíduos Orgânicos",
                "7.7": "7.7 - Erradicação de Lixões e Gestão de Aterro Sanitário",
                "7.8": "7.8 - Licenciamento Ambiental do Aterro Sanitário",
                "7.8.1": "7.8.1 - Monitoramento do Chorume e Gases no Aterro",
                "7.9": "7.9 - Cooperativas de Catadores Apoiadas pelo Município",
                "8.2": "8.2 - Recuperação de Áreas Degradadas",
                "8.3": "8.3 - Reflorestamento com Espécies Nativas",
                "8.4": "8.4 - Unidades de Conservação Municipais Criadas e Mantidas",
                "8.4.1": "8.4.1 - Plano de Manejo das Unidades de Conservação",
                "8.4.2": "8.4.2 - Infraestrutura de Fiscalização das Áreas Protegidas",
                "8.4.3": "8.4.3 - Regularização Fundiária das Unidades de Conservação",
                "9.2": "9.2 - Uso de Energias Renováveis em Prédios Públicos",
                "9.3": "9.3 - Eficiência Energética na Frota Municipal",
                "9.3.1": "9.3.1 - Incentivo a Veículos Elétricos ou Híbridos",
                "11.2": "11.2 - Controle de Zooses e Manejo de Animais",
                "11.3": "11.3 - Castração e Microchipagem de Cães e Gatos",
                "11.3.2": "11.3.2 - Centro de Acolhimento e Bem-Estar Animal",
                "11.3.3": "11.3.3 - Campanhas de Vacinação Animal",
                "11.5": "11.5 - Fiscalização contra Maus-Tratos a Animais",
                "12.1": "12.1 - Plano de Adaptação às Mudanças Climáticas",
                "14.3": "14.3 - Drenagem Sustentável e Piscinões",
                "15": "15.0 - Combate à Poluição Sonora",
                "15.1": "15.1 - Fiscalização de Ruídos e Emissões Sonoras",
                "A4.1.1": "A4.1.1 - Auditoria Ambiental nas Atividades Poluidoras",
                "A4.1.2": "A4.1.2 - Monitoramento de Ruído Urbano",
                "A4.1.3": "A4.1.3 - Certificações e Selos Verdes Municipais",
                "A6": "A6 - Transparência nas Licenças Ambientais Emitidas"
            }
        }

        # Dicionário de Pontuações Máximas
        self.pontuacoes_maximas_por_dimensao = {
            "iCidade": {
                "1.0": 40, "1.3": 5, "1.4": 50, "2.0": 20, "2.1": 30, "2.2": 10,
                "3.0": 10, "3.1.1": 10, "5.0": 200, "7.0": 50, "7.1": 5, "7.2": 80,
                "7.3": 50, "7.4": 50, "7.5": 10, "7.6": 10, "8.0": 50, "8.1.1.1": 20,
                "8.2": 50, "9.0": 100, "15.0": 50, "16.0": 50, "C1.1": 50
            },
            "iGov-Ti": {
                "1.0": 30, "1.1": 30, "1.2": 30, "1.3": 30, "1.3.1": 30, "1.4.1": 40, "1.4.2": 20,
                "2.0": 40, "2.1": 20, "2.2": 40, "2.3": 20,
                "3.0": 50, "3.1": 20, "3.1.1": 40, "3.1.1.1": 10, "3.2.1": 10, "3.3": 30, "3.4": 30, "3.5": 30, "3.6": 20,
                "4.0": 40, "6.0": 20, "6.1": 20, "6.2": 20, "6.3": 10, "6.4": 30, "7.0": 25, "7.1": 10, "7.2": 10, "7.3": 5,
                "8.0": 40, "8.2.1": 50, "8.2.2": 30, "9.1": 120
            },
            "i-Amb": {
                "1.1.2": 20, "1.1.3": 5, "1.2": 20, "2.0": 10, "2.1": 50, "3.0": 10,
                "3.1": 20, "4.0": 20, "5.2.1": 20, "6.0": 20, "6.1": 50, "6.2": 25,
                "7.2": 2, "7.3": 10, "7.3.1": 20, "7.4": 10, "7.4.1": 20, "7.5": 30,
                "7.7": 30, "7.8": 20, "7.8.1": 50, "7.9": 3, "8.2": 2, "8.3": 10,
                "8.4": 20, "8.4.1": 10, "8.4.2": 30, "8.4.3": 50, "9.2": 100, "9.3": 5,
                "9.3.1": 5, "11.2": 2, "11.3": 30, "11.3.2": 20, "11.3.3": 40, "11.5": 10,
                "12.1": 54, "14.3": 30, "15": 2, "15.1": 3, "A4.1.1": 90, "A4.1.2": 20,
                "A4.1.3": 22, "A6": 5
            }
        }
        
        # Cria a engine de conexão com o PostgreSQL Neon DB
        self.engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    def consultar_anos(self, dimensao, quesito_id):
        try:
            with self.engine.connect() as conn:
                query = text("""
                    SELECT ano, valor 
                    FROM respostas 
                    WHERE id = :id AND LOWER(dimensao) = LOWER(:dimensao)
                    ORDER BY ano ASC;
                """)
                result = conn.execute(query, {"id": str(quesito_id), "dimensao": dimensao})
                return [(row.ano, row.valor) for row in result]
        except Exception as e:
            st.error(f"Erro ao consultar anos no PostgreSQL: {e}")
            return []

    def analisar_pontos_fracos(self, ano, dimensao):
        pontos_fracos = []
        penalidades_detectadas = []
        
        questoes = self.questoes_por_dimensao.get(dimensao, {})
        pontuacoes_maximas = self.pontuacoes_maximas_por_dimensao.get(dimensao, {})
        
        try:
            with self.engine.connect() as conn:
                query = text("""
                    SELECT id, valor, pontos 
                    FROM respostas 
                    WHERE ano = :ano AND LOWER(dimensao) = LOWER(:dimensao);
                """)
                rows = conn.execute(query, {"ano": int(ano), "dimensao": dimensao}).fetchall()
            
            for row in rows:
                qid = str(row.id)
                valor = row.valor
                pontos_reais = float(row.pontos) if row.pontos is not None else 0.0

                enunciado = questoes.get(qid, f"Quesito {qid}")

                if pontos_reais < 0:
                    penalidades_detectadas.append({
                        "id": qid,
                        "pergunta": enunciado,
                        "valor": valor,
                        "penalidade": pontos_reais
                    })
                elif qid in pontuacoes_maximas:
                    max_possivel = float(pontuacoes_maximas[qid])
                    if pontos_reais < max_possivel:
                        deficit = max_possivel - pontos_reais
                        pontos_fracos.append({
                            "id": qid,
                            "pergunta": enunciado,
                            "valor": valor,
                            "obtido": pontos_reais,
                            "maximo": max_possivel,
                            "deficit": deficit
                        })
            
            pontos_fracos.sort(key=lambda x: x["deficit"], reverse=True)
            penalidades_detectadas.sort(key=lambda x: x["penalidade"])
            return pontos_fracos, penalidades_detectadas
        except Exception as e:
            st.error(f"Erro ao analisar pontos fracos no PostgreSQL: {e}")
            return [], []

    def calcular_evolucao_pontos(self, dimensao):
        anos_validos = [2023, 2024, 2025, 2026, 2027]
        dados_anos = []
        
        try:
            with self.engine.connect() as conn:
                for ano in anos_validos:
                    q_bruto = text("""
                        SELECT SUM(pontos) FROM respostas 
                        WHERE ano = :ano AND LOWER(dimensao) = LOWER(:dimensao) AND pontos > 0;
                    """)
                    res_bruto = conn.execute(q_bruto, {"ano": ano, "dimensao": dimensao}).scalar()
                    pontos_brutos = float(res_bruto) if res_bruto else 0.0

                    q_penalidade = text("""
                        SELECT SUM(pontos) FROM respostas 
                        WHERE ano = :ano AND LOWER(dimensao) = LOWER(:dimensao) AND pontos < 0;
                    """)
                    res_penalidade = conn.execute(q_penalidade, {"ano": ano, "dimensao": dimensao}).scalar()
                    penalidades_negativas = float(res_penalidade) if res_penalidade else 0.0

                    total_liquido = pontos_brutos + penalidades_negativas
                    if total_liquido < 0:
                        total_liquido = 0.0
                    
                    max_dim = sum(self.pontuacoes_maximas_por_dimensao.get(dimensao, {}).values()) or 100
                    p_perc = (total_liquido / max_dim) * 100
                    
                    if p_perc <= 50:
                        faixa, cor = "C", "rgba(239, 68, 68, 0.85)"
                    elif p_perc <= 60:
                        faixa, cor = "C+", "rgba(249, 115, 22, 0.85)"
                    elif p_perc <= 75:
                        faixa, cor = "B", "rgba(229, 191, 5, 0.85)"
                    elif p_perc <= 90:
                        faixa, cor = "B+", "rgba(34, 197, 94, 0.85)"
                    else:
                        faixa, cor = "A", "rgba(22, 163, 74, 0.85)"
                    
                    dados_anos.append({
                        "ano": ano,
                        "bruto": pontos_brutos,
                        "penalidade": penalidades_negativas,
                        "liquido": total_liquido,
                        "faixa": faixa,
                        "cor_faixa": cor
                    })
            return dados_anos
        except Exception as e:
            st.error(f"Erro ao calcular evolução no PostgreSQL: {e}")
            return []


# ==============================================================================
# FUNÇÃO DE RENDERIZAÇÃO STREAMLIT
# ==============================================================================
def mostrar_chat_hal():
    st.title("🤖 HAL - Sistema de Diagnóstico TCESP")
    st.write("Conectado diretamente ao banco de dados **PostgreSQL (Neon DB)**.")

    if "hal_sistema" not in st.session_state:
        st.session_state.hal_sistema = SistemaHAL()
    sistema = st.session_state.hal_sistema

    if "hal_chat_history" not in st.session_state:
        st.session_state.hal_chat_history = []

    st.markdown(
        """
        <style>
        .chat-wrapper { max-width: 900px; margin: 0 auto; font-family: -apple-system, sans-serif; }
        .chat-bubble-user { background-color: #f4f4f4; color: #1d1d1f; padding: 14px 18px; border-radius: 18px; display: inline-block; max-width: 80%; margin-bottom: 20px; float: right; clear: both; }
        .chat-bubble-ia { display: flex; gap: 16px; margin-bottom: 25px; clear: both; align-items: flex-start; }
        .avatar-ia { background-color: #10a37f; color: white; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; flex-shrink: 0; }
        .content-ia { color: #2d3748; font-size: 15px; line-height: 1.6; width: 100%; }
        .card-ponto-fraco { background-color: #fff5f5; border-left: 4px solid #e53e3e; padding: 15px; border-radius: 6px; margin-bottom: 12px; font-size: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown('<div class="chat-wrapper">', unsafe_allow_html=True)

    dimensoes_disponiveis = ["iGov-Ti", "iCidade", "i-Amb"]
    dimensao_selecionada = st.selectbox("📂 Selecione a Dimensão Operacional:", dimensoes_disponiveis, index=0)

    st.markdown(
        f"""
        <div class="chat-bubble-ia">
            <div class="avatar-ia">HAL</div>
            <div class="content-ia">
                Conexão PostgreSQL ativa. Consultando dados remotos no Neon DB para o índice <b>{dimensao_selecionada}</b>.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(f"### 📊 Histórico de Performance Real - {dimensao_selecionada}")
    historico_performance = sistema.calcular_evolucao_pontos(dimensao_selecionada)
    
    if historico_performance:
        eixo_x = [f"Ano {d['ano']}" for d in historico_performance]
        valores_liquidos = [d['liquido'] for d in historico_performance]
        cores = [d['cor_faixa'] for d in historico_performance]
        textos = [f"Faixa {d['faixa']} ({d['liquido']:.1f} pts)" for d in historico_performance]

        fig = go.Figure(data=[
            go.Bar(
                x=eixo_x, 
                y=valores_liquidos,
                text=textos,
                textposition='auto',
                marker_color=cores
            )
        ])
        fig.update_layout(
            margin=dict(l=20, r=20, t=20, b=20),
            height=300,
            yaxis_title="Pontuação Líquida",
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nenhum dado estruturado foi retornado do PostgreSQL para esta dimensão.")

    # ==============================================================================
    # PARTE 1: Recuperação Segmentada de Respostas por Quesito
    # ==============================================================================
    st.markdown("---")
    questoes_atuais = sistema.questoes_por_dimensao.get(dimensao_selecionada, {})
    ids_ordenados = sorted(
        list(questoes_atuais.keys()), 
        key=lambda x: [float(n) for n in re.findall(r'\d+', x)] if re.search(r'\d+', x) else [0.0]
    )
    opcoes_select = ["-- Selecione o item que deseja analisar --"] + [f"{q_id} - {questoes_atuais[q_id]}" for q_id in ids_ordenados]
    
    selecionado = st.selectbox(f"💬 Recuperar Resposta do Banco PostgreSQL ({dimensao_selecionada}):", options=opcoes_select, key="sel_hal_split")

    if selecionado != "-- Selecione o item que deseja analisar --":
        id_alvo = selecionado.split(" - ")[0]
        historico = sistema.consultar_anos(dimensao_selecionada, id_alvo)
        dict_historico = dict(historico)

        st.markdown(f'<div class="chat-bubble-user">Qual o histórico do item {id_alvo}?</div>', unsafe_allow_html=True)

        anos_disponiveis = [2023, 2024, 2025, 2026, 2027]
        tabs = st.tabs([f"📅 Ano {ano}" for ano in anos_disponiveis])

        for i, ano in enumerate(anos_disponiveis):
            with tabs[i]:
                if ano in dict_historico:
                    st.success(f"**Resposta registrada:** {dict_historico[ano]}")
                elif str(ano) in dict_historico:
                    st.success(f"**Resposta registrada:** {dict_historico[str(ano)]}")
                else:
                    st.warning("Nenhum dado encontrado para este ano no banco de dados.")

    # ==============================================================================
    # PARTE 2: Painel de Auditoria e Diagnóstico de Gaps
    # ==============================================================================
    st.markdown("---")
    st.markdown(f"### 🚨 Painel de Diagnóstico de Gaps ({dimensao_selecionada})")
    ano_auditoria = st.selectbox("Selecione o Ano Fiscal para Auditar:", [2023, 2024, 2025, 2026, 2027], index=2)

    if st.button("🚀 Rastrear Vulnerabilidades", type="primary", use_container_width=True):
        dados_criticos, penalidades = sistema.analisar_pontos_fracos(ano_auditoria, dimensao_selecionada)
        
        if dados_criticos or penalidades:
            if penalidades:
                st.markdown("#### ⚠️ Penalidades Ativas")
                for pen in penalidades:
                    st.markdown(
                        f"""
                        <div class="card-ponto-fraco" style="border-left-color: #e53e3e; background-color: #fff5f5;">
                            <span style="font-weight:bold; color:#c53030; font-size:14px;">⚠️ ITEM {pen['id']} - PENALIDADE APLICADA</span><br>
                            <b>Valor salvo em banco:</b> "{pen['valor']}"<br>
                            Impacto financeiro/operacional: <span style="color:red; font-weight:bold;">{pen['penalidade']} pontos</span><br>
                            <small style="color:#4a5568;"><b>Enunciado:</b> {pen['pergunta']}</small>
                        </div>
                        """, unsafe_allow_html=True
                    )

            if dados_criticos:
                st.markdown("#### 📉 Gaps de Pontuação Máxima")
                for item in dados_criticos:
                    st.markdown(
                        f"""
                        <div class="card-ponto-fraco" style="border-left-color: #dd6b20; background-color: #fffaf0;">
                            <span style="font-weight:bold; color:#dd6b20; font-size:14px;">🔴 ITEM {item['id']} COM DEFICIT</span><br>
                            <b>Valor salvo em banco:</b> "{item['valor']}"<br>
                            Pontuação: {item['obtido']} de {item['maximo']} (Perda de <b>{item['deficit']}</b> pontos).<br>
                            <small style="color:#4a5568;"><b>Enunciado:</b> {item['pergunta']}</small>
                        </div>
                        """, unsafe_allow_html=True
                    )
        else:
            st.info(f"Nenhuma perda ou penalidade registrada no PostgreSQL para {dimensao_selecionada} no ano {ano_auditoria}.")

    # ==============================================================================
    # PARTE 3: ÁREA DE DIÁLOGO DO ASSISTENTE CHAT
    # ==============================================================================
    st.markdown("---")
    st.markdown("### 💬 Conversar com Assistente HAL")

    for msg in st.session_state.hal_chat_history:
        if msg["role"] == "user":
            st.markdown(f'<div class="chat-bubble-user">{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f"""
                <div class="chat-bubble-ia">
                    <div class="avatar-ia">HAL</div>
                    <div class="content-ia">{msg["content"]}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

    if prompt := st.chat_input("Pergunte algo ao HAL ou digite 'pontos fracos 2025'..."):
        st.markdown(f'<div class="chat-bubble-user">{prompt}</div>', unsafe_allow_html=True)
        st.session_state.hal_chat_history.append({"role": "user", "content": prompt})
        
        prompt_limpo = prompt.lower()
        match_ano = re.search(r'\b(202[3-7])\b', prompt_limpo)
        
        if "ponto" in prompt_limpo and match_ano:
            ano_busca = int(match_ano.group(1))
            pontos_fracos, penalidades = sistema.analisar_pontos_fracos(ano_busca, dimensao_selecionada)
            resposta_ia = f"### 🔍 Diagnóstico Rápido ({dimensao_selecionada} - {ano_busca})<br><br>"
            
            if penalidades:
                resposta_ia += "⚠️ **Penalidades cruciais:**<br>"
                for pen in penalidades[:2]:
                    resposta_ia += f"- **Item {pen['id']}**: {pen['pergunta']} ({pen['penalidade']} pts)<br>"
            if pontos_fracos:
                resposta_ia += "<br>📉 **Déficits prioritários:**<br>"
                for pt in pontos_fracos[:3]:
                    resposta_ia += f"- **Item {pt['id']}**: Defasagem de {pt['deficit']} pts.<br>"
            if not penalidades and not pontos_fracos:
                resposta_ia += "Tudo limpo! Não identifiquei perdas de pontuação registradas no banco Neon DB."
        else:
            resposta_ia = f"Processando dados de **{dimensao_selecionada}**. Para auditoria automatizada via prompt, especifique comandos contendo o ano desejado (ex: *'analisar pontos fracos 2025'*)."

        st.markdown(
            f"""
            <div class="chat-bubble-ia">
                <div class="avatar-ia">HAL</div>
                <div class="content-ia">{resposta_ia}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.session_state.hal_chat_history.append({"role": "assistant", "content": resposta_ia})
        
    st.markdown('</div>', unsafe_allow_html=True)


# ==============================================================================
# DISPARO DIRETO DA APLICAÇÃO (GARANTE QUE O STREAMLIT CARREGUE A TELA)
# ==============================================================================
mostrar_chat_hal()
