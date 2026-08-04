import os
import re
import json
import time
import psycopg2
import psycopg2.extras
import streamlit as st
import plotly.graph_objects as go

# URL do Neon definida diretamente no código
DATABASE_URL = "postgresql://neondb_owner:npg_beMKhVR2N4wo@ep-divine-sky-awx1636y-pooler.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


class SistemaHAL:
    def __init__(self):
        self.questoes_por_dimensao = {}
        self.pontuacoes_maximas_por_dimensao = {}
        self.carregar_dicionarios_globais()

    def get_db_connection(self):
        """
        Conecta diretamente ao banco PostgreSQL no Neon.
        """
        try:
            conn = psycopg2.connect(
                DATABASE_URL,
                cursor_factory=psycopg2.extras.DictCursor
            )
            return conn
        except Exception as e:
            st.error(f"Erro ao conectar ao PostgreSQL: {e}")
            return None

    def consultar_anos(self, dimensao, quesito_id):
        """
        Consulta o histórico de respostas de um item em uma determinada dimensão.
        """
        conn = self.get_db_connection()
        if not conn:
            return []
        
        try:
            with conn.cursor() as cursor:
                # Usa %s (padrão PostgreSQL) em vez do ?
                cursor.execute(
                    "SELECT ano, valor FROM respostas WHERE id = %s AND dimensao = %s ORDER BY ano ASC;",
                    (quesito_id, dimensao)
                )
                return cursor.fetchall()
            except Exception:
                return []
        finally:
            conn.close()

    def analisar_pontos_fracos(self, ano, dimensao):
        """
        Audita falhas e penalidades registradas para uma dimensão/ano específico.
        """
        conn = self.get_db_connection()
        if not conn:
            return [], []
        
        pontos_fracos = []
        penalidades_detectadas = []
        
        questoes = self.questoes_por_dimensao.get(dimensao, {})
        pontuacoes_maximas = self.pontuacoes_maximas_por_dimensao.get(dimensao, {})
        
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, valor, pontos FROM respostas WHERE ano = %s AND dimensao = %s;",
                    (ano, dimensao)
                )
                rows = cursor.fetchall()
                
                for qid, valor, pontos_reais in rows:
                    pontos_reais = float(pontos_reais or 0)
                    if qid in questoes:
                        if pontos_reais < 0:
                            penalidades_detectadas.append({
                                "id": qid, 
                                "pergunta": questoes.get(qid),
                                "valor": valor, 
                                "penalidade": pontos_reais
                            })
                        elif qid in pontuacoes_maximas:
                            max_possivel = float(pontuacoes_maximas[qid])
                            if pontos_reais < max_possivel:
                                deficit = max_possivel - pontos_reais
                                pontos_fracos.append({
                                    "id": qid, 
                                    "pergunta": questoes.get(qid),
                                    "valor": valor, 
                                    "obtido": pontos_reais,
                                    "maximo": max_possivel, 
                                    "deficit": deficit
                                })
                
                pontos_fracos.sort(key=lambda x: x["deficit"], reverse=True)
                penalidades_detectadas.sort(key=lambda x: x["penalidade"])
                return pontos_fracos, penalidades_detectadas
        except Exception:
            return [], []
        finally:
            conn.close()

    def calcular_evolucao_pontos(self, dimensao):
        """
        Calcula as pontuações e métricas históricas de desempenho no PostgreSQL.
        """
        conn = self.get_db_connection()
        if not conn:
            return []
        
        anos_validos = [2023, 2024, 2025, 2026, 2027]
        dados_anos = []
        
        try:
            with conn.cursor() as cursor:
                for ano in anos_validos:
                    cursor.execute(
                        "SELECT SUM(pontos) FROM respostas WHERE ano = %s AND dimensao = %s AND pontos > 0;",
                        (ano, dimensao)
                    )
                    res_bruto = cursor.fetchone()[0]
                    pontos_brutos = float(res_bruto) if res_bruto else 0.0

                    cursor.execute(
                        "SELECT SUM(pontos) FROM respostas WHERE ano = %s AND dimensao = %s AND pontos < 0;",
                        (ano, dimensao)
                    )
                    res_penalidade = cursor.fetchone()[0]
                    penalidades_negativas = float(res_penalidade) if res_penalidade else 0.0

                    total_liquido = pontos_brutos + penalidades_negativas
                    if total_liquido < 0:
                        total_liquido = 0.0
                    
                    max_dim = sum(self.pontuacoes_maximas_por_dimensao.get(dimensao, {}).values()) or 100
                    p_perc = (total_liquido / max_dim) * 100
                    
                    if p_perc <= 50:
                        faixa, cor = "C",  "rgba(239, 68, 68, 0.85)"
                    elif p_perc <= 60:
                        faixa, cor = "C+", "rgba(249, 115, 22, 0.85)"
                    elif p_perc <= 75:
                        faixa, cor = "B",  "rgba(229, 191, 5, 0.85)"
                    elif p_perc <= 90:
                        faixa, cor = "B+", "rgba(34, 197, 94, 0.85)"
                    else:
                        faixa, cor = "A",  "rgba(22, 163, 74, 0.85)"
                    
                    dados_anos.append({
                        "ano": ano, 
                        "bruto": pontos_brutos, 
                        "penalidade": penalidades_negativas,
                        "liquido": total_liquido, 
                        "faixa": faixa, 
                        "cor_faixa": cor
                    })
            return dados_anos
        except Exception:
            return []
        finally:
            conn.close()

    def carregar_dicionarios_globais(self):
        # Dicionários de Questões
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": "Foi criada a Coordenadoria Municipal de Proteção e Defesa Civil (COMPDEC)?",
                "1.3": "A COMPDEC está associada ou subordinada a qual secretaria?",
                "1.4": "Atuação de forma sistêmica articulada com a COMPDEC?",
                "2.0": "Capacitação de agentes para ações municipais de Defesa Civil?",
                "3.0": "Ações para estimular participação de entidades privadas e voluntários?",
                "4.2": "Carta Geotécnica consta no Plano Diretor?",
                "5.0": "Mapeamento e identificação das principais ameaças?",
                "7.0": "Possui Plano de Contingência Municipal (PLANCON)?",
                "8.0": "Possui canal de atendimento de emergência à população?",
                "10.0": "Elaborou seu Plano de Mobilidade Urbana?"
            },
            "iGov-Ti": {
                "1.0": "Possui área ou setor focado em TIC?",
                "1.2": "Atribuições do pessoal de TIC definidas formalmente?",
                "2.0": "Possui PDTIC vigente com metas e diretrizes?",
                "3.0": "Política de Segurança da Informação formalmente instituída?",
                "4.0": "Regulamentou a Lei de Acesso à Informação (LAI)?",
                "5.0": "Regulamentou a Lei de Governo Digital?",
                "10.0": "Regulamentou o tratamento de dados pessoais (LGPD)?"
            },
            "i-Amb": {
                "1.0": "Estrutura organizacional instalada para assuntos de Meio Ambiente?",
                "2.0": "Promove participação em Programas de Educação Ambiental?",
                "7.0": "Plano Municipal ou Regional de Saneamento Básico instituído?",
                "8.0": "Plano de Gestão Integrada de Resíduos Sólidos instituído?",
                "9.0": "Realiza de forma efetiva a coleta seletiva?",
                "10.0": "Realiza serviço regular de coleta de lixo doméstico?"
            }
        }
        
        # Pontuações Máximas Padrão por Quesito
        self.pontuacoes_maximas_por_dimensao = {
            "iCidade": {"1.0": 10, "1.3": 5, "1.4": 5, "2.0": 10, "3.0": 10, "4.2": 10, "5.0": 10, "7.0": 15, "8.0": 10, "10.0": 15},
            "iGov-Ti": {"1.0": 15, "1.2": 10, "2.0": 15, "3.0": 15, "4.0": 15, "5.0": 15, "10.0": 15},
            "i-Amb": {"1.0": 10, "2.0": 10, "7.0": 20, "8.0": 20, "9.0": 20, "10.0": 20}
        }


def mostrar_chat_hal():
    if "hal_sistema" not in st.session_state:
        st.session_state.hal_sistema = SistemaHAL()
    sistema = st.session_state.hal_sistema

    if "hal_chat_history" not in st.session_state:
        st.session_state.hal_chat_history = []

    st.markdown(
        """
        <style>
        .chat-wrapper { max-width: 850px; margin: 0 auto; font-family: -apple-system, sans-serif; }
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
                Roteamento concluído com sucesso. Conectado ao <b>PostgreSQL (Neon)</b> processando o índice <b>{dimensao_selecionada}</b>.
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
        textos = [f"Faixa {d['faixa']}" for d in historico_performance]

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
        st.info("Nenhum dado estruturado foi retornado para a performance desta dimensão.")

    # ==============================================================================
    # PARTE RECUPERADA 1: Recuperação Segmentada de Respostas
    # ==============================================================================
    questoes_atuais = sistema.questoes_por_dimensao.get(dimensao_selecionada, {})
    ids_ordenados = sorted(list(questoes_atuais.keys()), key=lambda x: [float(n) for n in re.findall(r'\d+', x)] if re.search(r'\d+', x) else [0.0])
    opcoes_select = ["-- Selecione o item que deseja analisar --"] + [f"{q_id} - {questoes_atuais[q_id]}" for q_id in ids_ordenados]
    
    st.markdown("<br>", unsafe_allow_html=True)
    selecionado = st.selectbox(f"💬 Recuperar Resposta do Banco ({dimensao_selecionada}):", options=opcoes_select, key="sel_hal_split")

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
                    st.warning("Nenhum dado encontrado para este ano neste banco.")

    # ==============================================================================
    # PARTE RECUPERADA 2: Painel de Auditoria por Banco
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
            st.info(f"Nenhuma perda ou penalidade registrada para {dimensao_selecionada} no ano {ano_auditoria}.")

    # ==============================================================================
    # ÁREA DE DIÁLOGO DO ASSISTENTE CHAT
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
                resposta_ia += "Tudo limpo! Não identifiquei perdas de pontuação estruturadas no banco."
        else:
            resposta_ia = f"Processando dados de **{dimensao_selecionada}**. Para auditoria automatizada via prompt, especifique comandos contendo o ano desejado."

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


def main():
    mostrar_chat_hal()
