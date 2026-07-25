import json
import logging
import os
import re
import sys
import warnings
from datetime import date, datetime
from io import BytesIO

import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import streamlit as st
from plotly.subplots import make_subplots
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

# =============================================================================
# IMPORTS DO REPORTLAB (CORRIGIDOS COM ALINHAMENTOS ENUMS)
# =============================================================================
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT  # <-- Adicionado para alinhar células e textos
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# =============================================================================
# CONFIGURAÇÃO DE ESTILOS PADRÃO PARA RELATÓRIOS PDF (iFiscal)
# =============================================================================
styles = getSampleStyleSheet()

# Estilo Padrão para Tabelas (Evita NameError: style_tabela_padrao)
style_tabela_padrao = ParagraphStyle(
    "TabelaPadrao",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    alignment=TA_LEFT,
)

# Estilo Centralizado
style_tabela_centro = ParagraphStyle(
    "TabelaCentro",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    alignment=TA_CENTER,
)

# Estilo Alinhado à Esquerda
style_tabela_esquerda = ParagraphStyle(
    "TabelaEsquerda",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    alignment=TA_LEFT,
)

# Estilo Alinhado à Direita
style_tabela_direita = ParagraphStyle(
    "TabelaDireita",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    alignment=TA_RIGHT,
)

# Estilo para Cabeçalhos de Tabela
style_tabela_cabecalho = ParagraphStyle(
    "TabelaCabecalho",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=9,
    leading=11,
    alignment=TA_CENTER,
    textColor=colors.whitesmoke,
)
import json
import logging
import re
import warnings
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES INICIAIS E SUPRESSÃO DE WARNINGS
# -----------------------------------------------------------------------------
warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)

# =============================================================================
# REGEX DE VALIDAÇÃO E CONSTANTES GLOBAIS
# =============================================================================
REGEX_PURE_URL = r'((https?://[^\s<>"]+))'

FAIXA_CORES = {
    "C": "#ef4444",
    "C+": "#f97316",
    "B": "#eab308",
    "B+": "#22c55e",
    "A": "#16a34a",
}

CATEGORIAS_MAP = {
    "infraestrutura": {
        "label": "Infraestrutura e Setor Fiscal",
        "qids": ["1.1", "1.2", "1.3", "1.4", "1.5", "1.5.1"],
    },
    "planejamento": {
        "label": "Planejamento e Diretrizes Orçamentárias",
        "qids": ["2.0", "3.0", "4.3"],
    },
    "transparencia_gov": {
        "label": "Transparência Fiscal e Governo Digital",
        "qids": ["5.0", "5.3", "5.4", "6.0"],
    },
    "sistemas_gestao": {
        "label": "Sistemas de Gestão Financeira e Operações",
        "qids": ["8.0", "8.1", "8.2", "9.4", "9.4.1", "11.0", "13.0", "13.3"],
    },
    "seguranca_processos": {
        "label": "Segurança da Informação e Processos Fiscais",
        "qids": ["18.1", "19.0", "19.1", "20.0", "20.1", "21.0", "22.0"],
    },
    "auditoria_final": {
        "label": "Quesitos de Auditoria Final (Bloco F)",
        "qids": [
            "F1", "F2", "F3", "F4", "F5", "F8", "F10",
            "F12", "F13", "F14", "F15", "F16", "F17", "F18", "F20",
        ],
    },
}

PONTUACOES_MAX = {
    "1.1": 0.5, "1.2": 1.5, "1.3": 10.0, "1.4": 3.0, "1.5": 5.0, "1.5.1": 5.0,
    "2.0": 4.0, "3.0": 30.0, "4.3": 5.0,
    "5.0": 3.0, "5.3": 3.0, "5.4": 6.0, "6.0": 2.0,
    "8.0": 1.0, "8.1": 2.0, "8.2": 15.0, "9.4": 2.0, "9.4.1": 3.0, "11.0": 3.0, "13.0": 1.0, "13.3": 9.0,
    "18.1": 15.0, "19.0": 3.0, "19.1": 3.0, "20.0": 3.0, "20.1": 6.0, "21.0": 3.0, "22.0": 3.0,
    "F1": 75.0, "F2": 75.0, "F3": 100.0, "F4": 25.0, "F5": 25.0,
    "F8": 75.0, "F10": 75.0, "F12": 50.0, "F13": 50.0, "F14": 50.0,
    "F15": 25.0, "F16": 25.0, "F17": 75.0, "F18": 75.0, "F20": 50.0,
}

TEXTO_PERGUNTAS = {
    "1.1": "A estrutura de fiscalização tributária municipal conta com corpo técnico próprio?",
    "1.2": "As instalações e equipamentos do setor de arrecadação atendem à demanda operacional?",
    "1.3": "Percentual de incremento real na arrecadação de ISSQN em relação ao ano base.",
    "1.4": "Possui legislação específica atualizada sobre a planta genérica de valores (IPTU)?",
    "1.5": "Regularidade e tempestividade no envio de dados de receita ao portal da transparência.",
    "1.5.1": "Existem mecanismos informatizados de conciliação bancária de receitas automáticos?",
    "2.0": "Compatibilidade das metas da LDO com os limites fiscais da Lei de Responsabilidade Fiscal.",
    "3.0": "Cumprimento das metas fiscais anuais de resultado primário e nominal fixadas na LOA.",
    "4.3": "Evidências de audiências públicas realizadas para discussão das peças orçamentárias.",
    "5.0": "O portal institucional atende à Lei de Acesso à Informação (LAI) em sua totalidade?",
    "5.3": "Disponibilização de ferramentas de Governo Digital e serviços tributários ao cidadão.",
    "5.4": "Publicação tempestiva dos Relatórios de Gestão Fiscal (RGF) e Resumido de Execução (RREO).",
    "6.0": "Existência de canal ou ouvidoria ativa para denúncias sobre inconformidades fiscais.",
    "8.0": "O sistema contábil emite alertas automatizados sobre o atingimento de limites da LRF?",
    "8.1": "O sistema integrado de gestão permite rastreabilidade completa de restos a pagar?",
    "8.2": "Nível de aderência do plano de contas municipal às diretrizes da STN (PCASP).",
    "9.4": "Existência de rotinas formais para controle e inscrição de créditos em Dívida Ativa.",
    "9.4.1": "A cobrança administrativa ou judicial de créditos tributários possui fluxo normatizado?",
    "11.0": "Controle interno atua na verificação prévia de conformidade das despesas fiscais?",
    "13.0": "Rotinas automatizadas para validação cadastral de fornecedores integradas ao TCE.",
    "13.3": "Adoção preferencial de pregão eletrônico e nova lei de licitações para atos de gestão.",
    "18.1": "Aplicação de políticas rígidas de segurança da informação nos bancos de dados fiscais.",
    "19.0": "Plano de contingência operacional formalizado em caso de indisponibilidade de sistemas.",
    "19.1": "Periodicidade e segurança dos backups dos sistemas de arrecadação e contabilidade.",
    "20.0": "Treinamento técnico continuado oferecido aos servidores da área de gestão fiscal.",
    "20.1": "Metodologia estruturada para identificação de gargalos de sonegação fiscal no município.",
    "21.0": "Regulamentação municipal sobre o teto remuneratório constitucional de agentes públicos.",
    "22.0": "Ações de combate à renúncia ilegal de receitas e monitoramento de benefícios fiscais.",
    "F1": "Bloqueio Crítico TCE: Rejeição integral de contas do exercício anterior por descumprimento de metas?",
    "F2": "Gatilho de Alerta: Gastos com pessoal consolidado acima do limite prudencial estabelecido?",
    "F3": "Compromisso de Gestão: Ocorrência de déficit financeiro estrutural sem justificativa aceita?",
    "F4": "Irregularidade em Repasses: Retenção ou atraso sistemático de duodécimo ao Legislativo?",
    "F5": "Ordem Cronológica: Quebra injustificada na ordem cronológica de pagamentos a fornecedores?",
    "F8": "Inconsistência Patrimonial: Divergências graves não conciliadas entre o balanço e inventários?",
    "F10": "Mecanismos Anticorrupção: Falha grave na instituição ou atuação do sistema de controle interno?",
    "F12": "Transparência Omissa: Não disponibilização de dados fiscais no SICONFI nos prazos legais?",
    "F13": "Renúncia Injustificada: Concessão de isenções tributárias sem estimativa de impacto fiscal?",
    "F14": "Endividamento Extremo: Operações de crédito realizadas acima do limite autorizado pelo Senado?",
    "F15": "Precatórios Judiciais: Descumprimento do regime especial ou ordinário de pagamento de precatórios?",
    "F16": "Créditos Adicionais: Abertura de créditos suplementares sem a existência de recursos disponíveis?",
    "F17": "Fundo de Previdência: Existência de repasses atrasados ou insuficientes ao RPPS municipal?",
    "F18": "Educação/Saúde: Descumprimento das aplicações mínimas constitucionais em MDE ou ASPS?",
    "F20": "Dívida Ativa Inerte: Ausência absoluta de cobrança judicial que resulte em prescrição de débitos?",
}

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO
# =============================================================================
@st.dialog("⚠️ Atenção! Evidência em Link Externo")
def modal_aviso_link(qid, links_encontrados):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    for lk in links_encontrados:
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")

    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**

    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}_fiscal"):
        st.rerun()

# =============================================================================
# BANCO DE DADOS NEON (ISOLADO PARA O iFISCAL)
# =============================================================================
def get_connection():
    """Conecta ao banco Neon PostgreSQL usando st.secrets."""
    return psycopg2.connect(st.secrets["DATABASE_URL"], sslmode="require")


def init_db_ifiscal():
    """Inicializa a tabela EXCLUSIVA do i-Fiscal no PostgreSQL."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS respostas_ifiscal (
                        id SERIAL PRIMARY KEY,
                        ano INT NOT NULL,
                        quesito VARCHAR(50) NOT NULL,
                        resposta TEXT,
                        pontos DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                        detalhes JSONB DEFAULT '{}'::jsonb,
                        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT unq_ano_quesito_ifiscal UNIQUE(ano, quesito)
                    );
                    """
                )
            conn.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar tabela respostas_ifiscal: {e}")


# Inicializa a tabela do iFiscal ao importar
try:
    init_db_ifiscal()
except Exception as e:
    logging.error(f"Erro na inicialização da tabela respostas_ifiscal: {e}")


def load_respostas_ifiscal(ano):
    """Carrega EXCLUSIVAMENTE as respostas do i-Fiscal do banco."""
    dados_ano = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT quesito, resposta, pontos, detalhes FROM respostas_ifiscal WHERE ano = %s",
                    (int(ano),),
                )
                rows = cursor.fetchall()
                for row in rows:
                    quesito, resposta, pontos, detalhes_raw = row
                    
                    detalhes = detalhes_raw if isinstance(detalhes_raw, dict) else {}
                    if isinstance(detalhes_raw, str):
                        try:
                            detalhes = json.loads(detalhes_raw)
                        except Exception:
                            detalhes = {}

                    dados_ano[str(quesito)] = {
                        "valor": resposta or "",
                        "pontos": float(pontos) if pontos is not None else 0.0,
                        "link": detalhes.get("link", ""),
                        "comentarios": detalhes.get("comentarios", []),
                    }
    except Exception as e:
        logging.error(f"Erro ao carregar respostas_ifiscal do Neon: {e}")
    return dados_ano


def save_resp_ifiscal(qid, valor, pontos, link, comentarios=None):
    """Salva a resposta do i-Fiscal isolada na tabela respostas_ifiscal."""
    ano_sel = st.session_state.get(
        "ano_referencia_ifiscal",
        st.session_state.get("ano_referencia_global"),
    )
    if not ano_sel:
        return

    detalhes_obj = {
        "link": str(link or ""),
        "comentarios": comentarios if comentarios is not None else []
    }
    detalhes_json = json.dumps(detalhes_obj, ensure_ascii=False)
    timestamp_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO respostas_ifiscal (ano, quesito, resposta, pontos, detalhes, atualizado_em)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (ano, quesito) DO UPDATE SET
                        resposta = EXCLUDED.resposta,
                        pontos = EXCLUDED.pontos,
                        detalhes = EXCLUDED.detalhes,
                        atualizado_em = EXCLUDED.atualizado_em;
                    """,
                    (
                        int(ano_sel),
                        str(qid),
                        str(valor or ""),
                        float(pontos or 0.0),
                        detalhes_json,
                        timestamp_atual,
                    ),
                )
            conn.commit()
    except Exception as e:
        st.error(f"Erro ao salvar {qid} na tabela respostas_ifiscal: {e}")


def bloco_comentarios_ifiscal(questao_id, res_data, sufixo="fiscal"):
    """Gera o diálogo interno com histórico e gerenciamento de comentários do iFiscal."""
    ano_sel = st.session_state.get(
        "ano_referencia_ifiscal", datetime.now().year
    )
    usuario_atual = st.session_state.get(
        "username", st.session_state.get("usuario", "Usuário Anônimo")
    )

    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_{id_chave}_{ano_sel}"

    if key_estado_limpar not in st.session_state:
        st.session_state[key_estado_limpar] = False

    st.markdown("---")
    dados_questao = res_data.get(questao_id, {})
    historico = dados_questao.get("comentarios", [])

    status_global = "Resolvido"
    for com in historico:
        if "status_definido" in com:
            status_global = com["status_definido"]

    badge_status = (
        "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"
    )

    with st.expander(
        f"💬 Diálogo Interno {id_chave} | Status: {badge_status}",
        expanded=(status_global == "Pendente"),
    ):
        st.markdown(
            "<b style='font-size: 13px;'>Status Atual do Quesito:</b>",
            unsafe_allow_html=True,
        )
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = (
            opcoes_status.index(status_global)
            if status_global in opcoes_status
            else 0
        )

        novo_status_clicado = st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=f"rad_status_{id_chave}_{ano_sel}",
            label_visibility="collapsed",
        )

        if novo_status_clicado != status_global:
            log_mudanca = {
                "autor": "Sistema / " + usuario_atual,
                "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "texto": f"ℹ️ Alterou o status do quesito para: **{novo_status_clicado.upper()}**.",
                "status_definido": novo_status_clicado,
            }
            historico.append(log_mudanca)
            save_resp_ifiscal(
                qid=questao_id,
                valor=dados_questao.get("valor", ""),
                pontos=dados_questao.get("pontos", 0.0),
                link=dados_questao.get("link", ""),
                comentarios=historico,
            )
            st.rerun()

        st.markdown(
            "<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True
        )

        if historico:
            for idx, com in enumerate(historico):
                col_balao, col_lixeira = st.columns([11, 1])
                with col_balao:
                    if "Sistema /" in com["autor"]:
                        st.markdown(
                            f"""
                            <div style="background-color: #f1f3f5; padding: 6px 12px; border-radius: 6px; margin-bottom: 4px; border-left: 3px solid #ced4da;">
                                <span style="font-size: 11px; color: #6c757d; font-style: italic;">{com['autor']} - {com['data']}</span>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #495057; font-style: italic;">{com['texto']}</p>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f"""
                            <div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #1e88e5;">
                                <span style="font-size: 11px; color: #1e88e5; font-weight: bold;">{com['autor']}</span>
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{com['data']}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{com['texto']}</p>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                with col_lixeira:
                    st.markdown(
                        "<div style='margin-top: 10px;'></div>",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "🗑️",
                        key=f"btn_del_com_{id_chave}_{idx}_{ano_sel}",
                        help="Excluir este comentário",
                    ):
                        historico.pop(idx)
                        save_resp_ifiscal(
                            qid=questao_id,
                            valor=dados_questao.get("valor", ""),
                            pontos=dados_questao.get("pontos", 0.0),
                            link=dados_questao.get("link", ""),
                            comentarios=historico,
                        )
                        st.rerun()
        else:
            st.markdown(
                "<p style='font-size: 12px; color: #999; font-style: italic;'>Nenhum comentário enviado ainda.</p>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<b style='font-size: 13px;'>Adicionar Novo Comentário:</b>",
            unsafe_allow_html=True,
        )

        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False

        novo_texto = st.text_area(
            "Digite sua mensagem:",
            key=key_texto,
            height=80,
            label_visibility="collapsed",
        )

        if st.button(
            "Postar Comentário",
            key=f"btn_com_{id_chave}_{ano_sel}",
            type="primary",
        ):
            if novo_texto.strip():
                nova_mensagem = {
                    "autor": usuario_atual,
                    "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "texto": novo_texto.strip(),
                    "status_definido": status_global,
                }
                historico.append(nova_mensagem)
                save_resp_ifiscal(
                    qid=questao_id,
                    valor=dados_questao.get("valor", ""),
                    pontos=dados_questao.get("pontos", 0.0),
                    link=dados_questao.get("link", ""),
                    comentarios=historico,
                )
                st.session_state[key_estado_limpar] = True
                st.rerun()


def get_all_years_data_ifiscal():
    """Busca histórico EXCLUSIVO do i-Fiscal no Neon."""
    all_data = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT quesito, ano, resposta, pontos, detalhes FROM respostas_ifiscal ORDER BY ano DESC"
                )
                rows = cursor.fetchall()
                for row in rows:
                    quesito, ano, resposta, pontos, detalhes_raw = row
                    
                    detalhes = detalhes_raw if isinstance(detalhes_raw, dict) else {}
                    if isinstance(detalhes_raw, str):
                        try:
                            detalhes = json.loads(detalhes_raw)
                        except Exception:
                            detalhes = {}

                    if ano not in all_data:
                        all_data[ano] = {}
                    all_data[ano][str(quesito)] = {
                        "valor": resposta or "",
                        "pontos": float(pontos) if pontos is not None else 0.0,
                        "link": detalhes.get("link", ""),
                        "comentarios": detalhes.get("comentarios", []),
                    }
    except Exception as e:
        logging.error(f"Erro ao buscar histórico do iFiscal no Neon: {e}")
    return all_data
# =============================================================================
# 2. GERADOR DO RELATÓRIO PDF (i-Fiscal)
# =============================================================================


def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=50,
    )
    elements = []
    styles = getSampleStyleSheet()

    # -------------------------------------------------------------------------
    # 1. ESTILOS DO REPORTLAB PARA EVITAR NameError DE ESTILOS
    # -------------------------------------------------------------------------
    style_titulo_capa = ParagraphStyle(
        "TituloCapa",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#001A4D"),
        alignment=TA_CENTER,
    )

    style_ano_capa = ParagraphStyle(
        "AnoCapa",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=16,
        textColor=colors.HexColor("#7f8c8d"),
        alignment=TA_CENTER,
    )

    style_tabela_padrao = ParagraphStyle(
        "TabelaPadrao",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )

    style_tabela_centro = ParagraphStyle(
        "TabelaCentro",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
    )

    style_tabela_esquerda = ParagraphStyle(
        "TabelaEsquerda",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )

    style_tabela_direita = ParagraphStyle(
        "TabelaDireita",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        alignment=TA_RIGHT,
    )

    style_tabela_cabecalho = ParagraphStyle(
        "TabelaCabecalho",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.whitesmoke,
    )

    # -------------------------------------------------------------------------
    # 2. INICIALIZAÇÃO DE LISTAS DE SUBQUESTÕES (EVITA NameError: subquestoes_11)
    # -------------------------------------------------------------------------
    subquestoes_11 = []
    subquestoes_10 = []
    subquestoes_12 = []

    # Preenchimento dinâmico a partir dos dados do questionário
    if isinstance(dados, dict):
        for k, v in dados.items():
            if isinstance(v, dict):
                qid = str(v.get("qid", k))
                # Captura de subquestões do grupo 1.1 ou similares
                if qid.startswith("1.1") or k.startswith("1.1"):
                    subquestoes_11.append(v)
                elif qid.startswith("1.0") or k.startswith("1.0"):
                    subquestoes_10.append(v)
                elif qid.startswith("1.2") or k.startswith("1.2"):
                    subquestoes_12.append(v)

    # -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 100))
    try:
        logo = Image("iegm.png", width=380, height=180)
        logo.hAlign = "CENTER"
        elements.append(logo)
    except Exception:
        elements.append(
            Paragraph("[Logo: i-Fiscal / IEGM]", styles["Title"])
        )

    elements.append(Spacer(1, 50))
    elements.append(Paragraph("Relatório do i-fiscal", style_titulo_capa))
    elements.append(Spacer(1, 15))

    elements.append(Paragraph(f"{ano}", style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle(
        "ItemEsq",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#2c3e50"),
    )
    style_pag_direita = ParagraphStyle(
        "PagDir",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#1b4f72"),
        alignment=TA_RIGHT,
    )

    dados_sumario = [
        [
            Paragraph(
                "1. Resumo Executivo (Análise Comparativa)",
                style_item_esquerda,
            ),
            Paragraph("Pág. 3", style_pag_direita),
        ],
        [
            Paragraph(
                "2. Análise de Desempenho por Quesito", style_item_esquerda
            ),
            Paragraph("Pág. 3", style_pag_direita),
        ],
        [
            Paragraph(
                "3. Análise de Impacto e Penalidades", style_item_esquerda
            ),
            Paragraph("Pág. 4", style_pag_direita),
        ],
        [
            Paragraph(
                "4. Diagnóstico de Reincidências", style_item_esquerda
            ),
            Paragraph("Pág. 4", style_pag_direita),
        ],
        [
            Paragraph(
                "5. Alinhamento com a Agenda 2030 (ODS)", style_item_esquerda
            ),
            Paragraph("Pág. 4", style_pag_direita),
        ],
        [
            Paragraph(
                "6. Série Histórica do I-Fiscal", style_item_esquerda
            ),
            Paragraph("Pág. 5", style_pag_direita),
        ],
    ]

    tabela_sumario = Table(dados_sumario, colWidths=[400, 90])
    tabela_sumario.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            (
                "LINEBELOW",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#bdc3c7"),
                1,
                (2, 4),
            ),
        ])
    )
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # RESTANTE DO SEU CONTEÚDO DO PDF
    # (Páginas 3, 4, 5, tabelas com subquestoes_11, etc.)
    # -------------------------------------------------------------------------

    # Constrói o documento PDF na memória
    doc.build(elements)
    buffer.seek(0)
    return buffer

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO (Adaptado 100% para i-Fiscal)
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-FISCAL - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))

    # --- TÓPICO 1 ---
    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))

    nota_atual = float(total)
    ano_atual = int(str(ano).strip()[:4])
    ano_ant = ano_atual - 1

    def converter_pontos_em_faixa_ifiscal(pontos):
        pts = float(pontos)
        if pts < 500.0:              return "C"
        elif 500.0 <= pts <= 599.9:  return "C+"
        elif 600.0 <= pts <= 749.9:  return "B"
        elif 750.0 <= pts <= 899.9:  return "B+"
        else:                        return "A"

    if all_data is None:
        all_data = {}

    dados_ano_anterior = all_data.get(ano_ant, {})
    nota_anterior = 0.0
    if ano_ant in all_data:
        nota_anterior = float(sum(
            float(info_ant.get("pontos", 0)) 
            for qid_ant, info_ant in dados_ano_anterior.items() 
            if isinstance(info_ant, dict) and not qid_ant.startswith("COM_")
        ))

    faixa_anterior = converter_pontos_em_faixa_ifiscal(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_ifiscal(nota_atual)

    variacao_pontos = nota_atual - nota_anterior
    if nota_anterior > 0:
        variacao_percentual = (variacao_pontos / nota_anterior) * 100
        texto_percentual = f"{variacao_percentual:+.2f}%"
    else:
        texto_percentual = "0.00%"

    if variacao_pontos > 0:
        cor_variacao = colors.HexColor("#28a745")
        seta_tendencia = "▲"
    elif variacao_pontos < 0:
        cor_variacao = colors.HexColor("#dc3545")
        seta_tendencia = "▼"
    else:
        cor_variacao = colors.HexColor("#6c757d")
        seta_tendencia = "■"

    style_th = ParagraphStyle('Th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAno', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_td_pts = ParagraphStyle('TdPts', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, textColor=colors.HexColor("#1b4f72"), alignment=1)
    style_td_var = ParagraphStyle('TdVar', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, textColor=cor_variacao, alignment=1)

    dados_comparativos = [
        [Paragraph("Exercício", style_th), Paragraph("Pontuação Obtida", style_th), Paragraph("Faixa / Conceito", style_th), Paragraph("Variação Nominal", style_th), Paragraph("Variação Percentual", style_th)],
        [Paragraph(str(ano_ant), style_td_ano), Paragraph(f"{nota_anterior:.1f} pts", style_td_pts), Paragraph(str(faixa_anterior), style_td_faixa), Paragraph("-", style_td_var), Paragraph("-", style_td_var)],
        [Paragraph(str(ano_atual), style_td_ano), Paragraph(f"{nota_atual:.1f} pts", style_td_pts), Paragraph(str(faixa_real_atual), style_td_faixa), Paragraph(f"{seta_tendencia} {variacao_pontos:+.1f} pts", style_td_var), Paragraph(f"{seta_tendencia} {texto_percentual}", style_td_var)]
    ]

    tabela_comp = Table(dados_comparativos, colWidths=[80, 105, 95, 105, 105])
    tabela_comp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")), 
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8f9fa")), ("BACKGROUND", (0, 2), (-1, 2), colors.whitesmoke),                    
    ]))
    elements.append(tabela_comp)
    elements.append(Spacer(1, 12))

    style_analise = ParagraphStyle('Analise', parent=styles['Normal'], fontSize=10, leading=14)
    if variacao_pontos > 0:
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global do i-Fiscal comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores do i-Fiscal em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade do i-Fiscal."

    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # --- TÓPICO 2 ---
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []

    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): continue
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")
        pts_maximo = float(PONTUACOES_MAX.get(qid, 0)) if 'PONTUACOES_MAX' in globals() else 10.0
        
        if pts_maximo > 0:
            eficiencia = (pts_obtidos / pts_maximo) * 100
            item_data = {"qid": qid, "pts_obtidos": pts_obtidos, "pts_maximo": pts_maximo, "eficiencia": eficiencia, "valor": valor_resposta, "link": link_evidencia}
            
            # 🛠️ CORREÇÃO DE CORTE: Acima ou igual a 70% vira Ponto Forte. Menor que 70% vira Ponto Fraco.
            if eficiencia >= 70.0: 
                lista_pontos_fortes.append(item_data)
            else: 
                lista_pontos_fracos.append(item_data)

    if lista_pontos_fortes:
        # Título atualizado para refletir a faixa correta
        elements.append(Paragraph("<b>✅ Pontos Fortes (Eficiência de 70% a 100%):</b>", styles["h3"]))
        data_fortes = [["Quesito", "Nota / Teto", "Eficiência", "Resposta / Evidência"]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["pts_obtidos"], reverse=True):
            evidencia = f"<b>{item['valor']}</b><br/>{item['link']}"
            data_fortes.append([item['qid'], f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", f"{item['eficiencia']:.1f}%", Paragraph(evidencia, styles["Normal"])])
        tabela_fortes = Table(data_fortes, colWidths=[65, 75, 65, 285])
        tabela_fortes.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#28a745")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (2, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#28a745")), ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))

    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Pontos Fracos Geral (Eficiência abaixo de 70%):</b>", styles["h3"]))
        data_fracos = [["Quesito", "Nota / Teto", "Eficiência", "Resposta / Evidência"]]
        for item in sorted(lista_pontos_fracos, key=lambda x: x["eficiencia"]): # Ordena da pior eficiência para a melhor
            evidencia = f"<b>{item['valor']}</b><br/>{item['link']}"
            data_fracos.append([item['qid'], f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", f"{item['eficiencia']:.1f}%", Paragraph(evidencia, styles["Normal"])])
        tabela_fracos = Table(data_fracos, colWidths=[65, 75, 65, 285])
        tabela_fracos.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (2, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e67e22")), ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(tabela_fracos)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    # Dicionário mapeado com os 20 quesitos e suas respectivas penalidades máximas
    PENALIDADES_MAX = {
        "7.2": -3.0,
        "8.3": -15.0,
        "9.6": -30.0,
        "10.3": -5.0,
        "12.1": -10.0,
        "12.2": -5.0,
        "12.3": -5.0,
        "12.3.1": -5.0,
        "12.5.2": -10.0,
        "16": -10.0,
        "16.3": -5.0,
        "17.0": -5.0,
        "23.0": -30.0,
        "24.1": -30.0,
        "25.1": -25.0,
        "F6": -20.0,
        "F7": -10.0,
        "F9": -10.0,
        "F21": -50.0,
        "F22": -5.0
    }

    lista_penalidades = []
    
    for qid, pen_max in PENALIDADES_MAX.items():
        info = dados.get(qid, {}) if isinstance(dados.get(qid), dict) else {"pontos": 0.0, "valor": "Não Respondido", "link": ""}
        
        try:
            nota_real = float(info.get("pontos", 0.0))
        except (ValueError, TypeError):
            nota_real = 0.0
        
        # Lógica de Eficiência Preventiva e Status de Risco baseado na nota negativa (penalidade)
        if nota_real < 0:
            if nota_real <= pen_max:
                eficiencia_preventiva = 0.0
                status_html = "<font color='#dc3545'><b>Impacto Máximo Aplicado</b></font>"
            else:
                # Caso haja uma penalidade parcial aplicada
                eficiencia_preventiva = ((pen_max - nota_real) / pen_max) * 100
                status_html = f"<font color='#e67e22'><b>Impacto Parcial ({nota_real:.1f} pts)</b></font>"
        else:
            eficiencia_preventiva = 100.0
            status_html = "<font color='#28a745'><b>Risco Mitigado (Sem Penalidade)</b></font>"

        lista_penalidades.append({
            "qid": qid,
            "nota_real": nota_real,
            "pen_max": pen_max,
            "eficiencia": eficiencia_preventiva,
            "status": status_html
        })

    data_penalidades = [["Quesito", "Nota Obtida", "Penalidade Máxima", "Eficiência Preventiva", "Status de Risco"]]
    
    # Ordena exibindo primeiro os quesitos onde a penalidade causou maior impacto (menor eficiência)
    for item in sorted(lista_penalidades, key=lambda x: x["eficiencia"]):
        nota_txt = f"{item['nota_real']:.1f} pts"
        teto_txt = f"{item['pen_max']:.1f} pts"
        ef_txt = f"{item['eficiencia']:.1f}%"
        
        data_penalidades.append([
            item['qid'], 
            nota_txt, 
            teto_txt, 
            ef_txt, 
            Paragraph(item['status'], styles["Normal"]) 
        ])
        
    tabela_pen = Table(data_penalidades, colWidths=[65, 95, 115, 115, 150])
    tabela_pen.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4f72")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#1b4f72")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(tabela_pen)
    elements.append(Spacer(1, 15))

   # =========================================================================
    # 3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)
    # =========================================================================
    elements.append(Paragraph('<b>3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)</b>', styles['h2']))
    elements.append(Spacer(1, 6))

    PENALIDADES_MAX = {
        '7.2': -3.0,
        '8.3': -15.0,
        '9.6': -30.0,
        '10.3': -5.0,
        '12.1': -10.0,
        '12.2': -5.0,
        '12.3': -5.0,
        '12.3.1': -5.0,
        '12.5.2': -10.0,
        '16': -10.0,
        '16.3': -5.0,
        '17.0': -5.0,
        '23.0': -30.0,
        '24.1': -30.0,
        '25.1': -25.0,
        'F6': -20.0,
        'F7': -10.0,
        'F9': -10.0,
        'F21': -50.0,
        'F22': -5.0,
    }

    dados_penalidades = dados.copy() if isinstance(dados, dict) else {}
    reincidencias_detectadas = []

    # 🛠️ CORREÇÃO: Se não existir no dicionário, assume 0.0 pontos (não houve penalidade)
    for qid_pen, val_max in PENALIDADES_MAX.items():
        if qid_pen not in dados_penalidades:
            dados_penalidades[qid_pen] = {
                'pontos': 0.0,
                'valor': 'Não aplicável / Ocultado por condicional',
                'link': '',
            }

    lista_penalidades = []

    for qid, pen_max in PENALIDADES_MAX.items():
        if qid in dados_penalidades:
            info = dados_penalidades[qid]
            nota_real = float(info.get('pontos', 0.0))

            # Garante que apenas valores negativos (penalidades reais) entrem no cálculo do risco
            nota_risco = nota_real if nota_real <= 0.0 else 0.0

            if pen_max != 0:
                eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            else:
                eficiencia_preventiva = 100.0

            eficiencia_preventiva = max(0.0, min(eficiencia_preventiva, 100.0))

            lista_penalidades.append({
                'qid': qid,
                'nota_real': nota_real,
                'pen_max': pen_max,
                'eficiencia': eficiencia_preventiva,
                'valor': info.get('valor', ''),
                'link': info.get('link', ''),
            })

            if eficiencia_preventiva < 100.0 and isinstance(dados_ano_anterior, dict) and qid in dados_ano_anterior:
                info_ant = dados_ano_anterior[qid]
                nota_real_ant = float(info_ant.get('pontos', 0.0)) if isinstance(info_ant, dict) else 0.0
                if nota_real == nota_real_ant:
                    reincidencias_detectadas.append({
                        'qid': qid,
                        'tipo': 'Penalidade Aplicada',
                        'detalhe': f'Impacto Recorrente de Penalidade de {nota_real:.1f} pts',
                        'ant': f'{nota_real_ant:.1f} pts',
                        'atual': f'{nota_real:.1f} pts',
                    })

    if lista_penalidades:
        data_penalidades = [[
            Paragraph('Quesito', style_th),
            Paragraph('Penalidade Aplicada', style_th),
            Paragraph('Pior Cenário', style_th),
            Paragraph('Eficiência Preventiva', style_th),
            Paragraph('Status de Risco', style_th),
        ]]

        def ordenar_quesitos(x):
            limpo = ''.join(c for c in x['qid'] if c.isdigit() or c == '.')
            partes = [int(i) for i in limpo.split('.') if i.isdigit()]
            return partes if partes else [999]

        for item in sorted(lista_penalidades, key=ordenar_quesitos):
            # Formatação para não exibir "-0.0 pts" caso o valor venha flutuante negativo zerado
            valor_nota = 0.0 if abs(item['nota_real']) < 0.01 else item['nota_real']

            nota_txt = f'{valor_nota:.1f} pts'
            teto_txt = f"{item['pen_max']:.1f} pts"
            ef_txt = f"{item['eficiencia']:.1f}%"

            if item['eficiencia'] >= 100.0:
                status = "<font color='#2e7d32'><b>Risco Mitigado</b></font>"
            elif item['eficiencia'] <= 0.0:
                status = "<font color='#c0392b'><b>Impacto Máximo</b></font>"
            else:
                status = "<font color='#d35400'><b>Impacto Parcial</b></font>"

            data_penalidades.append([
                Paragraph(item['qid'], style_tabela_centro),
                Paragraph(nota_txt, style_tabela_centro),
                Paragraph(teto_txt, style_tabela_centro),
                Paragraph(ef_txt, style_tabela_centro),
                Paragraph(status, style_tabela_padrao),
            ])

        tabela_pen = Table(data_penalidades, colWidths=[70, 110, 80, 115, 125])
        tabela_pen.setStyle(
            TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1b4f72')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#1b4f72')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ])
        )
        elements.append(tabela_pen)
        elements.append(Spacer(1, 15))

    # =========================================================================
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS
    # =========================================================================
    elements.append(Paragraph('<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS </b>', styles['h2']))
    elements.append(Spacer(1, 6))

    TETOS_VALIDOS = {
        '1.1.2': 20,
        '1.1.3': 5,
        '1.2': 20,
        '2.0': 10,
        '2.1': 50,
        '3.0': 10,
        '3.1': 20,
        '4.0': 20,
        '5.2.1': 20,
        '6.0': 20,
        '6.1': 50,
        '6.2': 25,
        '7.2': 2,
        '7.3': 10,
        '7.3.1': 20,
        '7.4': 10,
        '7.4.1': 20,
        '7.5': 30,
        '7.7': 30,
        '7.8': 20,
        '7.8.1': 50,
        '7.9': 3,
        '8.2': 2,
        '8.3': 10,
        '8.4': 20,
        '8.4.1': 10,
        '8.4.2': 30,
        '8.4.3': 50,
        '9.2': 100,
        '9.3': 5,
        '9.3.1': 5,
        '11.2': 2,
        '11.3': 30,
        '11.3.2': 20,
        '11.3.3': 40,
        '11.5': 10,
        '12.1': 54,
        '14.3': 30,
        '15': 2,
        '15.1': 3,
        'A4.1.1': 90,
        'A4.1.2': 20,
        'A4.1.3': 22,
        'A6': 5,
    }

    dados_analise_reinc = dados.copy() if isinstance(dados, dict) else {}

    if subquestoes_11:
        for sub_id in subquestoes_11:
            if resposta_11_nao or (sub_id not in dados_analise_reinc):
                dados_analise_reinc[sub_id] = {'pontos': 0.0, 'valor': 'Não', 'link': ''}

    for qid, info_atual in dados_analise_reinc.items():
        if qid.startswith('COM_') or not isinstance(info_atual, dict):
            continue

        qid_str = str(qid).strip()

        if qid_str.startswith('A4.1.1_'):
            chave_mae = 'A4.1.1'
        elif qid_str.startswith('A4.1.2_'):
            chave_mae = 'A4.1.2'
        elif qid_str.startswith('A4.1.3_'):
            chave_mae = 'A4.1.3'
        else:
            chave_mae = qid_str

        if chave_mae not in TETOS_VALIDOS:
            continue

        pts_maximo = float(TETOS_VALIDOS[chave_mae])
        pts_obtidos_atual = float(info_atual.get('pontos', 0.0))

        if pts_maximo > 0 and (pts_obtidos_atual / pts_maximo) * 100 < 50.0:
            info_ant = dados_ano_anterior.get(qid, {}) if isinstance(dados_ano_anterior, dict) else {}
            pts_obtidos_ant = float(info_ant.get('pontos', 0.0)) if isinstance(info_ant, dict) else 0.0

            if (pts_obtidos_ant / pts_maximo) * 100 < 50.0:
                origem = 'Gestão Ambiental Geral'
                if 'CATEGORIAS_MAP' in globals():
                    for cat_chave, cat_info in CATEGORIAS_MAP.items():
                        if chave_mae in cat_info.get('qids', []):
                            origem = cat_info.get('label', 'Outros')
                            break
                else:
                    if (
                        chave_mae.startswith('1.')
                        or chave_mae.startswith('2.')
                        or chave_mae.startswith('3.')
                    ):
                        origem = 'Planejamento e Infraestrutura'
                    elif chave_mae.startswith('7.') or chave_mae.startswith('8.'):
                        origem = 'Resíduos e Saneamento'
                    elif chave_mae.startswith('11.') or chave_mae.startswith('12.'):
                        origem = 'Biodiversidade e Água'
                    elif chave_mae.startswith('A4'):
                        origem = 'Indicadores SINISA'

                reincidencias_detectadas.append({
                    'qid': qid_str,
                    'tipo': origem,
                    'detalhe': 'Ineficiência Crônica de Desempenho (Eficiência inferior a 50% por 2 anos)',
                    'ant': f'{pts_obtidos_ant:.1f} / {pts_maximo:.1f} pts',
                    'atual': f'{pts_obtidos_atual:.1f} / {pts_maximo:.1f} pts',
                })

    if reincidencias_detectadas:
        data_reinc = [[
            Paragraph('Quesito', style_th),
            Paragraph('Origem da Falha', style_th),
            Paragraph('Impacto Histórico', style_th),
            Paragraph('Exercício Anterior', style_th),
            Paragraph('Exercício Atual', style_th),
        ]]

        def ordenacao_segura(x):
            limpo = ''.join(c for c in x['qid'].split('_')[0] if c.isdigit() or c == '.')
            partes = [int(i) for i in limpo.split('.') if i.isdigit()]
            return partes if partes else [999]

        for reinc in sorted(reincidencias_detectadas, key=ordenacao_segura):
            data_reinc.append([
                Paragraph(reinc['qid'], style_tabela_centro),
                Paragraph(reinc['tipo'], style_tabela_centro),
                Paragraph(f"<b>{reinc['detalhe']}</b>", style_tabela_padrao),
                Paragraph(reinc['ant'], style_tabela_centro),
                Paragraph(reinc['atual'], style_tabela_centro),
            ])

        tabela_reinc = Table(data_reinc, colWidths=[65, 115, 170, 75, 65])
        tabela_reinc.setStyle(
            TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0392b')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c0392b')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ])
        )
        elements.append(tabela_reinc)
    else:
        elements.append(
            Paragraph(
                "<font color='#2e7d32'><b>✅ Nenhuma reincidência ativa detectada. O município corrigiu ou mitigou as falhas do ano anterior.</b></font>",
                styles['Normal'],
            )
        )

    elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)
    # -------------------------------------------------------------------------
    elements.append(Paragraph('<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>', styles['h2']))
    elements.append(Spacer(1, 6))

    def calcular_percentual_checklist(resposta_bruta, total_itens, ignorar_filtros=False):
        if not resposta_bruta:
            return 0.0

        if str(resposta_bruta).startswith('['):
            try:
                itens_lista = ast.literal_eval(str(resposta_bruta))
                if isinstance(itens_lista, list):
                    if ignorar_filtros:
                        itens_validos = [str(i).strip() for i in itens_lista if i]
                    else:
                        itens_validos = [
                            str(i).strip().lower()
                            for i in itens_lista
                            if i and 'outros' not in str(i).lower() and 'não' not in str(i).lower()
                        ]
                    return min((len(itens_validos) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0
            except Exception:
                pass

        itens = [i.strip() for i in str(resposta_bruta).split(',') if i.strip()]
        if not ignorar_filtros:
            itens = [i for i in itens if 'outros' not in i.lower() and 'não' not in i.lower()]
        return min((len(itens) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0

    REGRAS_ODS = {
        '1.0': {'metas': '17.1', 'total_chk': 0},
        '1.1': {'metas': '17.1', 'total_chk': 0},
        '1.3': {'metas': '17.1', 'total_chk': 0},
        '1.4': {'metas': '16.5, 17.1', 'total_chk': 0},
        '1.5': {'metas': '16.5', 'total_chk': 0},
        '1.5.1': {'metas': '16.5', 'total_chk': 0},
        '2.0': {'metas': '16.5', 'total_chk': 0},
        '3.0': {'metas': '17.1', 'total_chk': 0},
        '3.1': {'metas': '17.1', 'total_chk': 8},
        '4.0': {'metas': '17.1', 'total_chk': 0},
        '5.0': {'metas': '17.1', 'total_chk': 0},
        '7.0': {'metas': '17.1', 'total_chk': 0},
        '7.3': {'metas': '10.4, 17.1', 'total_chk': 5},
        '8.0': {'metas': '17.1', 'total_chk': 0},
        '8.1': {'metas': '17.1', 'total_chk': 0},
        '8.2': {'metas': '17.1', 'total_chk': 0},
        '8.3': {'metas': '16.6, 16.10', 'total_chk': 0},
        '9.0': {'metas': '17.1', 'total_chk': 0},
        '9.3': {'metas': '17.1', 'total_chk': 0},
        '9.4': {'metas': '17.1', 'total_chk': 0},
        '9.5': {'metas': '17.1', 'total_chk': 3},  # Múltipla escolha (3 opções)
        '9.6': {'metas': '10.4, 17.1', 'total_chk': 0},
        '10.0': {'metas': '17.1', 'total_chk': 0},
        '10.3': {'metas': '17.1', 'total_chk': 0},
        '11.0': {'metas': '17.1', 'total_chk': 0},
        '12.0': {'metas': '10.4, 16.6, 17.1', 'total_chk': 0},
        '13.0': {'metas': '16.6, 16.7, 17.1', 'total_chk': 0},
        '16': {'metas': '16.6, 17.1', 'total_chk': 0},
        '17.0': {'metas': '17.1', 'total_chk': 0},
        '18.0': {'metas': '16.6, 16.10', 'total_chk': 0},
        '21.0': {'metas': '16.5, 16.6', 'total_chk': 0},
        '22.0': {'metas': '16.5, 16.6', 'total_chk': 0},
        '23.0': {'metas': '17.1', 'total_chk': 0},
        '25.0': {'metas': '17.1', 'total_chk': 0},
    }

    analise_ods = []
    dados_reference = dados if isinstance(dados, dict) else {}

    for qid, config in REGRAS_ODS.items():
        info = dados_reference.get(qid, {}) if isinstance(dados_reference, dict) else {'valor': 'Não Respondido'}
        if not isinstance(info, dict):
            info = {'valor': str(info)}

        resp = str(info.get('valor', '')).strip()
        resp_l = resp.lower()

        if not resp or resp_l == 'não respondido' or resp == '[]':
            continue

        if config['total_chk'] > 0 or qid == '9.5':
            total_opcoes = 3 if qid == '9.5' else config['total_chk']
            is_95 = qid == '9.5'
            pct = calcular_percentual_checklist(resp, total_opcoes, ignorar_filtros=is_95)
            status = f'{pct:.1f}% Atendido'
        else:
            if qid in ['9.6', '12.0']:
                status = 'Atendido' if 'não' in resp_l else 'Não Atendido'
            elif qid == '8.2':
                status = (
                    'Atendido' if ('sistema automatizado' in resp_l or 'manualmente' in resp_l) else 'Não Atendido'
                )
            elif qid == '8.3':
                status = (
                    'Atendido'
                    if ('sim, sem restrição' in resp_l or 'sem restrição - 00' in resp_l)
                    else 'Não Atendido'
                )
            elif qid == '9.3':
                opcoes_validas = [
                    'site da prefeitura',
                    'órgão fazendário',
                    'orgao fazendario',
                    'cartório autorizado',
                    'cartorio autorizado',
                    'outros',
                ]
                status = 'Atendido' if any(opc in resp_l for opc in opcoes_validas) else 'Não Atendido'
            elif qid == '17.0':
                status = 'Atendido' if 'todas as ações' in resp_l else 'Não Atendido'
            elif qid == '23.0':
                status = 'Atendido' if 'dentro do prazo' in resp_l else 'Não Atendido'
            else:
                status = (
                    'Atendido'
                    if ('sim' in resp_l or 'parcialmente' in resp_l or 'integralmente' in resp_l)
                    else 'Não Atendido'
                )

        exibicao_resp = resp
        if exibicao_resp.startswith('['):
            exibicao_resp = exibicao_resp.replace('[', '').replace(']', '').replace("'", '').replace('"', '')

        analise_ods.append({
            'qid': qid,
            'status': status,
            'metas': config['metas'],
            'resp': exibicao_resp[:45] + '...' if len(exibicao_resp) > 45 else exibicao_resp,
        })

    if analise_ods:
        data_ods = [['Quesito', 'Resposta Informada', 'Vínculo Metas ODS', 'Status de Cumprimento']]
        style_td_ods = ParagraphStyle(
            'TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1
        )

        def chave_ordenacao_ods(item):
            partes = []
            for p in item['qid'].split('.'):
                if p.isdigit():
                    partes.append(int(p))
                else:
                    partes.append(sum(ord(char) for char in p))
            return partes

        for item in sorted(analise_ods, key=chave_ordenacao_ods):
            st_txt = item['status']

            if 'Não Atendido' in st_txt:
                st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif 'Atendido' in st_txt and '%' not in st_txt:
                st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else:
                st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)

            data_ods.append(
                [item['qid'], Paragraph(item['resp'], styles['Normal']), item['metas'], st_p]
            )

        tabela_ods = Table(data_ods, colWidths=[60, 200, 115, 110])
        tabela_ods.setStyle(
            TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor('#0f9d58')),
                ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.whitesmoke),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (2, 0), (3, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, rl_colors.HexColor('#0f9d58')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ])
        )
        elements.append(tabela_ods)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 📊 6. SÉRIE HISTÓRICA DO IAMB (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 10))
    elements.append(Paragraph('<b>6. SÉRIE HISTÓRICA DO IAMB (CONSOLIDADO FINAL)</b>', styles['h2']))
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []

    ano_reference = ano_sel if ano_sel else 2026
    nota_reference = float(total_pts) if total_pts else 0.0

    # Montagem do array de dados para o Gráfico
    for a in anos_serie:
        if a == 0 or a == '0':
            valores_serie.append(0.0)
        elif a == ano_reference:
            valores_serie.append(
                min(nota_reference, 100.0) if nota_reference <= 100.0 else min(nota_reference, 1000.0)
            )
        elif all_data and a in all_data:
            dados_ano = all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(
                    sum(
                        info_h.get('pontos', 0.0)
                        for qid_h, info_h in dados_ano.items()
                        if isinstance(info_h, dict) and not qid_h.startswith('COM_')
                    )
                )
                valores_serie.append(pontos_ano)
            else:
                valores_serie.append(float(dados_ano))
        elif st and hasattr(st, 'session_state') and 'all_data' in st.session_state and a in st.session_state.all_data:
            dados_ano = st.session_state.all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(
                    sum(
                        info_h.get('pontos', 0.0)
                        for qid_h, info_h in dados_ano.items()
                        if isinstance(info_h, dict) and not qid_h.startswith('COM_')
                    )
                )
                valores_serie.append(pontos_ano)
            else:
                valores_serie.append(float(dados_ano))
        else:
            valores_serie.append(0.0)

    max_escala = 1000 if any(v > 100 for v in valores_serie) else 100
    passo_escala = 200 if max_escala == 1000 else 20

    desenho_grafico = Drawing(480, 165)
    bc = VerticalBarChart()
    bc.x = 45
    bc.y = 25
    bc.height = 110
    bc.width = 410
    bc.data = [valores_serie]
    bc.categoryAxis.categoryNames = [str(a) for a in anos_serie]
    bc.categoryAxis.labels.fontSize = 9
    bc.categoryAxis.labels.fontName = 'Helvetica-Bold'
    bc.categoryAxis.labels.dy = -10

    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max_escala
    bc.valueAxis.valueStep = passo_escala
    bc.valueAxis.labels.fontSize = 8

    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'

    bc.bars[0].fillColor = rl_colors.HexColor('#1b4f72')
    bc.bars[0].strokeColor = rl_colors.HexColor('#2c3e50')
    bc.bars[0].strokeWidth = 0.5

    desenho_grafico.add(
        String(
            240,
            150,
            'Série Histórica de Evolução do iAMB',
            textAnchor='middle',
            fontName='Helvetica-Bold',
            fontSize=12,
            fillColor=rl_colors.HexColor('#2c3e50'),
        )
    )
    desenho_grafico.add(bc)

    elements.append(desenho_grafico)
    elements.append(Spacer(1, 15))

    # =========================================================================
    # GERAÇÃO E RETORNO SEGURO DO BUFFER
    # =========================================================================
    doc.build(elements)
    buffer.seek(0)
    return buffer

import logging
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 1. FUNÇÕES DE BANCO E LIMPEZA - iFiscal
# =============================================================================


def zerar_questionario_ifiscal(ano: int):
    """Deleta todas as respostas do ano selecionado na tabela de respostas."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Tenta deletar da tabela específica do iFiscal
                try:
                    cursor.execute(
                        "DELETE FROM respostas_ifiscal WHERE ano = %s;",
                        (int(ano),),
                    )
                except Exception:
                    # Fallback caso seu banco utilize a tabela unificada 'respostas'
                    conn.rollback()
                    cursor.execute(
                        "DELETE FROM respostas WHERE ano = %s AND (modulo = 'ifiscal' OR modulo IS NULL);",
                        (int(ano),),
                    )
            conn.commit()

        # Limpa o cache de leitura do Streamlit para forçar nova consulta ao banco
        st.cache_data.clear()
    except Exception as e:
        logging.error(f"Erro ao zerar questionário iFiscal: {e}")
        st.error(f"Erro ao zerar questionário iFiscal no banco Neon: {e}")


@st.dialog("⚠️ Zerar Respostas do iFiscal")
def confirmar_zerar_dialog_ifiscal(ano):
    st.warning(
        f"Tem certeza que deseja apagar TODAS as respostas do iFiscal para o ano {ano}?"
    )
    st.write(
        "Esta ação é irreversível e excluirá os dados salvos no banco Neon."
    )

    # Campo para inserção da senha de confirmação
    senha_digitada = st.text_input(
        "Digite a senha de confirmação para prosseguir:",
        type="password",
        placeholder="Digite a senha...",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "🔴 Sim, Zerar Tudo", type="primary", use_container_width=True
        ):
            if senha_digitada.strip() == "fidelios":
                try:
                    # 1. Deleta do PostgreSQL (Neon)
                    zerar_questionario_ifiscal(ano)

                    # 2. Reseta a chave primária de respostas no session_state
                    key_ano = f"respostas_ifiscal_{ano}"
                    st.session_state[key_ano] = {}

                    # 3. Limpa todas as chaves dinâmicas dos formulários/inputs do iFiscal no session_state
                    chaves_para_limpar = [
                        k
                        for k in list(st.session_state.keys())
                        if f"ifiscal_{ano}" in k
                        or k.endswith(f"_{ano}")
                        or "ifiscal" in k.lower()
                    ]

                    for key in chaves_para_limpar:
                        # Preserva apenas a chave que guarda a seleção do ano na sidebar
                        if key != "ano_referencia_ifiscal":
                            del st.session_state[key]

                    st.toast(
                        f"Respostas do iFiscal ({ano}) zeradas com sucesso!",
                        icon="🗑️",
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao zerar iFiscal: {e}")
            else:
                st.error("🔒 Senha incorreta! Ação cancelada.")

    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


# =============================================================================
# 2. DIÁLOGO E BANCO - ZERAR DADOS DO iFISCAL
# =============================================================================


def zerar_banco_ifiscal_por_ano(ano: int):
    """Apaga fisicamente as respostas do i-Fiscal para o ano selecionado no Neon DB."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Garante exclusão/zeramento estritamente na tabela do iFiscal
                cursor.execute(
                    "DELETE FROM respostas_ifiscal WHERE ano = %s;", (int(ano),)
                )
            conn.commit()

        # Limpa caches em memória
        st.cache_data.clear()

        # Limpa chaves do session_state associadas ao ano
        chave_ss = f"respostas_ifiscal_{ano}"
        if chave_ss in st.session_state:
            del st.session_state[chave_ss]

        return True
    except Exception as e:
        logging.error(f"Erro ao zerar i-Fiscal no banco: {e}")
        return False


@st.dialog("⚠️ Confirmar Zeramento - i-Fiscal")
def confirmar_zerar_dialog_ifiscal(ano):
    st.warning(
        f"Tem certeza que deseja apagar **TODAS** as respostas e pontos do i-Fiscal para o ano de **{ano}**?"
    )
    st.write(
        "Esta ação é irreversível e removerá as evidências e comentários do banco de dados."
    )

    col_sim, col_nao = st.columns(2)
    with col_sim:
        if st.button(
            "🔥 Sim, Zerar Dados", type="primary", use_container_width=True
        ):
            if zerar_banco_ifiscal_por_ano(ano):
                st.toast(
                    f"Dados do i-Fiscal para {ano} foram zerados com sucesso!",
                    icon="🗑️",
                )
                st.rerun()
            else:
                st.error("Erro ao tentar zerar os dados no banco.")

    with col_nao:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


# =============================================================================
# 2. SIDEBAR E PAINEL - iFiscal (CORRIGIDO)
# =============================================================================


def render_sidebar():
    st.sidebar.title("🏛️ Painel de Controle - i-Fiscal")
    anos = [2024, 2025, 2026, 2027, 2028, 2029, 2030]

    ano_sel = st.sidebar.selectbox(
        "Ano de Referência:", anos, key="ano_referencia_ifiscal"
    )

    # Força a busca da função específica do iFiscal sem recuar para tabelas genéricas
    if "load_respostas_ifiscal" in globals():
        res_data = load_respostas_ifiscal(ano_sel)
    else:
        res_data = load_respostas(ano_sel)

    # Garante conversão float para não travar o cálculo de pontuação
    total_pts = sum(
        float(item.get("pontos", 0.0))
        for item in res_data.values()
        if isinstance(item, dict)
    )

    # Régua de Classificação IEGM / i-Fiscal
    if total_pts <= 500:
        faixa, cor = "C", "red"
    elif total_pts <= 599:
        faixa, cor = "C+", "orange"
    elif total_pts <= 749:
        faixa, cor = "B", "#d4d400"
    elif total_pts <= 899:
        faixa, cor = "B+", "lightgreen"
    else:
        faixa, cor = "A", "green"

    st.sidebar.metric("Pontuação Total i-Fiscal", f"{total_pts:.1f} pts")
    st.sidebar.markdown(
        f"**Faixa:** <span style='color:{cor}; font-size:18px; font-weight:bold;'>{faixa}</span>",
        unsafe_allow_html=True,
    )

    st.sidebar.divider()

    col1, col2 = st.sidebar.columns(2)

    # Botão de Download do PDF
    with col1:
        pdf_bytes = b""
        if "gerar_relatorio_ifiscal" in globals():
            pdf_bytes = gerar_relatorio_ifiscal(
                res_data, ano_sel=ano_sel, total_pts=total_pts
            ).getvalue()
        elif "gerar_relatorio_pdf" in globals():
            pdf_bytes = gerar_relatorio_pdf(
                res_data, ano_sel, total_pts, faixa
            )

        st.download_button(
            label="📄 Baixar PDF",
            data=pdf_bytes,
            file_name=f"Relatorio_iFiscal_{ano_sel}.pdf",
            mime="application/pdf",
            use_container_width=True,
            disabled=(pdf_bytes == b""),
        )

    # Botão para abrir o Modal de confirmação
    with col2:
        if st.button(
            "🔄 Zerar",
            help="Limpar todas as respostas do ano selecionado",
            use_container_width=True,
        ):
            confirmar_zerar_dialog_ifiscal(ano_sel)

    return total_pts, res_data, ano_sel


# =============================================================================
# 3. GRÁFICOS E HISTÓRICO - iFiscal (CORRIGIDO)
# =============================================================================


def get_all_years_data_ifiscal() -> dict:
    """Busca o histórico de dados EXCLUSIVAMENTE do i-Fiscal."""
    all_data = {}

    # 1. Carrega estritamente da tabela respostas_ifiscal no Neon
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # NENHUM fallback para 'respostas' aqui! Apenas 'respostas_ifiscal'
                cursor.execute(
                    "SELECT DISTINCT ano FROM respostas_ifiscal ORDER BY ano"
                )
                anos_banco = [row[0] for row in cursor.fetchall()]

                for a in anos_banco:
                    all_data[a] = (
                        load_respostas_ifiscal(a)
                        if "load_respostas_ifiscal" in globals()
                        else load_respostas(a)
                    )
    except Exception as e:
        logging.error(f"Erro ao buscar histórico de anos i-Fiscal no banco: {e}")

    # 2. Carrega dados temporários do Session State do i-Fiscal
    prefixo = "respostas_ifiscal_"
    for key in list(st.session_state.keys()):
        if key.startswith(prefixo):
            try:
                ano = int(key.replace(prefixo, ""))
                if ano not in all_data or not all_data[ano]:
                    all_data[ano] = st.session_state[key]
            except ValueError:
                continue

    return all_data


def grafico_pontos_por_ano(all_data):
    """Gráfico de barras vertical com pontos totais por ano para o i-Fiscal."""
    anos = sorted(all_data.keys())
    totais = []
    cores = []

    for ano in anos:
        res = all_data[ano]
        total = sum(
            float(v.get("pontos", 0.0))
            for k, v in res.items()
            if isinstance(v, dict) and not str(k).startswith("COM_")
        )
        totais.append(total)

        if total <= 500:
            cores.append("#ef4444")
        elif total <= 599:
            cores.append("#f97316")
        elif total <= 749:
            cores.append("#eab308")
        elif total <= 899:
            cores.append("#84cc16")
        else:
            cores.append("#16a34a")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[str(a) for a in anos],
            y=totais,
            marker_color=cores,
            text=[f"{t:.1f} pts" for t in totais],
            textposition="outside",
            hovertemplate="<b>Ano: %{x}</b><br>i-Fiscal Total: %{y:.1f} pts<extra></extra>",
        )
    )

    fig.update_layout(
        title="Índice Histórico i-Fiscal (Gestão Fiscal) por Exercício",
        xaxis_title="Ano",
        yaxis_title="Pontuação i-Fiscal",
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        height=400,
    )

    return fig


def render_graficos(res_data_atual, ano_sel):
    st.header("📊 Painel de Análise do i-Fiscal")

    all_data = get_all_years_data_ifiscal()

    if not all_data:
        st.info(
            "Nenhum dado do i-Fiscal registrado ainda. Preencha os itens para visualizar os gráficos."
        )
        return

    st.plotly_chart(grafico_pontos_por_ano(all_data), use_container_width=True)


# =============================================================================
# 4. FORMULÁRIO PRINCIPAL - iFiscal
# =============================================================================


def mostrar_formulario_ifiscal():
    total_pts, res_data, ano_sel = render_sidebar()

    st.title(f"🏛️ Gestão Fiscal e Financeira (i-Fiscal) - {ano_sel}")

    aba_quest, aba_ext, aba_graf = st.tabs(
        ["📋 Questionário i-Fiscal", "🌐 Dados Externos", "📊 Gráficos"]
    )

    with aba_quest:
        st.info("Preencha as informações fiscais e financeiras do município.")

        # =============================================================================
        # QUESITO 1.0 • ESTRUTURA ADMINISTRATIVA TRIBUTÁRIA (MODELO PADRONIZADO iGov)
        # =============================================================================
        with st.container(key=f"container_bloco_fiscal_1_0_{ano_sel}", border=True):
                with st.expander(
                        "📌 Quesito 1.0 - Estrutura Administrativa", expanded=True
                ):
                        st.subheader("1.0 • Administração Tributária")
                        st.write(
                                "**Há estrutura administrativa voltada para a administração tributária?**"
                        )
                        st.caption(
                                "ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.0' para registrar.*"
                        )

                        # Dicionário com Mapeamento de Opções e Pontuações do iFiscal
                        opcoes_10 = {
                                "Selecione...": 0.0,
                                "Sim (0.0 pts)": 0.0,
                                "Não (0.0 pts)": 0.0,
                        }

                        # Estado inicial / persistente
                        d10 = res_data.get("1.0") or {
                                "valor": "Selecione...",
                                "pontos": 0.0,
                                "link": "",
                                "comentarios": [],
                        }
                        v_salvo_10 = d10.get("valor", "Selecione...")

                        # Trata migração de legado caso no banco esteja salvo apenas "Sim" ou "Não"
                        if v_salvo_10 == "Sim":
                                v_salvo_10 = "Sim (0.0 pts)"
                        elif v_salvo_10 == "Não":
                                v_salvo_10 = "Não (0.0 pts)"

                        evidencia_10_salva = d10.get("link", "")

                        # Chaves fixas por componente e ano
                        chave_radio_10 = f"r_10_{ano_sel}_fiscal"
                        chave_link_10 = f"l_10_txt_{ano_sel}_fiscal"

                        c10_1, c10_2 = st.columns([1, 1])
                        with c10_1:
                                lista_opcoes_10 = list(opcoes_10.keys())
                                idx_10 = (
                                        lista_opcoes_10.index(v_salvo_10)
                                        if v_salvo_10 in lista_opcoes_10
                                        else 0
                                )

                                val_radio_10 = st.radio(
                                        "Selecione uma opção (1.0):",
                                        options=lista_opcoes_10,
                                        index=idx_10,
                                        key=chave_radio_10,
                                )

                        with c10_2:
                                link_10 = st.text_area(
                                        "Link / Evidência (1.0):",
                                        value=evidencia_10_salva,
                                        key=chave_link_10,
                                        placeholder="Insira o link oficial da lei de criação, organograma ou documento comprobatório...",
                                        height=100,
                                )
                                placeholder_links_10 = st.empty()
                                links_10_visuais = re.findall(REGEX_PURE_URL, link_10 or "")
                                if links_10_visuais:
                                        placeholder_links_10.markdown(
                                                "**🔗 Link ativo:** "
                                                + " | ".join(
                                                        [
                                                                f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                                                for u in links_10_visuais
                                                        ]
                                                )
                                        )

                        # -----------------------------------------------------------------
                        # BLOCO DE COMENTÁRIOS DO iFISCAL
                        # -----------------------------------------------------------------
                        bloco_comentarios_ifiscal("1.0", res_data, sufixo="fiscal")

                        # -----------------------------------------------------------------
                        # BOTÃO DE SALVAMENTO MANUAL
                        # -----------------------------------------------------------------
                        if st.button(
                                "💾 Salvar Quesito 1.0",
                                key=f"btn_salvar_1_0_{ano_sel}_fiscal",
                                type="primary",
                        ):
                                val_salvar = st.session_state.get(chave_radio_10, v_salvo_10)
                                pts_10 = float(opcoes_10.get(val_salvar, 0.0))
                                lnk_val = link_10.strip()

                                # Captura os comentários atualizados do dicionário/estado
                                comentario_para_salvar = d10.get("comentarios", [])

                                # SALVA NA TABELA ISOLADA DO IFISCAL (respostas_ifiscal)
                                save_resp_ifiscal(
                                        qid="1.0",
                                        valor=val_salvar,
                                        pontos=pts_10,
                                        link=lnk_val,
                                        comentarios=comentario_para_salvar,
                                )

                                # Atualiza o dicionário local res_data da sessão atual
                                res_data["1.0"] = {
                                        "valor": val_salvar,
                                        "pontos": pts_10,
                                        "link": lnk_val,
                                        "comentarios": comentario_para_salvar,
                                }

                                # Validação de novos links para acionar o modal
                                links_atuais = [
                                        u[0] if isinstance(u, tuple) else u
                                        for u in re.findall(REGEX_PURE_URL, lnk_val or "")
                                ]
                                links_antigos = [
                                        u[0] if isinstance(u, tuple) else u
                                        for u in re.findall(REGEX_PURE_URL, evidencia_10_salva or "")
                                ]

                                if (
                                        lnk_val != evidencia_10_salva
                                        and links_atuais
                                        and links_atuais != links_antigos
                                ):
                                        st.session_state[f"links_pendentes_1_0_{ano_sel}"] = (
                                                links_atuais
                                        )
                                        st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                                st.cache_data.clear()
                                st.toast(
                                        "Resposta e evidências do Quesito 1.0 salvos com sucesso no iFiscal!",
                                        icon="✅",
                                )
                                st.rerun()

                        # Resumo dinâmico e impacto de pontuação
                        pts_atuais_10 = d10.get("pontos", 0.0)
                        cor_txt_10 = "#28a745" if pts_atuais_10 > 0.0 else "#6c757d"

                        st.markdown(
                                f"<span style='color:{cor_txt_10}; font-weight:bold;'>"
                                f"📊 Impacto de Pontuação no Quesito 1.0: +{pts_atuais_10:.1f} pontos</span>",
                                unsafe_allow_html=True,
                        )

        # GATILHO DO MODAL 1.0 (Ainda dentro do questionário)
        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
                if "modal_aviso_link" in globals():
                        modal_aviso_link(
                                "1.0",
                                st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []),
                        )
                st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.1 • LEI DA ESTRUTURA ORGANIZACIONAL (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_1_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.1 - Lei da Estrutura Organizacional", expanded=True):
                st.subheader("1.1 • Estrutura Organizacional por Lei")
                st.write(
                    "**O Município possui lei que defina a estrutura organizacional da Administração Tributária?**"
                )
                st.caption("ℹ *Preencha os campos abaixo e clique no botão 'Salvar Quesito 1.1' para registrar.*")

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 1.1
                opcoes_11 = {
                    "Selecione...": 0.0,
                    "Sim – 0,5": 0.5,
                    "Não – 00": 0.0
                }

                # Estado inicial / persistente
                d11 = res_data.get("1.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_11 = d11.get("valor", "Selecione...")

                # Trata migração de legado caso no banco esteja salvo apenas "Sim" ou "Não"
                if v_salvo_11 == "Sim":
                    v_salvo_11 = "Sim – 0,5"
                elif v_salvo_11 == "Não":
                    v_salvo_11 = "Não – 00"

                evidencia_11_salva = d11.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_11 = f"r_11_{ano_sel}_fiscal"
                chave_link_11 = f"l_11_txt_{ano_sel}_fiscal"
                chave_coment_11 = f"coment_1.1_{ano_sel}_fiscal"

                c11_1, c11_2 = st.columns([1, 1])
                with c11_1:
                    lista_opcoes_11 = list(opcoes_11.keys())
                    idx_11 = lista_opcoes_11.index(v_salvo_11) if v_salvo_11 in lista_opcoes_11 else 0

                    val_radio_11 = st.radio(
                        "Selecione uma opção (1.1):",
                        options=lista_opcoes_11,
                        index=idx_11,
                        key=chave_radio_11
                    )

                with c11_2:
                    link_11 = st.text_area(
                        "Link/Evidência (1.1):",
                        value=evidencia_11_salva,
                        key=chave_link_11,
                        placeholder="Insira o link oficial da lei que estrutura a Administração Tributária...",
                        height=100
                    )
                    placeholder_links_11 = st.empty()
                    links_11_visuais = re.findall(REGEX_PURE_URL, link_11 or "")
                    if links_11_visuais:
                        placeholder_links_11.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_11_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("1.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.1", key=f"btn_salvar_1_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_11, v_salvo_11)
                    pts_11 = float(opcoes_11.get(val_salvar, 0.0))
                    lnk_val = link_11.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_11, d11.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="1.1",
                        valor=val_salvar,
                        pontos=pts_11,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.1"] = {
                        "valor": val_salvar,
                        "pontos": pts_11,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_11_salva or "")]

                    if lnk_val != evidencia_11_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_11 = d11.get("pontos", 0.0)
                cor_txt_11 = "#28a745" if pts_atuais_11 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_11}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.1: +{pts_atuais_11:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.1", st.session_state.get(f"links_pendentes_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.2 • QUADRO DE FISCAIS E AUDITORES (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_1_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.2 - Quadro de Fiscais e Auditores", expanded=True):
                st.subheader("1.2 • Cargos Preenchidos")
                st.write(
                    "**Qual o número de cargos de fiscais/auditores tributários preenchidos?**"
                )
                st.caption(
                    "ℹ *Critério: Se efetivos > 0 E comissão = 0 E terceirizados = 0 ➔ 1,5 ponto. Caso contrário ➔ 0,0 ponto.*"
                )

                # Estado inicial / persistente
                d12 = res_data.get("1.2") or {"valor": "0/0/0", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_12_salva = d12.get("link", "")

                # Extrai os valores numéricos salvos (Efetivos / Comissão / Terceirizados)
                val_bruto_12 = d12.get("valor", "0/0/0")
                try:
                    ef_salvo, com_salvo, terc_salvo = map(int, val_bruto_12.split("/"))
                except Exception:
                    ef_salvo, com_salvo, terc_salvo = 0, 0, 0

                # Chaves fixas por componente e ano
                chave_ef_12 = f"num_12_ef_{ano_sel}_fiscal"
                chave_com_12 = f"num_12_com_{ano_sel}_fiscal"
                chave_terc_12 = f"num_12_terc_{ano_sel}_fiscal"
                chave_link_12 = f"l_12_txt_{ano_sel}_fiscal"
                chave_coment_12 = f"coment_1.2_{ano_sel}_fiscal"

                c12_1, c12_2 = st.columns([1, 1])
                with c12_1:
                    v_ef_12 = st.number_input(
                        "Efetivos:",
                        value=ef_salvo,
                        min_value=0,
                        step=1,
                        key=chave_ef_12
                    )
                    v_com_12 = st.number_input(
                        "Em comissão:",
                        value=com_salvo,
                        min_value=0,
                        step=1,
                        key=chave_com_12
                    )
                    v_terc_12 = st.number_input(
                        "Terceirizados:",
                        value=terc_salvo,
                        min_value=0,
                        step=1,
                        key=chave_terc_12
                    )

                with c12_2:
                    link_12 = st.text_area(
                        "Link/Evidência (1.2):",
                        value=evidencia_12_salva,
                        key=chave_link_12,
                        placeholder="Insira o link oficial com o quantitativo de cargos preenchidos...",
                        height=165
                    )
                    placeholder_links_12 = st.empty()
                    links_12_visuais = re.findall(REGEX_PURE_URL, link_12 or "")
                    if links_12_visuais:
                        placeholder_links_12.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_12_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("1.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.2", key=f"btn_salvar_1_2_{ano_sel}", type="primary"):
                    ef_val = st.session_state.get(chave_ef_12, ef_salvo)
                    com_val = st.session_state.get(chave_com_12, com_salvo)
                    terc_val = st.session_state.get(chave_terc_12, terc_salvo)
                    lnk_val = link_12.strip()

                    # Regra de cálculo de pontuação do Quesito 1.2
                    pts_12 = 1.5 if ef_val > 0 and com_val == 0 and terc_val == 0 else 0.0
                    val_salvar = f"{ef_val}/{com_val}/{terc_val}"

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_12, d12.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="1.2",
                        valor=val_salvar,
                        pontos=pts_12,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.2"] = {
                        "valor": val_salvar,
                        "pontos": pts_12,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_12_salva or "")]

                    if lnk_val != evidencia_12_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_12 = d12.get("pontos", 0.0)
                cor_txt_12 = "#28a745" if pts_atuais_12 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_12}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.2: +{pts_atuais_12:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.3 • CAPACITAÇÃO PERIÓDICA (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_1_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.3 - Capacitação Periódica", expanded=True):
                st.subheader("1.3 • Treinamento de Fiscais")
                st.write(
                    "**Os fiscais tributários recebem treinamento específico para execução das atividades inerentes ao cargo?**"
                )
                st.caption("ℹ *Exigência: Treinamento periódico pelo menos 1 vez ao ano.*")

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 1.3
                opcoes_13 = {
                    "Selecione...": 0.0,
                    "Sim – 1,0": 1.0,
                    "Não – 0,0": 0.0
                }

                # Estado inicial / persistente
                d13 = res_data.get("1.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_13 = d13.get("valor", "Selecione...")

                # Trata migração de legado caso no banco esteja salvo como "Sim – 10" ou no formato antigo
                if "Sim" in v_salvo_13 and "1,0" not in v_salvo_13:
                    v_salvo_13 = "Sim – 1,0"
                elif "Não" in v_salvo_13 and "0,0" not in v_salvo_13:
                    v_salvo_13 = "Não – 0,0"

                evidencia_13_salva = d13.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_13 = f"r_13_{ano_sel}_fiscal"
                chave_link_13 = f"l_13_txt_{ano_sel}_fiscal"
                chave_coment_13 = f"coment_1.3_{ano_sel}_fiscal"

                c13_1, c13_2 = st.columns([1, 1])
                with c13_1:
                    lista_opcoes_13 = list(opcoes_13.keys())
                    idx_13 = lista_opcoes_13.index(v_salvo_13) if v_salvo_13 in lista_opcoes_13 else 0

                    val_radio_13 = st.radio(
                        "Selecione uma opção (1.3):",
                        options=lista_opcoes_13,
                        index=idx_13,
                        key=chave_radio_13
                    )

                with c13_2:
                    link_13 = st.text_area(
                        "Link/Evidência (1.3):",
                        value=evidencia_13_salva,
                        key=chave_link_13,
                        placeholder="Insira o link oficial do certificado, certificado de curso ou portaria de treinamento...",
                        height=100
                    )
                    placeholder_links_13 = st.empty()
                    links_13_visuais = re.findall(REGEX_PURE_URL, link_13 or "")
                    if links_13_visuais:
                        placeholder_links_13.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_13_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("1.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.3", key=f"btn_salvar_1_3_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_13, v_salvo_13)
                    pts_13 = float(opcoes_13.get(val_salvar, 0.0))
                    lnk_val = link_13.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_13, d13.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="1.3",
                        valor=val_salvar,
                        pontos=pts_13,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.3"] = {
                        "valor": val_salvar,
                        "pontos": pts_13,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_13_salva or "")]

                    if lnk_val != evidencia_13_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_13 = d13.get("pontos", 0.0)
                cor_txt_13 = "#28a745" if pts_atuais_13 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_13}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.3: +{pts_atuais_13:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.3", st.session_state.get(f"links_pendentes_1_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.4 • PLANO DE CARGOS E SALÁRIOS (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_1_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.4 - Plano de Cargos e Salários", expanded=True):
                st.subheader("1.4 • PCCS Específico")
                st.write(
                    "**O Município possui Plano de Cargos e Salários específico para seus fiscais tributários?**"
                )
                st.caption(
                    "⚠️ *Atenção: PCCS geral dos servidores públicos não é considerado PCCS específico.*"
                )

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 1.4
                opcoes_14 = {
                    "Selecione...": 0.0,
                    "Sim – 3,0": 3.0,
                    "Não – 0,0": 0.0
                }

                # Estado inicial / persistente
                d14 = res_data.get("1.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_14 = d14.get("valor", "Selecione...")

                # Trata migração de legado caso no banco esteja salvo como "Sim – 03" ou no formato antigo
                if "Sim" in v_salvo_14 and "3,0" not in v_salvo_14:
                    v_salvo_14 = "Sim – 3,0"
                elif "Não" in v_salvo_14 and "0,0" not in v_salvo_14:
                    v_salvo_14 = "Não – 0,0"

                evidencia_14_salva = d14.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_14 = f"r_14_{ano_sel}_fiscal"
                chave_link_14 = f"l_14_txt_{ano_sel}_fiscal"
                chave_coment_14 = f"coment_1.4_{ano_sel}_fiscal"

                c14_1, c14_2 = st.columns([1, 1])
                with c14_1:
                    lista_opcoes_14 = list(opcoes_14.keys())
                    idx_14 = lista_opcoes_14.index(v_salvo_14) if v_salvo_14 in lista_opcoes_14 else 0

                    val_radio_14 = st.radio(
                        "Selecione uma opção (1.4):",
                        options=lista_opcoes_14,
                        index=idx_14,
                        key=chave_radio_14
                    )

                with c14_2:
                    link_14 = st.text_area(
                        "Link/Evidência Geral (1.4):",
                        value=evidencia_14_salva,
                        key=chave_link_14,
                        placeholder="Insira o link oficial da lei do PCCS específico dos fiscais...",
                        height=100
                    )
                    placeholder_links_14 = st.empty()
                    links_14_visuais = re.findall(REGEX_PURE_URL, link_14 or "")
                    if links_14_visuais:
                        placeholder_links_14.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_14_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("1.4", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.4", key=f"btn_salvar_1_4_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_14, v_salvo_14)
                    pts_14 = float(opcoes_14.get(val_salvar, 0.0))
                    lnk_val = link_14.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_14, d14.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="1.4",
                        valor=val_salvar,
                        pontos=pts_14,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.4"] = {
                        "valor": val_salvar,
                        "pontos": pts_14,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_14_salva or "")]

                    if lnk_val != evidencia_14_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_14 = d14.get("pontos", 0.0)
                cor_txt_14 = "#28a745" if pts_atuais_14 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_14}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.4: +{pts_atuais_14:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.4 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.4", st.session_state.get(f"links_pendentes_1_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.4.1 • REGULAMENTAÇÃO DO PCCS (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_1_4_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.4.1 - Regulamentação do PCCS", expanded=True):
                st.subheader("1.4.1 • Instrumento Normativo")
                st.write(
                    "**Informe o instrumento normativo de regulamentação do Plano de Cargos e Salários específico para seus fiscais tributários, Número e Data da publicação:**"
                )
                st.caption(
                    "ℹ️ *Caso não esteja disponível na internet, recomendamos anexar conforme Instrução de Preenchimento (IP).* "
                    "Este quesito é meramente informativo/declaratório e não gera pontuação direta."
                )

                # Estado inicial / persistente
                d141 = res_data.get("1.4.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_141 = d141.get("valor", "")

                # Chaves fixas por componente e ano
                chave_text_141 = f"t141_in_{ano_sel}_fiscal"
                chave_coment_141 = f"coment_1.4.1_{ano_sel}_fiscal"

                val_text_141 = st.text_input(
                    "Número e Data da publicação (Ex: Lei nº 1.234 de 10/05/2020):",
                    value=v_salvo_141,
                    key=chave_text_141,
                    placeholder="Ex: Lei Ordinária Municipal nº 2.450/2021 de 15/03/2021"
                )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("1.4.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.4.1", key=f"btn_salvar_1_4_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_text_141, v_salvo_141).strip()
                    pts_141 = 0.0

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_141, d141.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="1.4.1",
                        valor=val_salvar,
                        pontos=pts_141,
                        link="",
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.4.1"] = {
                        "valor": val_salvar,
                        "pontos": pts_141,
                        "link": "",
                        "comentarios": comentario_para_salvar
                    }

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.4.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 1.4.1: +0.0 pontos (Quesito Declaratório)</span>",
                    unsafe_allow_html=True
                )

        # =============================================================================
        # QUESITO 1.4.2 • DIVULGAÇÃO ELETRÔNICA DO PCCS (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_1_4_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.4.2 - Divulgação Eletrônica do PCCS", expanded=True):
                st.subheader("1.4.2 • Página Eletrônica do PCCS")
                st.write(
                    "**Informe a página eletrônica (link na internet) de divulgação do Plano de Cargos e Salários específico para os fiscais tributários:**"
                )
                st.caption(
                    "ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ**.* "
                    "Este quesito é meramente informativo/declaratório e não gera pontuação direta."
                )

                # Estado inicial / persistente
                d142 = res_data.get("1.4.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_142 = d142.get("valor", "")

                # Chaves fixas por componente e ano
                chave_text_142 = f"t142_in_{ano_sel}_fiscal"
                chave_coment_142 = f"coment_1.4.2_{ano_sel}_fiscal"

                val_text_142 = st.text_input(
                    "Página eletrônica (ou XYZ):",
                    value=v_salvo_142,
                    key=chave_text_142,
                    placeholder="https://... ou XYZ"
                )

                # Visualização dinâmica dos links detectados no próprio campo de texto
                placeholder_links_142 = st.empty()
                links_142_visuais = [
                    u[0] if isinstance(u, tuple) else u
                    for u in re.findall(REGEX_PURE_URL, val_text_142 or "")
                ]
                if links_142_visuais:
                    placeholder_links_142.markdown(
                        "**🔗 Link ativo:** "
                        + " | ".join([f"[{u}]({u})" for u in links_142_visuais])
                    )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("1.4.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.4.2", key=f"btn_salvar_1_4_2_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_text_142, v_salvo_142).strip()
                    pts_142 = 0.0

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_142, d142.get("comentario", ""))

                    # Salva no banco de dados Neon (o próprio campo 'valor' funciona como link)
                    save_resp_ifiscal(
                        qid="1.4.2",
                        valor=val_salvar,
                        pontos=pts_142,
                        link=val_salvar,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.4.2"] = {
                        "valor": val_salvar,
                        "pontos": pts_142,
                        "link": val_salvar,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, val_salvar or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_142 or "")]

                    if val_salvar != v_salvo_142 and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.4.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 1.4.2: +0.0 pontos (Quesito Declaratório)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.4.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.4.2", st.session_state.get(f"links_pendentes_1_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.5 • SEGREGAÇÃO DE FUNÇÕES (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_1_5_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.5 - Segregação de Funções", expanded=True):
                st.subheader("1.5 • Segregação de Funções Administrativas")
                st.write(
                    "**Há segregação de funções entre os setores de lançadoria, arrecadação, fiscalização e contabilidade?**"
                )
                st.caption(
                    "ℹ️ *Critério: O órgão deve demonstrar a divisão independente de competências para evitar conflitos de interesse.*"
                )

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 1.5
                opcoes_15 = {
                    "Selecione...": 0.0,
                    "Sim – 5,0": 5.0,
                    "Não – 0,0": 0.0
                }

                # Estado inicial / persistente
                d15 = res_data.get("1.5") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_15 = d15.get("valor", "Selecione...")

                # Trata migração de legado caso no banco esteja salvo como "Sim – 05" ou no formato antigo
                if "Sim" in v_salvo_15 and "5,0" not in v_salvo_15:
                    v_salvo_15 = "Sim – 5,0"
                elif "Não" in v_salvo_15 and "0,0" not in v_salvo_15:
                    v_salvo_15 = "Não – 0,0"

                evidencia_15_salva = d15.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_15 = f"r_15_{ano_sel}_fiscal"
                chave_link_15 = f"l_15_txt_{ano_sel}_fiscal"
                chave_coment_15 = f"coment_1.5_{ano_sel}_fiscal"

                c15_1, c15_2 = st.columns([1, 1])
                with c15_1:
                    lista_opcoes_15 = list(opcoes_15.keys())
                    idx_15 = lista_opcoes_15.index(v_salvo_15) if v_salvo_15 in lista_opcoes_15 else 0

                    val_radio_15 = st.radio(
                        "Selecione uma opção (1.5):",
                        options=lista_opcoes_15,
                        index=idx_15,
                        key=chave_radio_15
                    )

                with c15_2:
                    link_15 = st.text_area(
                        "Link/Evidência (1.5):",
                        value=evidencia_15_salva,
                        key=chave_link_15,
                        placeholder="Insira o link oficial com organograma, regimento interno ou portarias...",
                        height=100
                    )
                    placeholder_links_15 = st.empty()
                    links_15_visuais = re.findall(REGEX_PURE_URL, link_15 or "")
                    if links_15_visuais:
                        placeholder_links_15.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_15_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("1.5", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.5", key=f"btn_salvar_1_5_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_15, v_salvo_15)
                    pts_15 = float(opcoes_15.get(val_salvar, 0.0))
                    lnk_val = link_15.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_15, d15.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="1.5",
                        valor=val_salvar,
                        pontos=pts_15,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.5"] = {
                        "valor": val_salvar,
                        "pontos": pts_15,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_15_salva or "")]

                    if lnk_val != evidencia_15_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_15 = d15.get("pontos", 0.0)
                cor_txt_15 = "#28a745" if pts_atuais_15 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_15}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.5: +{pts_atuais_15:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.5 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.5", st.session_state.get(f"links_pendentes_1_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_5_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.5.1 • PERMISSÕES DO SISTEMA (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_1_5_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 1.5.1 - Permissões do Sistema", expanded=True):
                st.subheader("1.5.1 • Permissões de Acesso e Auditoria")
                st.write(
                    "**Há segregação nas permissões de acesso do sistema, com identificação do usuário e registro das transações efetuadas?**"
                )
                st.caption(
                    "ℹ️ *Critério: O sistema deve registrar logs auditáveis de acesso e operações por usuário individual.*"
                )

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 1.5.1
                opcoes_151 = {
                    "Selecione...": 0.0,
                    "Sim – 5,0": 5.0,
                    "Não – 0,0": 0.0,
                    "Ausência de segregação para lançamento, arrecadação ou fiscalização – -3,0": -3.0
                }

                # Estado inicial / persistente
                d151 = res_data.get("1.5.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_151 = d151.get("valor", "Selecione...")

                # Tratamento de legados/formatos anteriores
                if "Sim" in v_salvo_151 and "5,0" not in v_salvo_151:
                    v_salvo_151 = "Sim – 5,0"
                elif "Não" in v_salvo_151 and "0,0" not in v_salvo_151:
                    v_salvo_151 = "Não – 0,0"
                elif "-03" in v_salvo_151 or "perde 03" in v_salvo_151:
                    v_salvo_151 = "Ausência de segregação para lançamento, arrecadação ou fiscalização – -3,0"

                evidencia_151_salva = d151.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_151 = f"r_151_{ano_sel}_fiscal"
                chave_link_151 = f"l_151_txt_{ano_sel}_fiscal"
                chave_coment_151 = f"coment_1.5.1_{ano_sel}_fiscal"

                c151_1, c151_2 = st.columns([1, 1])
                with c151_1:
                    lista_opcoes_151 = list(opcoes_151.keys())
                    idx_151 = lista_opcoes_151.index(v_salvo_151) if v_salvo_151 in lista_opcoes_151 else 0

                    val_radio_151 = st.radio(
                        "Selecione uma opção (1.5.1):",
                        options=lista_opcoes_151,
                        index=idx_151,
                        key=chave_radio_151
                    )

                with c151_2:
                    link_151 = st.text_area(
                        "Link/Evidência (1.5.1):",
                        value=evidencia_151_salva,
                        key=chave_link_151,
                        placeholder="Insira o link oficial, relatório de auditoria ou telas do sistema...",
                        height=100
                    )
                    placeholder_links_151 = st.empty()
                    links_151_visuais = re.findall(REGEX_PURE_URL, link_151 or "")
                    if links_151_visuais:
                        placeholder_links_151.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_151_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("1.5.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 1.5.1", key=f"btn_salvar_1_5_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_151, v_salvo_151)
                    pts_151 = float(opcoes_151.get(val_salvar, 0.0))
                    lnk_val = link_151.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_151, d151.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="1.5.1",
                        valor=val_salvar,
                        pontos=pts_151,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["1.5.1"] = {
                        "valor": val_salvar,
                        "pontos": pts_151,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_151_salva or "")]

                    if lnk_val != evidencia_151_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_1_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_1_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 1.5.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_151 = d151.get("pontos", 0.0)
                if pts_atuais_151 > 0.0:
                    cor_txt_151 = "#28a745"
                elif pts_atuais_151 < 0.0:
                    cor_txt_151 = "#dc3545"
                else:
                    cor_txt_151 = "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_151}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 1.5.1: {pts_atuais_151:+.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 1.5.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_1_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("1.5.1", st.session_state.get(f"links_pendentes_1_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_5_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 2.0 • RESPONSÁVEL PELA CONTABILIDADE (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_2_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 2.0 - Responsável pela Contabilidade", expanded=True):
                st.subheader("2.0 • Provimento do Cargo de Contabilidade")
                st.write(
                    "**O servidor responsável pela contabilidade do município é ocupante de cargo de provimento efetivo?**"
                )
                st.caption(
                    "ℹ️ *Critério: O responsável técnico pela contabilidade municipal deve ter vínculo efetivo (concurso público).* "
                )

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 2.0
                opcoes_20 = {
                    "Selecione...": 0.0,
                    "Sim – 4,0": 4.0,
                    "Não – 0,0": 0.0
                }

                # Estado inicial / persistente
                d20 = res_data.get("2.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_20 = d20.get("valor", "Selecione...")

                # Tratamento de legados/formatos anteriores (ex: "Sim – 04")
                if "Sim" in v_salvo_20 and "4,0" not in v_salvo_20:
                    v_salvo_20 = "Sim – 4,0"
                elif "Não" in v_salvo_20 and "0,0" not in v_salvo_20:
                    v_salvo_20 = "Não – 0,0"

                evidencia_20_salva = d20.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_20 = f"r_20_{ano_sel}_fiscal"
                chave_link_20 = f"l_20_txt_{ano_sel}_fiscal"
                chave_coment_20 = f"coment_2.0_{ano_sel}_fiscal"

                c20_1, c20_2 = st.columns([1, 1])
                with c20_1:
                    lista_opcoes_20 = list(opcoes_20.keys())
                    idx_20 = lista_opcoes_20.index(v_salvo_20) if v_salvo_20 in lista_opcoes_20 else 0

                    val_radio_20 = st.radio(
                        "Selecione uma opção (2.0):",
                        options=lista_opcoes_20,
                        index=idx_20,
                        key=chave_radio_20
                    )

                with c20_2:
                    link_20 = st.text_area(
                        "Link/Evidência (2.0):",
                        value=evidencia_20_salva,
                        key=chave_link_20,
                        placeholder="Insira o link oficial (termo de posse, edital de concurso, portal da transparência...)",
                        height=100
                    )
                    placeholder_links_20 = st.empty()
                    links_20_visuais = re.findall(REGEX_PURE_URL, link_20 or "")
                    if links_20_visuais:
                        placeholder_links_20.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_20_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("2.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 2.0", key=f"btn_salvar_2_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_20, v_salvo_20)
                    pts_20 = float(opcoes_20.get(val_salvar, 0.0))
                    lnk_val = link_20.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_20, d20.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="2.0",
                        valor=val_salvar,
                        pontos=pts_20,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["2.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_20,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_20_salva or "")]

                    if lnk_val != evidencia_20_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 2.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_20 = d20.get("pontos", 0.0)
                cor_txt_20 = "#28a745" if pts_atuais_20 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_20}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 2.0: +{pts_atuais_20:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 2.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 3.0 • MEDIDAS DE ARRECADAÇÃO (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_3_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 3.0 - Medidas de Arrecadação", expanded=True):
                st.subheader("3.0 • Efetividade na Arrecadação")
                st.write(
                    "**O Município adotou medidas efetivas para aumento da arrecadação?**"
                )
                st.caption(
                    "ℹ️ *Critério: O município deve comprovar a implementação de políticas, programas ou ações práticas voltadas à expansão da arrecadação própria.*"
                )

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 3.0
                opcoes_30 = {
                    "Selecione...": 0.0,
                    "Sim – 30,0": 30.0,
                    "Não – 0,0": 0.0
                }

                # Estado inicial / persistente
                d30 = res_data.get("3.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_30 = d30.get("valor", "Selecione...")

                # Tratamento de legados/formatos anteriores (ex: "Sim – 30")
                if "Sim" in v_salvo_30 and "30,0" not in v_salvo_30:
                    v_salvo_30 = "Sim – 30,0"
                elif "Não" in v_salvo_30 and "0,0" not in v_salvo_30:
                    v_salvo_30 = "Não – 0,0"

                evidencia_30_salva = d30.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_30 = f"r_30_{ano_sel}_fiscal"
                chave_link_30 = f"l_30_txt_{ano_sel}_fiscal"
                chave_coment_30 = f"coment_3.0_{ano_sel}_fiscal"

                c30_1, c30_2 = st.columns([1, 1])
                with c30_1:
                    lista_opcoes_30 = list(opcoes_30.keys())
                    idx_30 = lista_opcoes_30.index(v_salvo_30) if v_salvo_30 in lista_opcoes_30 else 0

                    val_radio_30 = st.radio(
                        "Selecione uma opção (3.0):",
                        options=lista_opcoes_30,
                        index=idx_30,
                        key=chave_radio_30
                    )

                with c30_2:
                    link_30 = st.text_area(
                        "Link/Evidência Geral (3.0):",
                        value=evidencia_30_salva,
                        key=chave_link_30,
                        placeholder="Insira o link oficial com leis de incentivo, relatórios de arrecadação ou campanhas tributárias...",
                        height=100
                    )
                    placeholder_links_30 = st.empty()
                    links_30_visuais = re.findall(REGEX_PURE_URL, link_30 or "")
                    if links_30_visuais:
                        placeholder_links_30.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_30_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("3.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 3.0", key=f"btn_salvar_3_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_30, v_salvo_30)
                    pts_30 = float(opcoes_30.get(val_salvar, 0.0))
                    lnk_val = link_30.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_30, d30.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="3.0",
                        valor=val_salvar,
                        pontos=pts_30,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["3.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_30,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_30_salva or "")]

                    if lnk_val != evidencia_30_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 3.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_30 = d30.get("pontos", 0.0)
                cor_txt_30 = "#28a745" if pts_atuais_30 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_30}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 3.0: +{pts_atuais_30:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 3.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 3.1 • DETALHAMENTO DAS MEDIDAS - CHECKLIST (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_3_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 3.1 - Detalhamento das Medidas (Checklist)", expanded=True):
                st.subheader("3.1 • Medidas Implementadas")
                st.write("**Assinale as medidas implementadas para o aumento da arrecadação:**")
                st.caption(
                    "ℹ️ *Critério: Marque todas as ações e programas efetivamente adotados pelo município.*"
                )

                # Lista de Opções do Checklist
                opc31 = [
                    "Recadastramento de Imóveis",
                    "Programas de Recuperação Fiscal",
                    "Implementação de Nota Fiscal Eletrônica",
                    "Convênios com a União e o Estado para compartilhamento de Informações",
                    "Parceria/Convênio com os tabelionatos de notas e Registros de Imóveis",
                    "Protesto da Certidão de Dívida Ativa",
                    "Convênios com órgãos de proteção ao crédito",
                    "Convênio com o Governo Federal para a cobrança do ITR (Imposto sobre a Propriedade Territorial Rural)",
                    "Outros"
                ]

                # Estado inicial / persistente
                d31 = res_data.get("3.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_31_salva = d31.get("link", "")

                # Desserialização do JSON armazenado em d31["valor"]
                valor_cru_31 = d31.get("valor", "[]")
                try:
                    if isinstance(valor_cru_31, list):
                        sel31 = valor_cru_31
                    else:
                        sel31 = json.loads(valor_cru_31.replace("'", '"'))
                        if not isinstance(sel31, list):
                            sel31 = []
                except Exception:
                    sel31 = []

                # Chaves fixas por componente e ano
                chave_link_31 = f"l_31_txt_{ano_sel}_fiscal"
                chave_coment_31 = f"coment_3.1_{ano_sel}_fiscal"

                # Renderização dos Checkboxes em 2 colunas
                col_chk1, col_chk2 = st.columns(2)
                for i, opcao in enumerate(opc31):
                    target_col = col_chk1 if i % 2 == 0 else col_chk2
                    with target_col:
                        ja_checado = opcao in sel31
                        st.checkbox(
                            opcao,
                            value=ja_checado,
                            key=f"chk_31_{i}_{ano_sel}_fiscal"
                        )

                st.markdown("---")

                # Campo de Evidências / Links
                link_31 = st.text_area(
                    "Link/Evidência Específica (3.1):",
                    value=evidencia_31_salva,
                    key=chave_link_31,
                    placeholder="Insira os links e comprovações específicos das medidas assinaladas acima...",
                    height=100
                )
                placeholder_links_31 = st.empty()
                links_31_visuais = re.findall(REGEX_PURE_URL, link_31 or "")
                if links_31_visuais:
                    placeholder_links_31.markdown(
                        "**🔗 Link ativo:** "
                        + " | ".join(
                            [
                                f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                for u in links_31_visuais
                            ]
                        )
                    )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("3.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 3.1", key=f"btn_salvar_3_1_{ano_sel}", type="primary"):
                    # Coleta o estado atual dos checkboxes no session_state
                    lista_selecionados_31 = []
                    for i, opcao in enumerate(opc31):
                        if st.session_state.get(f"chk_31_{i}_{ano_sel}_fiscal", False):
                            lista_selecionados_31.append(opcao)

                    json_str_31 = json.dumps(lista_selecionados_31, ensure_ascii=False)
                    lnk_val = link_31.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_31, d31.get("comentario", ""))

                    # Salva no banco de dados Neon (Checklist tem peso informativo: 0.0 pontos)
                    save_resp_ifiscal(
                        qid="3.1",
                        valor=json_str_31,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["3.1"] = {
                        "valor": json_str_31,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_31_salva or "")]

                    if lnk_val != evidencia_31_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_31 = d31.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 3.1: {pts_atuais_31:+.1f} pontos (Checklist Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 4.0 • REVISÃO DO CADASTRO IMOBILIÁRIO (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_4_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 4.0 - Procedimento de Revisão do Cadastro Imobiliário", expanded=True):
                st.subheader("4.0 • Instituição de Revisão Periódica")
                st.write("**Foi instituído procedimento de revisão do cadastro imobiliário estabelecendo a sua periodicidade?**")
                st.caption(
                    "⚠️ **Obs.:** *A mera atualização cadastral por solicitação do contribuinte realizada de forma pontual e esporádica, "
                    "sem qualquer convocação ou iniciativa por parte da Prefeitura Municipal, não será considerada na questão como revisão "
                    "periódica e geral do Cadastro imobiliário.*"
                )

                # Opções de Seleção
                opc40 = ["Selecione...", "Sim", "Não"]

                # Estado inicial / persistente
                d40 = res_data.get("4.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_40 = d40.get("valor", "Selecione...")
                if v_salvo_40 not in opc40:
                    v_salvo_40 = "Selecione..."
                evidencia_40_salva = d40.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_40 = f"r_40_in_{ano_sel}_fiscal"
                chave_link_40 = f"l_40_in_{ano_sel}_fiscal"
                chave_coment_40 = f"coment_4.0_{ano_sel}_fiscal"

                # Layout de entrada (Radio e Link em 2 colunas)
                col1, col2 = st.columns([1, 1])
                with col1:
                    v_radio_40 = st.radio(
                        "Selecione uma opção (4.0):",
                        options=opc40,
                        index=opc40.index(v_salvo_40),
                        key=chave_radio_40
                    )
                with col2:
                    link_40 = st.text_area(
                        "Link/Evidência Geral (4.0):",
                        value=evidencia_40_salva,
                        key=chave_link_40,
                        placeholder="Insira os links e evidências pertinentes...",
                        height=100
                    )
                    placeholder_links_40 = st.empty()
                    links_40_visuais = re.findall(REGEX_PURE_URL, link_40 or "")
                    if links_40_visuais:
                        placeholder_links_40.markdown(
                            "**🔗 Link ativo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_40_visuais
                                ]
                            )
                        )

                # Bloco de comentários do quesito
                bloco_comentarios_ifiscal("4.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 4.0", key=f"btn_salvar_4_0_{ano_sel}", type="primary"):
                    val_sel_40 = st.session_state.get(chave_radio_40, v_salvo_40)
                    lnk_val = link_40.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_40, d40.get("comentario", ""))

                    # Salva no banco de dados (Pontuação zero / informativa)
                    save_resp_ifiscal(
                        qid="4.0",
                        valor=val_sel_40,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário res_data localmente
                    res_data["4.0"] = {
                        "valor": val_sel_40,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_40_salva or "")]

                    if lnk_val != evidencia_40_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 4.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico de pontuação
                pts_atuais_40 = d40.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 4.0: {pts_atuais_40:+.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 4.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 4.1 • DETALHAMENTO NORMATIVO E DIVULGAÇÃO (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_4_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 4.1 - Detalhamento Normativo e Divulgação", expanded=True):
                st.subheader("4.1 • Instrumento Normativo e Endereço Eletrônico")
                st.write(
                    "**Informe o instrumento normativo (número e data da aprovação) e "
                    "endereço eletrônico de divulgação do procedimento de revisão do cadastro imobiliário:**"
                )
                st.caption(
                    "ℹ️ *Critério: Preencha os dados do ato normativo e o link onde a revisão cadastral foi publicada.*"
                )

                # Estado inicial / persistente
                d41 = res_data.get("4.1") or {"valor": " | ", "pontos": 0.0, "link": "", "comentario": ""}
                evidencia_41_salva = d41.get("link", "")

                # Extração do normativo e link do campo valor
                valor_salvo_41 = d41.get("valor", " | ")
                try:
                    normativo_salvo, link_salvo = valor_salvo_41.split(" | ", 1)
                except Exception:
                    normativo_salvo, link_salvo = "", ""

                # Chaves fixas por componente e ano
                chave_norm_41 = f"t41_norm_{ano_sel}_fiscal"
                chave_link_div_41 = f"t41_link_{ano_sel}_fiscal"
                chave_link_evid_41 = f"l41_in_{ano_sel}_fiscal"
                chave_coment_41 = f"coment_4.1_{ano_sel}_fiscal"

                # Campos de entrada de texto para o quesito
                normativo_input = st.text_input(
                    "Instrumento Normativo (Número e Data):",
                    value=normativo_salvo,
                    key=chave_norm_41,
                    placeholder="Ex: Lei Municipal nº 1.234 de 15/03/2023..."
                )

                link_divulgacao_input = st.text_input(
                    "Endereço Eletrônico de Divulgação (Campo do Quesito):",
                    value=link_salvo,
                    key=chave_link_div_41,
                    placeholder="https://..."
                )

                # Visualizador de link ativo do campo de divulgação
                placeholder_link_div = st.empty()
                links_div_visuais = re.findall(REGEX_PURE_URL, link_divulgacao_input or "")
                if links_div_visuais:
                    placeholder_link_div.markdown(
                        "**🔗 Links detectados no campo normativo:** "
                        + " | ".join(
                            [
                                f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                for u in links_div_visuais
                            ]
                        )
                    )

                st.markdown("---")

                # Campo de Evidência Geral
                link_evidencia_41 = st.text_area(
                    "Link/Evidência Geral (4.1):",
                    value=evidencia_41_salva,
                    key=chave_link_evid_41,
                    placeholder="Insira os links e evidências complementares do quesito 4.1...",
                    height=100
                )

                placeholder_links_evid = st.empty()
                links_evid_visuais = re.findall(REGEX_PURE_URL, link_evidencia_41 or "")
                if links_evid_visuais:
                    placeholder_links_evid.markdown(
                        "**🔗 Ativos (Evidência 4.1):** "
                        + " | ".join(
                            [
                                f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                for u in links_evid_visuais
                            ]
                        )
                    )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("4.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 4.1", key=f"btn_salvar_4_1_{ano_sel}", type="primary"):
                    val_norm = st.session_state.get(chave_norm_41, normativo_salvo).strip()
                    val_div = st.session_state.get(chave_link_div_41, link_salvo).strip()
                    novo_valor_41 = f"{val_norm} | {val_div}"

                    lnk_val = link_evidencia_41.strip()

                    # Captura o comentário do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_41, d41.get("comentario", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 pontos)
                    save_resp_ifiscal(
                        qid="4.1",
                        valor=novo_valor_41,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["4.1"] = {
                        "valor": novo_valor_41,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_41_salva or "")]

                    if lnk_val != evidencia_41_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 4.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_41 = d41.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 4.1: {pts_atuais_41:+.1f} pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 4.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.1", st.session_state.get(f"links_pendentes_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 4.2 • PERIODICIDADE DA REVISÃO (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_4_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 4.2 - Periodicidade da Revisão", expanded=True):
                st.subheader("4.2 • Janela Temporal de Revisão")
                st.write("**Qual a periodicidade da revisão geral do Cadastro Imobiliário?**")
                st.caption(
                    "ℹ️ *Critério: Selecione o intervalo de tempo regulamentado para a atualização periódica do cadastro.*"
                )

                # Opções de Seleção de Periodicidade
                opc42 = [
                    "Selecione...",
                    "Menor ou igual a 1 ano",
                    "Maior que 1 e menor ou igual a 4 anos",
                    "Maior que 4 e menor ou igual a 8 anos",
                    "Maior que 8 anos"
                ]

                # Estado inicial / persistente
                d42 = res_data.get("4.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_42 = d42.get("valor", "Selecione...")
                if v_salvo_42 not in opc42:
                    v_salvo_42 = "Selecione..."
                evidencia_42_salva = d42.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_42 = f"r42_in_{ano_sel}_fiscal"
                chave_link_42 = f"l42_in_{ano_sel}_fiscal"
                chave_coment_42 = f"coment_4.2_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_radio_42 = st.radio(
                        "Selecione a periodicidade (4.2):",
                        options=opc42,
                        index=opc42.index(v_salvo_42),
                        key=chave_radio_42
                    )

                with col2:
                    link_42 = st.text_area(
                        "Link/Evidência Geral (4.2):",
                        value=evidencia_42_salva,
                        key=chave_link_42,
                        placeholder="Insira os links e evidências comprobatórias da periodicidade...",
                        height=100
                    )
                    placeholder_links_42 = st.empty()
                    links_42_visuais = re.findall(REGEX_PURE_URL, link_42 or "")
                    if links_42_visuais:
                        placeholder_links_42.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_42_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("4.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 4.2", key=f"btn_salvar_4_2_{ano_sel}", type="primary"):
                    val_sel_42 = st.session_state.get(chave_radio_42, v_salvo_42)
                    lnk_val = link_42.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_42, d42.get("comentario", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 pontos)
                    save_resp_ifiscal(
                        qid="4.2",
                        valor=val_sel_42,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["4.2"] = {
                        "valor": val_sel_42,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_42_salva or "")]

                    if lnk_val != evidencia_42_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 4.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_42 = d42.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#6c757d; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 4.2: {pts_atuais_42:+.1f} pontos (Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 4.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_4_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.2", st.session_state.get(f"links_pendentes_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 4.3 • STATUS DE ATUALIZAÇÃO DO CADASTRO (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_4_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 4.3 - Status de Atualização do Cadastro", expanded=True):
                st.subheader("4.3 • Revisão Atualizada")
                st.write("**O cadastro imobiliário está com a revisão periódica ou geral atualizada?**")
                st.caption(
                    "⚠️ **Obs.:** *A mera atualização cadastral por solicitação do contribuinte realizada de forma pontual e esporádica, "
                    "sem qualquer convocação ou iniciativa por parte da Prefeitura Municipal, não será considerada na questão como revisão "
                    "periódica e geral do Cadastro imobiliário.*"
                )

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 4.3
                opcoes_43 = {
                    "Selecione...": 0.0,
                    "Sim – 5,0": 5.0,
                    "Não – 0,0": 0.0
                }

                # Estado inicial / persistente
                d43 = res_data.get("4.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_43 = d43.get("valor", "Selecione...")

                # Tratamento de legados/formatos anteriores (ex: "Sim – 05" ou "Sim – 5")
                if "Sim" in v_salvo_43 and "5,0" not in v_salvo_43:
                    v_salvo_43 = "Sim – 5,0"
                elif "Não" in v_salvo_43 and "0,0" not in v_salvo_43:
                    v_salvo_43 = "Não – 0,0"

                evidencia_43_salva = d43.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_43 = f"r43_in_{ano_sel}_fiscal"
                chave_link_43 = f"l43_in_{ano_sel}_fiscal"
                chave_coment_43 = f"coment_4.3_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    lista_opcoes_43 = list(opcoes_43.keys())
                    idx_43 = lista_opcoes_43.index(v_salvo_43) if v_salvo_43 in lista_opcoes_43 else 0

                    val_radio_43 = st.radio(
                        "Selecione uma opção (4.3):",
                        options=lista_opcoes_43,
                        index=idx_43,
                        key=chave_radio_43
                    )

                with col2:
                    link_43 = st.text_area(
                        "Link/Evidência (4.3):",
                        value=evidencia_43_salva,
                        key=chave_link_43,
                        placeholder="Insira os links e comprovações referentes ao status de atualização...",
                        height=100
                    )
                    placeholder_links_43 = st.empty()
                    links_43_visuais = re.findall(REGEX_PURE_URL, link_43 or "")
                    if links_43_visuais:
                        placeholder_links_43.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_43_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("4.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 4.3", key=f"btn_salvar_4_3_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_43, v_salvo_43)
                    pts_43 = float(opcoes_43.get(val_salvar, 0.0))
                    lnk_val = link_43.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_43, d43.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="4.3",
                        valor=val_salvar,
                        pontos=pts_43,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["4.3"] = {
                        "valor": val_salvar,
                        "pontos": pts_43,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_43_salva or "")]

                    if lnk_val != evidencia_43_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_4_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_4_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 4.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_43 = d43.get("pontos", 0.0)
                cor_txt_43 = "#28a745" if pts_atuais_43 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_43}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 4.3: +{pts_atuais_43:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 4.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_4_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("4.3", st.session_state.get(f"links_pendentes_4_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.0 • APROVAÇÃO DA PGV POR LEI (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.0 - Aprovação da PGV por Lei", expanded=True):
                st.subheader("5.0 • Aprovação Legal da PGV")
                st.write(
                    "**O instrumento da Planta Genérica de Valores (PGV) foi aprovado por lei, "
                    "conforme previsto no Código Tributário Nacional (CTN)?**"
                )
                st.caption(
                    "ℹ️ *Critério: A aprovação da PGV exige previsão legal formal nos termos da legislação tributária vigência.*"
                )

                # Dicionário com Mapeamento de Opções e Pontuações do iFiscal 5.0
                opcoes_50 = {
                    "Selecione...": 0.0,
                    "Sim – 3,0": 3.0,
                    "Não – 0,0": 0.0
                }

                # Estado inicial / persistente
                d50 = res_data.get("5.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_50 = d50.get("valor", "Selecione...")

                # Tratamento de legados/formatos anteriores (ex: "Sim – 03" ou "Sim – 3")
                if "Sim" in v_salvo_50 and "3,0" not in v_salvo_50:
                    v_salvo_50 = "Sim – 3,0"
                elif "Não" in v_salvo_50 and "0,0" not in v_salvo_50:
                    v_salvo_50 = "Não – 0,0"

                evidencia_50_salva = d50.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_50 = f"r50_in_{ano_sel}_fiscal"
                chave_link_50 = f"l50_in_{ano_sel}_fiscal"
                chave_coment_50 = f"coment_5.0_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    lista_opcoes_50 = list(opcoes_50.keys())
                    idx_50 = lista_opcoes_50.index(v_salvo_50) if v_salvo_50 in lista_opcoes_50 else 0

                    val_radio_50 = st.radio(
                        "Selecione uma opção (5.0):",
                        options=lista_opcoes_50,
                        index=idx_50,
                        key=chave_radio_50
                    )

                with col2:
                    link_50 = st.text_area(
                        "Link/Evidência Geral (5.0):",
                        value=evidencia_50_salva,
                        key=chave_link_50,
                        placeholder="Insira os links da norma de aprovação da PGV e evidências legais...",
                        height=100
                    )
                    placeholder_links_50 = st.empty()
                    links_50_visuais = re.findall(REGEX_PURE_URL, link_50 or "")
                    if links_50_visuais:
                        placeholder_links_50.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_50_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.0", key=f"btn_salvar_5_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_50, v_salvo_50)
                    pts_50 = float(opcoes_50.get(val_salvar, 0.0))
                    lnk_val = link_50.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_50, d50.get("comentario", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="5.0",
                        valor=val_salvar,
                        pontos=pts_50,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.0"] = {
                        "valor": val_salvar,
                        "pontos": pts_50,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_50_salva or "")]

                    if lnk_val != evidencia_50_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentário do Quesito 5.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                pts_atuais_50 = d50.get("pontos", 0.0)
                cor_txt_50 = "#28a745" if pts_atuais_50 > 0.0 else "#6c757d"

                st.markdown(
                    f"<span style='color:{cor_txt_50}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 5.0: +{pts_atuais_50:.1f} pontos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.0", st.session_state.get(f"links_pendentes_5_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.1 • DETALHAMENTO NORMATIVO DA PGV (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.1 - Instrumento Normativo da PGV", expanded=True):
                st.subheader("5.1 • Detalhamento Normativo")
                st.write(
                    "**Informe o Instrumento normativo de aprovação da Planta Genérica de Valores (PGV), "
                    "Número e Data da publicação:**"
                )
                st.caption(
                    "ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*"
                )

                # Estado inicial / persistente (Pontuação fixa de 0.0)
                d51 = res_data.get("5.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_51 = d51.get("valor", "")
                evidencia_51_salva = d51.get("link", "")

                # Chaves fixas por componente e ano
                chave_texto_51 = f"t51_val_{ano_sel}_fiscal"
                chave_link_51 = f"l51_in_{ano_sel}_fiscal"
                chave_coment_51 = f"coment_5.1_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_texto_51 = st.text_input(
                        "Instrumento normativo de aprovação (Nº e Data):",
                        value=v_salvo_51,
                        key=chave_texto_51,
                        placeholder="Ex: Lei Municipal nº 1.234/2022, publicada em 15/12/2022"
                    )

                with col2:
                    link_51 = st.text_area(
                        "Link/Evidência (5.1):",
                        value=evidencia_51_salva,
                        key=chave_link_51,
                        placeholder="Insira os links da norma, diário oficial ou documento da PGV...",
                        height=100
                    )
                    placeholder_links_51 = st.empty()
                    links_51_visuais = re.findall(REGEX_PURE_URL, link_51 or "")
                    if links_51_visuais:
                        placeholder_links_51.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_51_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.1", key=f"btn_salvar_5_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_texto_51, v_salvo_51).strip()
                    lnk_val = link_51.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_51, d51.get("comentario", ""))

                    # Salva no banco de dados Neon (pontuação é 0.0 por ser quesito informativo/descritivo)
                    save_resp_ifiscal(
                        qid="5.1",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.1"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_51_salva or "")]

                    if lnk_val != evidencia_51_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 5.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 5.1: 0,0 ponto (Quesito Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.1", st.session_state.get(f"links_pendentes_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.2 • PÁGINA DE DIVULGAÇÃO DA PGV (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.2 - Página de Divulgação da PGV", expanded=True):
                st.subheader("5.2 • Divulgação Eletrônica")
                st.write(
                    "**Informe a página eletrônica (link na internet) de divulgação do Instrumento Normativo "
                    "de aprovação da Planta Genérica de Valores (PGV):**"
                )
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")

                # Estado inicial / persistente (Pontuação fixa de 0.0)
                d52 = res_data.get("5.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_52 = d52.get("valor", "")
                evidencia_52_salva = d52.get("link", "")

                # Chaves fixas por componente e ano
                chave_texto_52 = f"t52_val_{ano_sel}_fiscal"
                chave_link_52 = f"l52_in_{ano_sel}_fiscal"
                chave_coment_52 = f"coment_5.2_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_texto_52 = st.text_input(
                        "Link de divulgação do instrumento (ou XYZ):",
                        value=v_salvo_52,
                        key=chave_texto_52,
                        placeholder="https://... ou XYZ"
                    )
                    
                    # Detecta e exibe links no campo de divulgação
                    placeholder_detec_52 = st.empty()
                    links_detec_52 = re.findall(REGEX_PURE_URL, val_texto_52 or "")
                    if links_detec_52:
                        placeholder_detec_52.markdown(
                            "**🔗 Detectado no campo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_detec_52
                                ]
                            )
                        )

                with col2:
                    link_52 = st.text_area(
                        "Link/Evidência Geral (5.2):",
                        value=evidencia_52_salva,
                        key=chave_link_52,
                        placeholder="Insira os links e evidências complementares da divulgação...",
                        height=100
                    )
                    placeholder_links_52 = st.empty()
                    links_52_visuais = re.findall(REGEX_PURE_URL, link_52 or "")
                    if links_52_visuais:
                        placeholder_links_52.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_52_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.2", key=f"btn_salvar_5_2_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_texto_52, v_salvo_52).strip()
                    lnk_val = link_52.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_52, d52.get("comentario", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 ponto)
                    save_resp_ifiscal(
                        qid="5.2",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.2"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_52_salva or "")]

                    if lnk_val != evidencia_52_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 5.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 5.2: 0,0 ponto (Quesito Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.2", st.session_state.get(f"links_pendentes_5_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.3 • PREVISÃO DE REVISÃO OBRIGATÓRIA DA PGV (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.3 - Previsão de Revisão Obrigatória da PGV", expanded=True):
                st.subheader("5.3 • Previsão de Revisão Periódica")
                st.write(
                    "**O Código Tributário Municipal ou Lei específica que tenha instituído o IPTU "
                    "prevê a revisão periódica obrigatória da Planta Genérica de Valores (PGV)?**"
                )

                # Estado inicial / persistente
                d53 = res_data.get("5.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc53 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                v_salvo_53 = d53.get("valor", "Selecione...")
                if v_salvo_53 not in opc53:
                    v_salvo_53 = "Selecione..."
                
                evidencia_53_salva = d53.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_53 = f"r53_in_{ano_sel}_fiscal"
                chave_link_53 = f"l53_in_{ano_sel}_fiscal"
                chave_coment_53 = f"coment_5.3_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_radio_53 = st.radio(
                        "Selecione uma opção (5.3):",
                        options=opc53,
                        index=opc53.index(v_salvo_53),
                        key=chave_radio_53
                    )

                with col2:
                    link_53 = st.text_area(
                        "Link/Evidência (5.3):",
                        value=evidencia_53_salva,
                        key=chave_link_53,
                        placeholder="Insira os links e evidências do dispositivo legal...",
                        height=100
                    )
                    placeholder_links_53 = st.empty()
                    links_53_visuais = re.findall(REGEX_PURE_URL, link_53 or "")
                    if links_53_visuais:
                        placeholder_links_53.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_53_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.3", res_data, sufixo="fiscal")

                # Cálculo de pontuação em tempo real
                pts_calculados_53 = 3.0 if "Sim" in val_radio_53 else 0.0

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.3", key=f"btn_salvar_5_3_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_53, v_salvo_53)
                    lnk_val = link_53.strip()
                    pts_salvar = 3.0 if "Sim" in val_salvar else 0.0

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_53, d53.get("comentarios", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="5.3",
                        valor=val_salvar,
                        pontos=pts_salvar,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.3"] = {
                        "valor": val_salvar,
                        "pontos": pts_salvar,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_53_salva or "")]

                    if lnk_val != evidencia_53_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 5.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 5.3: {pts_calculados_53:.1f} ponto(s) aplicado(s)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.3", st.session_state.get(f"links_pendentes_5_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.3.1 • INSTRUMENTO NORMATIVO DE REVISÃO DA PGV (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_3_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.3.1 - Instrumento Normativo de Revisão da PGV", expanded=True):
                st.subheader("5.3.1 • Instrumento de Revisão")
                st.write(
                    "**Informe o instrumento normativo de revisão da Planta Genérica de Valores (PGV), "
                    "Número e Data da publicação:**"
                )
                st.caption(
                    "ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*"
                )

                # Estado inicial / persistente (Pontuação fixa de 0.0)
                d531 = res_data.get("5.3.1") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_531 = d531.get("valor", "")
                evidencia_531_salva = d531.get("link", "")

                # Chaves fixas por componente e ano
                chave_texto_531 = f"t531_{ano_sel}_fiscal"
                chave_link_531 = f"l531_in_{ano_sel}_fiscal"
                chave_coment_531 = f"coment_5.3.1_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_texto_531 = st.text_input(
                        "Instrumento normativo de revisão (Nº e Data):",
                        value=v_salvo_531,
                        key=chave_texto_531,
                        placeholder="Ex: Lei Municipal nº 2.456/2023, publicada em 20/11/2023"
                    )

                with col2:
                    link_531 = st.text_area(
                        "Link/Evidência (5.3.1):",
                        value=evidencia_531_salva,
                        key=chave_link_531,
                        placeholder="Insira os links e evidências do instrumento de revisão...",
                        height=100
                    )
                    placeholder_links_531 = st.empty()
                    links_531_visuais = re.findall(REGEX_PURE_URL, link_531 or "")
                    if links_531_visuais:
                        placeholder_links_531.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_531_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.3.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.3.1", key=f"btn_salvar_5_3_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_texto_531, v_salvo_531).strip()
                    lnk_val = link_531.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_531, d531.get("comentario", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 ponto)
                    save_resp_ifiscal(
                        qid="5.3.1",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.3.1"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_531_salva or "")]

                    if lnk_val != evidencia_531_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 5.3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 5.3.1: 0,0 ponto (Quesito Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.3.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.3.1", st.session_state.get(f"links_pendentes_5_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_3_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.3.2 • PÁGINA DE DIVULGAÇÃO DA REVISÃO DA PGV (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_3_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.3.2 - Página de Divulgação da Revisão", expanded=True):
                st.subheader("5.3.2 • Divulgação Eletrônica da Revisão")
                st.write(
                    "**Informe a página eletrônica (link na internet) de divulgação do Instrumento "
                    "normativo de revisão da Planta Genérica de Valores (PGV):**"
                )
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")

                # Estado inicial / persistente (Pontuação fixa de 0.0)
                d532 = res_data.get("5.3.2") or {"valor": "", "pontos": 0.0, "link": "", "comentario": ""}
                v_salvo_532 = d532.get("valor", "")
                evidencia_532_salva = d532.get("link", "")

                # Chaves fixas por componente e ano
                chave_texto_532 = f"t532_{ano_sel}_fiscal"
                chave_link_532 = f"l532_in_{ano_sel}_fiscal"
                chave_coment_532 = f"coment_5.3.2_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_texto_532 = st.text_input(
                        "Link de divulgação da revisão (ou XYZ):",
                        value=v_salvo_532,
                        key=chave_texto_532,
                        placeholder="https://... ou XYZ"
                    )

                    # Detecta e exibe links no campo de divulgação
                    placeholder_detec_532 = st.empty()
                    links_detec_532 = re.findall(REGEX_PURE_URL, val_texto_532 or "")
                    if links_detec_532:
                        placeholder_detec_532.markdown(
                            "**🔗 Detectado no campo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_detec_532
                                ]
                            )
                        )

                with col2:
                    link_532 = st.text_area(
                        "Link/Evidência Geral (5.3.2):",
                        value=evidencia_532_salva,
                        key=chave_link_532,
                        placeholder="Insira os links e evidências complementares da divulgação...",
                        height=100
                    )
                    placeholder_links_532 = st.empty()
                    links_532_visuais = re.findall(REGEX_PURE_URL, link_532 or "")
                    if links_532_visuais:
                        placeholder_links_532.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_532_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.3.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.3.2", key=f"btn_salvar_5_3_2_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_texto_532, v_salvo_532).strip()
                    lnk_val = link_532.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_532, d532.get("comentario", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 ponto)
                    save_resp_ifiscal(
                        qid="5.3.2",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.3.2"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_532_salva or "")]

                    if lnk_val != evidencia_532_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_3_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_3_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 5.3.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 5.3.2: 0,0 ponto (Quesito Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.3.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_3_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.3.2", st.session_state.get(f"links_pendentes_5_3_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_3_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.3.3 • DATA DA ÚLTIMA REVISÃO DA PGV (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_3_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.3.3 - Data da Última Revisão", expanded=True):
                st.subheader("5.3.3 • Cronologia da Última Revisão")
                st.write("**Informe a data da última revisão da PGV:**")
                st.caption(
                    "ℹ️ *Informe a data de publicação da norma ou vigência da última atualização da Planta Genérica de Valores.*"
                )

                # Estado inicial / persistente (Pontuação fixa de 0.0)
                d533 = res_data.get("5.3.3") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_533 = d533.get("valor", "")
                evidencia_533_salva = d533.get("link", "")

                # Chaves fixas por componente e ano
                chave_texto_533 = f"t533_{ano_sel}_fiscal"
                chave_link_533 = f"l533_in_{ano_sel}_fiscal"
                chave_coment_533 = f"coment_5.3.3_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_texto_533 = st.text_input(
                        "Data da última revisão (Ex: DD/MM/AAAA):",
                        value=v_salvo_533,
                        key=chave_texto_533,
                        placeholder="Ex: 15/12/2023"
                    )

                with col2:
                    link_533 = st.text_area(
                        "Link/Evidência (5.3.3):",
                        value=evidencia_533_salva,
                        key=chave_link_533,
                        placeholder="Insira os links e evidências comprovando a data da revisão...",
                        height=100
                    )
                    placeholder_links_533 = st.empty()
                    links_533_visuais = re.findall(REGEX_PURE_URL, link_533 or "")
                    if links_533_visuais:
                        placeholder_links_533.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_533_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.3.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.3.3", key=f"btn_salvar_5_3_3_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_texto_533, v_salvo_533).strip()
                    lnk_val = link_533.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_533, d533.get("comentarios", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 ponto)
                    save_resp_ifiscal(
                        qid="5.3.3",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.3.3"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_533_salva or "")]

                    if lnk_val != evidencia_533_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_3_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_3_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 5.3.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 5.3.3: 0,0 ponto (Quesito Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.3.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_3_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.3.3", st.session_state.get(f"links_pendentes_5_3_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_3_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.3.4 • PERIODICIDADE EM ANOS DA PGV (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_3_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.3.4 - Periodicidade em Anos", expanded=True):
                st.subheader("5.3.4 • Periodicidade Estabelecida")
                st.write("**Informe a periodicidade de revisão da PGV (em anos):**")
                st.caption(
                    "ℹ️ *Indique o intervalo em anos previsto em legislação para a realização da revisão da PGV (digite 0 caso não haja previsão).* "
                )

                # Estado inicial / persistente (Pontuação fixa de 0.0)
                d534 = res_data.get("5.3.4") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": ""}
                
                # Tratamento seguro para inicialização do valor numérico
                try:
                    periodicidade_inicial = int(d534.get("valor", 0))
                except (ValueError, TypeError):
                    periodicidade_inicial = 0

                evidencia_534_salva = d534.get("link", "")

                # Chaves fixas por componente e ano
                chave_num_534 = f"num_534_{ano_sel}_fiscal"
                chave_link_534 = f"l534_in_{ano_sel}_fiscal"
                chave_coment_534 = f"coment_5.3.4_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_num_534 = st.number_input(
                        "Periodicidade em anos:",
                        value=periodicidade_inicial,
                        min_value=0,
                        step=1,
                        key=chave_num_534
                    )

                with col2:
                    link_534 = st.text_area(
                        "Link/Evidência (5.3.4):",
                        value=evidencia_534_salva,
                        key=chave_link_534,
                        placeholder="Insira os links e evidências comprovando a periodicidade legal...",
                        height=100
                    )
                    placeholder_links_534 = st.empty()
                    links_534_visuais = re.findall(REGEX_PURE_URL, link_534 or "")
                    if links_534_visuais:
                        placeholder_links_534.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_534_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.3.4", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.3.4", key=f"btn_salvar_5_3_4_{ano_sel}", type="primary"):
                    val_num_obtido = st.session_state.get(chave_num_534, periodicidade_inicial)
                    val_salvar = str(val_num_obtido)
                    lnk_val = link_534.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_534, d534.get("comentarios", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 ponto)
                    save_resp_ifiscal(
                        qid="5.3.4",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.3.4"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_534_salva or "")]

                    if lnk_val != evidencia_534_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_3_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_3_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 5.3.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 5.3.4: 0,0 ponto (Quesito Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.3.4 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_3_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.3.4", st.session_state.get(f"links_pendentes_5_3_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_3_4_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 5.4 • INTEGRAÇÃO COM BASE DO IPTU (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_5_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 5.4 - Integração com Base do IPTU", expanded=True):
                st.subheader("5.4 • Atualização da Base de Cálculo")
                st.write(
                    "**Os dados da Planta Genérica de Valores (PGV) e do Cadastro Imobiliário "
                    "atualizam a base de cálculo do IPTU?**"
                )

                # Estado inicial / persistente
                d54 = res_data.get("5.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc54 = [
                    "Selecione...",
                    "Sim, de forma automática no sistema – 06",
                    "Sim, de forma manual – 02",
                    "Não – 00"
                ]

                v_salvo_54 = d54.get("valor", "Selecione...")
                if v_salvo_54 not in opc54:
                    v_salvo_54 = "Selecione..."

                evidencia_54_salva = d54.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_54 = f"r54_in_{ano_sel}_fiscal"
                chave_link_54 = f"l54_in_{ano_sel}_fiscal"
                chave_coment_54 = f"coment_5.4_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_radio_54 = st.radio(
                        "Selecione uma opção (5.4):",
                        options=opc54,
                        index=opc54.index(v_salvo_54),
                        key=chave_radio_54
                    )

                with col2:
                    link_54 = st.text_area(
                        "Link/Evidência (5.4):",
                        value=evidencia_54_salva,
                        key=chave_link_54,
                        placeholder="Insira os links e evidências do processo de atualização...",
                        height=100
                    )
                    placeholder_links_54 = st.empty()
                    links_54_visuais = re.findall(REGEX_PURE_URL, link_54 or "")
                    if links_54_visuais:
                        placeholder_links_54.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_54_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("5.4", res_data, sufixo="fiscal")

                # Cálculo de pontuação em tempo real
                if "automática" in val_radio_54:
                    pts_calculados_54 = 6.0
                elif "manual" in val_radio_54:
                    pts_calculados_54 = 2.0
                else:
                    pts_calculados_54 = 0.0

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 5.4", key=f"btn_salvar_5_4_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_54, v_salvo_54)
                    lnk_val = link_54.strip()

                    if "automática" in val_salvar:
                        pts_salvar = 6.0
                    elif "manual" in val_salvar:
                        pts_salvar = 2.0
                    else:
                        pts_salvar = 0.0

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_54, d54.get("comentarios", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="5.4",
                        valor=val_salvar,
                        pontos=pts_salvar,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["5.4"] = {
                        "valor": val_salvar,
                        "pontos": pts_salvar,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_54_salva or "")]

                    if lnk_val != evidencia_54_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_5_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_5_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 5.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 5.4: {pts_calculados_54:.1f} ponto(s) aplicado(s)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 5.4 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_5_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("5.4", st.session_state.get(f"links_pendentes_5_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_4_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 6.0 • CRITÉRIOS DE ALÍQUOTA DO IPTU (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_6_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 6.0 - Critérios de Alíquota do IPTU", expanded=True):
                st.subheader("6.0 • Critérios de Cobrança do IPTU")
                st.write(
                    "**Sobre a alíquota do IPTU, quais critérios o município instituiu "
                    "para a cobrança do imposto? (Checklist)**"
                )

                # Busca e sanitiza dados anteriores do banco
                d60 = res_data.get("6.0") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                evidencia_60_salva = d60.get("link", "")

                try:
                    val_banco = d60.get("valor", "[]").replace("'", '"')
                    sel60 = json.loads(val_banco)
                    if not isinstance(sel60, list):
                        sel60 = []
                except Exception:
                    sel60 = []

                opcoes_tela_60 = [
                    "Alíquotas progressivas em razão do valor do imóvel – 01",
                    "Alíquotas diferenciadas em razão da localização do imóvel – 0,5",
                    "Alíquotas diferenciadas em razão do uso do imóvel – 0,5",
                    "Outros – 00",
                    "Não há diferenciação nas alíquotas dos imóveis – -01 (perde 01 ponto)"
                ]

                # Chaves fixas por componente e ano
                chave_link_60 = f"txt_60_{ano_sel}_fiscal"
                chave_coment_60 = f"coment_6.0_{ano_sel}_fiscal"

                # Layout de exibição dos Checkboxes (Duas colunas)
                c1, c2 = st.columns([1, 1])
                res60_selecionados = []

                for idx, opcao in enumerate(opcoes_tela_60):
                    target_col = c1 if idx % 2 == 0 else c2
                    with target_col:
                        pode_marcar = opcao in sel60
                        marcado = st.checkbox(
                            opcao,
                            value=pode_marcar,
                            key=f"chk_60_{idx}_{ano_sel}_fiscal"
                        )
                        if marcado:
                            res60_selecionados.append(opcao)

                # Lógica excludente: se marcou 'Não há diferenciação', prevalece isoladamente
                opc_penalidade = "Não há diferenciação nas alíquotas dos imóveis – -01 (perde 01 ponto)"
                if opc_penalidade in res60_selecionados:
                    res60_selecionados = [opc_penalidade]

                # Cálculo de pontuação em tempo real para exibição
                pts_calculados_60 = 0.0
                if opc_penalidade in res60_selecionados:
                    pts_calculados_60 = -1.0
                else:
                    for item in res60_selecionados:
                        if "progressivas" in item:
                            pts_calculados_60 += 1.0
                        elif "localização" in item:
                            pts_calculados_60 += 0.5
                        elif "uso" in item:
                            pts_calculados_60 += 0.5

                st.markdown("---")

                # Campo de Entrada de Link/Evidência
                link_60 = st.text_area(
                    "Link/Evidência (Legislação das Alíquotas do IPTU - 6.0):",
                    value=evidencia_60_salva,
                    key=chave_link_60,
                    placeholder="Insira os links e evidências da legislação municipal...",
                    height=100
                )

                placeholder_links_60 = st.empty()
                links_60_visuais = re.findall(REGEX_PURE_URL, link_60 or "")
                if links_60_visuais:
                    placeholder_links_60.markdown(
                        "**🔗 Ativos (Evidência 6.0):** "
                        + " | ".join(
                            [
                                f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                for u in links_60_visuais
                            ]
                        )
                    )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("6.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 6.0", key=f"btn_salvar_6_0_{ano_sel}", type="primary"):
                    # Coleta atualizada dos checkboxes no momento do clique
                    res60_final = []
                    for idx_c, opc_c in enumerate(opcoes_tela_60):
                        if st.session_state.get(f"chk_60_{idx_c}_{ano_sel}_fiscal", False):
                            res60_final.append(opc_c)

                    if opc_penalidade in res60_final:
                        res60_final = [opc_penalidade]

                    # Recálculo final dos pontos
                    pts_final_60 = 0.0
                    if opc_penalidade in res60_final:
                        pts_final_60 = -1.0
                    else:
                        for item in res60_final:
                            if "progressivas" in item:
                                pts_final_60 += 1.0
                            elif "localização" in item:
                                pts_final_60 += 0.5
                            elif "uso" in item:
                                pts_final_60 += 0.5

                    lnk_val_60 = link_60.strip()
                    valor_json_60 = json.dumps(res60_final)

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_60, d60.get("comentarios", ""))

                    # Salva no banco de dados Neon
                    save_resp_ifiscal(
                        qid="6.0",
                        valor=valor_json_60,
                        pontos=pts_final_60,
                        link=lnk_val_60,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["6.0"] = {
                        "valor": valor_json_60,
                        "pontos": pts_final_60,
                        "link": lnk_val_60,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_60 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_60_salva or "")]

                    if lnk_val_60 != evidencia_60_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_6_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 6.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 6.0: {pts_calculados_60:.1f} ponto(s) aplicado(s)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 6.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.0 • PROGRAMA DE ISENÇÃO DO IPTU (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_7_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.0 - Programa de Isenção do IPTU", expanded=True):
                st.subheader("7.0 • Programa de Isenção")
                st.write("**O município adotou programa de isenção do IPTU?**")
                st.caption("ℹ️ *Indique se há programa regulamentado de isenção do IPTU no município.*")

                # Estado inicial / persistente (Pontuação fixa de 0.0)
                d70 = res_data.get("7.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc70 = ["Selecione...", "Sim", "Não"]

                v_salvo_70 = d70.get("valor", "Selecione...")
                if v_salvo_70 not in opc70:
                    v_salvo_70 = "Selecione..."

                evidencia_70_salva = d70.get("link", "")

                # Chaves fixas por componente e ano
                chave_radio_70 = f"r70_in_{ano_sel}_fiscal"
                chave_link_70 = f"l70_in_{ano_sel}_fiscal"
                chave_coment_70 = f"coment_7.0_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_radio_70 = st.radio(
                        "Selecione uma opção (7.0):",
                        options=opc70,
                        index=opc70.index(v_salvo_70),
                        key=chave_radio_70
                    )

                with col2:
                    link_70 = st.text_area(
                        "Link/Evidência Geral (7.0):",
                        value=evidencia_70_salva,
                        key=chave_link_70,
                        placeholder="Insira os links e evidências do programa de isenção...",
                        height=100
                    )
                    placeholder_links_70 = st.empty()
                    links_70_visuais = re.findall(REGEX_PURE_URL, link_70 or "")
                    if links_70_visuais:
                        placeholder_links_70.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_70_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("7.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.0", key=f"btn_salvar_7_0_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_radio_70, v_salvo_70)
                    lnk_val = link_70.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_70, d70.get("comentarios", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 ponto)
                    save_resp_ifiscal(
                        qid="7.0",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["7.0"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_70_salva or "")]

                    if lnk_val != evidencia_70_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 7.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 7.0: 0,0 ponto (Quesito Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 7.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.0", st.session_state.get(f"links_pendentes_7_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.1 • REGULAMENTAÇÃO DO PROGRAMA DE ISENÇÃO (MODELO PADRONIZADO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_7_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.1 - Regulamentação do Programa de Isenção", expanded=True):
                st.subheader("7.1 • Instrumento de Regulamentação")
                st.write("**Informe o instrumento normativo de regulamentação do programa de isenção do IPTU, Número e Data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")

                # Estado inicial / persistente (Pontuação fixa de 0.0)
                d71 = res_data.get("7.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_71 = d71.get("valor", "")
                evidencia_71_salva = d71.get("link", "")

                # Chaves fixas por componente e ano
                chave_txt_71 = f"txt_71_val_{ano_sel}_fiscal"
                chave_link_71 = f"l71_in_{ano_sel}_fiscal"
                chave_coment_71 = f"coment_7.1_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    val_txt_71 = st.text_input(
                        "Instrumento normativo (Nº e Data):",
                        value=v_salvo_71,
                        key=chave_txt_71,
                        placeholder="Ex: Lei Municipal nº 1.234/2020 de 15/03/2020"
                    )

                with col2:
                    link_71 = st.text_area(
                        "Link/Evidência (7.1):",
                        value=evidencia_71_salva,
                        key=chave_link_71,
                        placeholder="Insira os links e evidências da regulamentação...",
                        height=100
                    )
                    placeholder_links_71 = st.empty()
                    links_71_visuais = re.findall(REGEX_PURE_URL, link_71 or "")
                    if links_71_visuais:
                        placeholder_links_71.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_71_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários dentro do expander
                bloco_comentarios_ifiscal("7.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.1", key=f"btn_salvar_7_1_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_txt_71, v_salvo_71).strip()
                    lnk_val = link_71.strip()

                    # Captura o comentário atual do session_state
                    comentario_para_salvar = st.session_state.get(chave_coment_71, d71.get("comentarios", ""))

                    # Salva no banco de dados Neon (Item informativo: 0.0 ponto)
                    save_resp_ifiscal(
                        qid="7.1",
                        valor=val_salvar,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o dicionário local res_data
                    res_data["7.1"] = {
                        "valor": val_salvar,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Validação de novos links para acionar o modal
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_71_salva or "")]

                    if lnk_val != evidencia_71_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 7.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Resumo dinâmico e impacto de pontuação
                st.markdown(
                    "<span style='color:#6c757d; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 7.1: 0,0 ponto (Quesito Informativo)</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 7.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.1", st.session_state.get(f"links_pendentes_7_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.2 • DIVULGAÇÃO ELETRÔNICA DA REGULAMENTAÇÃO (PADRÃO iGov/iFiscal)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_7_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.2 - Página de Divulgação da Isenção", expanded=True):
                st.subheader("7.2 • Divulgação Eletrônica da Regulamentação")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do Instrumento normativo de regulamentação do programa de isenção do IPTU:**")
                st.caption("⚠️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")

                # Estado inicial / persistente
                d72 = res_data.get("7.2") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_72 = d72.get("valor", "")
                evidencia_72_salva = d72.get("link", "")

                # Chaves padronizadas por componente e ano
                chave_txt_72 = f"txt_72_val_{ano_sel}_fiscal"
                chave_link_72 = f"l72_in_{ano_sel}_fiscal"
                chave_coment_72 = f"coment_7.2_{ano_sel}_fiscal"

                col1, col2 = st.columns([1, 1])
                with col1:
                    v_input_72 = st.text_input(
                        "Link de divulgação da isenção (ou XYZ):",
                        value=v_salvo_72,
                        key=chave_txt_72,
                        placeholder="https://... ou XYZ"
                    )
                    
                    # Detecção visual no próprio campo de input
                    lk_detec_72 = re.findall(REGEX_PURE_URL, v_input_72 or "")
                    if lk_detec_72:
                        st.markdown(
                            "**🔗 Detectado no campo:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in lk_detec_72
                                ]
                            )
                        )

                with col2:
                    link_72 = st.text_area(
                        "Link/Evidência Geral (7.2):",
                        value=evidencia_72_salva,
                        key=chave_link_72,
                        placeholder="Insira os links e evidências gerais...",
                        height=100
                    )
                    placeholder_links_72 = st.empty()
                    links_72_visuais = re.findall(REGEX_PURE_URL, link_72 or "")
                    if links_72_visuais:
                        placeholder_links_72.markdown(
                            "**🔗 Ativos:** "
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                    for u in links_72_visuais
                                ]
                            )
                        )

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("7.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.2", key=f"btn_salvar_7_2_{ano_sel}", type="primary"):
                    val_salvar = st.session_state.get(chave_txt_72, v_salvo_72).strip()
                    lnk_val = link_72.strip()

                    # Regra de cálculo de pontuação (-3.0 para XYZ, caso contrário 0.0)
                    pts72_nova = -3.0 if val_salvar.upper() == "XYZ" else 0.0

                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_72, d72.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="7.2",
                        valor=val_salvar,
                        pontos=float(pts72_nova),
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["7.2"] = {
                        "valor": val_salvar,
                        "pontos": float(pts72_nova),
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_72_salva or "")]

                    if lnk_val != evidencia_72_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 7.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_72 = d72.get("pontos", 0.0)
                cor_status_72 = "#dc3545" if pts_exibido_72 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_status_72}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 7.2: {pts_exibido_72:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 7.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.2", st.session_state.get(f"links_pendentes_7_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 7.3 • TOTALMENTE INDEPENDENTE (CHECKLIST)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_7_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 7.3 - Critérios Estabelecidos para Isenção", expanded=True):
                st.subheader("7.3 • Critérios de Concessão de Isenção")
                st.write("**Assinale os critérios estabelecidos para a concessão de isenção total ou parcial do IPTU: (Checklist)**")
                
                # Estado inicial / persistente
                d73 = res_data.get("7.3") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                evidencia_73_salva = d73.get("link", "")
                
                # Carregamento seguro da lista de opções previamente marcadas
                try:
                    val_banco73 = d73.get("valor", "[]").replace("'", '"')
                    sel73 = json.loads(val_banco73)
                    if not isinstance(sel73, list): 
                        sel73 = []
                except:
                    sel73 = []

                opc73 = [
                    "Aposentado, pensionista ou beneficiário de renda mensal vitalícia",
                    "Não possuir outro imóvel",
                    "Utilizar o único imóvel como residência",
                    "Rendimento mensal máximo",
                    "Valor venal máximo do imóvel",
                    "Outros"
                ]

                # Renderização dos Checkboxes em 2 colunas
                c3, c4 = st.columns([1, 1])
                for idx, opcao in enumerate(opc73):
                    target_col = c3 if idx % 2 == 0 else c4
                    with target_col:
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel73), 
                            key=f"chk_73_{idx}_{ano_sel}_fiscal"
                        )

                st.markdown("---")
                
                # Chaves padronizadas
                chave_link_73 = f"l73_in_{ano_sel}_fiscal"
                chave_coment_73 = f"coment_7.3_{ano_sel}_fiscal"
                
                link_73 = st.text_area(
                    "Link/Evidência (7.3):",
                    value=evidencia_73_salva,
                    key=chave_link_73,
                    placeholder="Insira os links e evidências gerais...",
                    height=100
                )
                
                # Detecção visual de links no campo
                placeholder_links_73 = st.empty()
                links_73_visuais = re.findall(REGEX_PURE_URL, link_73 or "")
                if links_73_visuais:
                    placeholder_links_73.markdown(
                        "**🔗 Ativos:** "
                        + " | ".join(
                            [
                                f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})"
                                for u in links_73_visuais
                            ]
                        )
                    )

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("7.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 7.3", key=f"btn_salvar_7_3_{ano_sel}", type="primary"):
                    # Coleta os checkboxes que estão marcados no momento do clique
                    res73_atual = []
                    for idx_c, opc_c in enumerate(opc73):
                        if st.session_state.get(f"chk_73_{idx_c}_{ano_sel}_fiscal", False):
                            res73_atual.append(opc_c)
                    
                    val_salvar_json = json.dumps(res73_atual)
                    lnk_val = link_73.strip()

                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_73, d73.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="7.3",
                        valor=val_salvar_json,
                        pontos=0.0,
                        link=lnk_val,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["7.3"] = {
                        "valor": val_salvar_json,
                        "pontos": 0.0,
                        "link": lnk_val,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_73_salva or "")]

                    if lnk_val != evidencia_73_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_7_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_7_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 7.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_73 = d73.get("pontos", 0.0)
                cor_status_73 = "#28a745" # Sempre verde pois não tem penalidade
                st.markdown(
                    f"<span style='color:{cor_status_73}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 7.3: {pts_exibido_73:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 7.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_7_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("7.3", st.session_state.get(f"links_pendentes_7_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_7_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_8_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.0 - Instituição do ISSQN", expanded=True):
                st.subheader("8.0 • Instituição do ISSQN")
                st.write("**O Imposto sobre Serviços de Qualquer Natureza (ISSQN) foi instituído no município?**")
                
                # Estado inicial / persistente
                d80 = res_data.get("8.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc80 = ["Selecione...", "Sim – 01", "Não – 00"]
                
                v_salvo_80 = d80.get("valor", "Selecione...")
                if v_salvo_80 not in opc80: 
                    v_salvo_80 = "Selecione..."
                
                evidencia_80_salva = d80.get("link", "")

                # Chaves padronizadas
                chave_rad_80 = f"rad_80_{ano_sel}_fiscal"
                chave_link_80 = f"l80_in_{ano_sel}_fiscal"
                chave_coment_80 = f"coment_8.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio(
                        "Selecione 8.0:", 
                        opc80, 
                        index=opc80.index(v_salvo_80), 
                        key=chave_rad_80
                    )
                with c2: 
                    link_80 = st.text_area(
                        "Link/Evidência (8.0):", 
                        value=evidencia_80_salva, 
                        key=chave_link_80, 
                        placeholder="Insira os links e evidências gerais...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_80 = st.empty()
                    links_80_visuais = re.findall(REGEX_PURE_URL, link_80 or "")
                    if links_80_visuais: 
                        placeholder_links_80.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_80_visuais
                                ]
                            )
                        )
                
                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("8.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.0", key=f"btn_salvar_8_0_{ano_sel}", type="primary"):
                    val_sel_80 = st.session_state.get(chave_rad_80, v_salvo_80)
                    lnk_val_80 = link_80.strip()
                    
                    # Regra de Pontuação: 1.0 para "Sim", 0.0 caso contrário
                    pts80_nova = 1.0 if "Sim" in val_sel_80 else 0.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_80, d80.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="8.0",
                        valor=val_sel_80,
                        pontos=float(pts80_nova),
                        link=lnk_val_80,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["8.0"] = {
                        "valor": val_sel_80,
                        "pontos": float(pts80_nova),
                        "link": lnk_val_80,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_80 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_80_salva or "")]

                    if lnk_val_80 != evidencia_80_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 8.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_80 = d80.get("pontos", 0.0)
                cor_status_80 = "#28a745" if pts_exibido_80 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_status_80}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 8.0: {pts_exibido_80:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 8.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.0", st.session_state.get(f"links_pendentes_8_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_8_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.1 - Atualização da Legislação do ISSQN", expanded=True):
                st.subheader("8.1 • Atualização Normativa (LC 157/2016)")
                st.write("**O Município atualizou sua legislação conforme as novas hipóteses de incidência de ISS (LC 157/2016)?**")
                
                # Estado inicial / persistente
                d81 = res_data.get("8.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc81 = ["Selecione...", "Sim – 02", "Não – 00"]
                
                v_salvo_81 = d81.get("valor", "Selecione...")
                if v_salvo_81 not in opc81: 
                    v_salvo_81 = "Selecione..."
                
                evidencia_81_salva = d81.get("link", "")

                # Chaves padronizadas
                chave_rad_81 = f"rad_81_{ano_sel}_fiscal"
                chave_link_81 = f"l81_in_{ano_sel}_fiscal"
                chave_coment_81 = f"coment_8.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio(
                        "Selecione 8.1:", 
                        opc81, 
                        index=opc81.index(v_salvo_81), 
                        key=chave_rad_81
                    )
                with c2: 
                    link_81 = st.text_area(
                        "Link/Evidência (8.1):", 
                        value=evidencia_81_salva, 
                        key=chave_link_81, 
                        placeholder="Insira os links e evidências gerais...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_81 = st.empty()
                    links_81_visuais = re.findall(REGEX_PURE_URL, link_81 or "")
                    if links_81_visuais: 
                        placeholder_links_81.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_81_visuais
                                ]
                            )
                        )
                
                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("8.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.1", key=f"btn_salvar_8_1_{ano_sel}", type="primary"):
                    val_sel_81 = st.session_state.get(chave_rad_81, v_salvo_81)
                    lnk_val_81 = link_81.strip()
                    
                    # Regra de Pontuação: 2.0 para "Sim", 0.0 caso contrário
                    pts81_nova = 2.0 if "Sim" in val_sel_81 else 0.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_81, d81.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="8.1",
                        valor=val_sel_81,
                        pontos=float(pts81_nova),
                        link=lnk_val_81,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["8.1"] = {
                        "valor": val_sel_81,
                        "pontos": float(pts81_nova),
                        "link": lnk_val_81,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_81 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_81_salva or "")]

                    if lnk_val_81 != evidencia_81_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 8.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_81 = d81.get("pontos", 0.0)
                cor_status_81 = "#28a745" if pts_exibido_81 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_status_81}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 8.1: {pts_exibido_81:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 8.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.1", st.session_state.get(f"links_pendentes_8_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_8_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.2 - Rotina de Fiscalização do ISSQN", expanded=True):
                st.subheader("8.2 • Mecanismos de Combate à Sonegação")
                st.write("**Houve rotina de fiscalização para detectar contribuintes que deixaram de emitir a Nota Fiscal de Serviços por determinado período ou que apresentaram queda acentuada em suas operações, a fim de detectar o fim das atividades ou a sonegação do ISSQN?**")
                
                # Estado inicial / persistente
                d82 = res_data.get("8.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc82 = ["Selecione...", "Sim por meio de sistema automatizado – 15", "Sim, manualmente – 08", "Não – 00"]
                
                v_salvo_82 = d82.get("valor", "Selecione...")
                if v_salvo_82 not in opc82: 
                    v_salvo_82 = "Selecione..."
                
                evidencia_82_salva = d82.get("link", "")

                # Chaves padronizadas
                chave_rad_82 = f"rad_82_{ano_sel}_fiscal"
                chave_link_82 = f"l82_in_{ano_sel}_fiscal"
                chave_coment_82 = f"coment_8.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio(
                        "Selecione 8.2:", 
                        opc82, 
                        index=opc82.index(v_salvo_82), 
                        key=chave_rad_82
                    )
                with c2: 
                    link_82 = st.text_area(
                        "Link/Evidência (8.2):", 
                        value=evidencia_82_salva, 
                        key=chave_link_82, 
                        placeholder="Insira os links e evidências gerais...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_82 = st.empty()
                    links_82_visuais = re.findall(REGEX_PURE_URL, link_82 or "")
                    if links_82_visuais: 
                        placeholder_links_82.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_82_visuais
                                ]
                            )
                        )
                
                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("8.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.2", key=f"btn_salvar_8_2_{ano_sel}", type="primary"):
                    val_sel_82 = st.session_state.get(chave_rad_82, v_salvo_82)
                    lnk_val_82 = link_82.strip()
                    
                    # Regra de Pontuação: 15.0 para automatizado, 8.0 para manualmente, 0.0 caso contrário
                    pts82_nova = 15.0 if "automatizado" in val_sel_82 else (8.0 if "manualmente" in val_sel_82 else 0.0)
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_82, d82.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="8.2",
                        valor=val_sel_82,
                        pontos=float(pts82_nova),
                        link=lnk_val_82,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["8.2"] = {
                        "valor": val_sel_82,
                        "pontos": float(pts82_nova),
                        "link": lnk_val_82,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_82 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_82_salva or "")]

                    if lnk_val_82 != evidencia_82_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 8.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_82 = d82.get("pontos", 0.0)
                cor_status_82 = "#28a745" if pts_exibido_82 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_status_82}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 8.2: {pts_exibido_82:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 8.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.2", st.session_state.get(f"links_pendentes_8_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 8.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_8_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 8.3 - Autenticidade de Notas Fiscais", expanded=True):
                st.subheader("8.3 • Acesso Público à Consulta de NFS-e")
                st.write("**A pesquisa de autenticidade de notas fiscais eletrônicas está disponível ao público?**")
                
                # Estado inicial / persistente
                d83 = res_data.get("8.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc83 = [
                    "Selecione...",
                    "Sim, sem restrição – 00", 
                    "Sim, com restrição (Ex.: há necessidade de cadastro para acessar o resultado da pesquisa) – -09 (perde 09 pontos)", 
                    "Serviço não disponibilizado – -15", 
                    "Não implantou a NFS-e – -15"
                ]
                
                v_salvo_83 = d83.get("valor", "Selecione...")
                if v_salvo_83 not in opc83: 
                    v_salvo_83 = "Selecione..."
                
                evidencia_83_salva = d83.get("link", "")

                # Chaves padronizadas
                chave_rad_83 = f"rad_83_{ano_sel}_fiscal"
                chave_link_83 = f"l83_in_{ano_sel}_fiscal"
                chave_coment_83 = f"coment_8.3_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio(
                        "Selecione 8.3:", 
                        opc83, 
                        index=opc83.index(v_salvo_83), 
                        key=chave_rad_83
                    )
                with c2: 
                    link_83 = st.text_area(
                        "Link/Evidência (8.3):", 
                        value=evidencia_83_salva, 
                        key=chave_link_83, 
                        placeholder="Insira os links e evidências gerais...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_83 = st.empty()
                    links_83_visuais = re.findall(REGEX_PURE_URL, link_83 or "")
                    if links_83_visuais: 
                        placeholder_links_83.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_83_visuais
                                ]
                            )
                        )
                
                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("8.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 8.3", key=f"btn_salvar_8_3_{ano_sel}", type="primary"):
                    val_sel_83 = st.session_state.get(chave_rad_83, v_salvo_83)
                    lnk_val_83 = link_83.strip()
                    
                    # Regra de Cálculo de Pontuação
                    if val_sel_83 == "Sim, sem restrição – 00" or val_sel_83 == "Selecione...":
                        pts83_nova = 0.0
                    elif "com restrição" in val_sel_83:
                        pts83_nova = -9.0
                    else:
                        pts83_nova = -15.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_83, d83.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="8.3",
                        valor=val_sel_83,
                        pontos=float(pts83_nova),
                        link=lnk_val_83,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["8.3"] = {
                        "valor": val_sel_83,
                        "pontos": float(pts83_nova),
                        "link": lnk_val_83,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_83 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_83_salva or "")]

                    if lnk_val_83 != evidencia_83_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_8_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_8_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 8.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_83 = d83.get("pontos", 0.0)
                cor_status_83 = "#dc3545" if pts_exibido_83 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_status_83}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 8.3: {pts_exibido_83:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 8.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_8_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("8.3", st.session_state.get(f"links_pendentes_8_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_8_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 9.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_9_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 9.0 - Regulamentação do ITBI", expanded=True):
                st.subheader("9.0 • Regulamentação do ITBI")
                st.write("**O Imposto sobre Transmissão de Bens Imóveis (ITBI) foi regulamentado?**")
                
                # Estado inicial / persistente
                d90 = res_data.get("9.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc90 = ["Selecione...", "Sim", "Não"]
                
                v_salvo_90 = d90.get("valor", "Selecione...")
                if v_salvo_90 not in opc90: 
                    v_salvo_90 = "Selecione..."
                
                evidencia_90_salva = d90.get("link", "")

                # Chaves padronizadas
                chave_rad_90 = f"rad_90_{ano_sel}_fiscal"
                chave_link_90 = f"l90_in_{ano_sel}_fiscal"
                chave_coment_90 = f"coment_9.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 9.0:", 
                        opc90, 
                        index=opc90.index(v_salvo_90), 
                        key=chave_rad_90
                    )
                with c2:
                    link_90 = st.text_area(
                        "Link/Evidência Geral (9.0):", 
                        value=evidencia_90_salva, 
                        key=chave_link_90, 
                        placeholder="Insira os links e evidências gerais...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_90 = st.empty()
                    links_90_visuais = re.findall(REGEX_PURE_URL, link_90 or "")
                    if links_90_visuais: 
                        placeholder_links_90.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_90_visuais
                                ]
                            )
                        )
                
                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("9.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 9.0", key=f"btn_salvar_9_0_{ano_sel}", type="primary"):
                    val_sel_90 = st.session_state.get(chave_rad_90, v_salvo_90)
                    lnk_val_90 = link_90.strip()
                    
                    # Regra de Pontuação (Informativo - 0.0)
                    pts90_nova = 0.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_90, d90.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="9.0",
                        valor=val_sel_90,
                        pontos=float(pts90_nova),
                        link=lnk_val_90,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["9.0"] = {
                        "valor": val_sel_90,
                        "pontos": float(pts90_nova),
                        "link": lnk_val_90,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_90 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_90_salva or "")]

                    if lnk_val_90 != evidencia_90_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 9.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_90 = d90.get("pontos", 0.0)
                cor_status_90 = "#28a745"
                st.markdown(
                    f"<span style='color:{cor_status_90}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 9.0: {pts_exibido_90:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 9.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.0", st.session_state.get(f"links_pendentes_9_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 9.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_9_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 9.1 - Instrumento Normativo do ITBI", expanded=True):
                st.subheader("9.1 • Instrumento de Regulamentação")
                st.write("**Informe o instrumento normativo de regulamentação do ITBI, Número e Data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")
                
                # Estado inicial / persistente
                d91 = res_data.get("9.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_91 = d91.get("valor", "")
                evidencia_91_salva = d91.get("link", "")

                # Chaves padronizadas
                chave_txt_91 = f"txt_91_val_{ano_sel}_fiscal"
                chave_link_91 = f"l91_in_{ano_sel}_fiscal"
                chave_coment_91 = f"coment_9.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Instrumento normativo do ITBI (Nº e Data):", 
                        value=v_salvo_91, 
                        key=chave_txt_91
                    )
                with c2:
                    link_91 = st.text_area(
                        "Link/Evidência (9.1):", 
                        value=evidencia_91_salva, 
                        key=chave_link_91, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_91 = st.empty()
                    links_91_visuais = re.findall(REGEX_PURE_URL, link_91 or "")
                    if links_91_visuais: 
                        placeholder_links_91.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_91_visuais
                                ]
                            )
                        )
                
                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("9.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 9.1", key=f"btn_salvar_9_1_{ano_sel}", type="primary"):
                    val_sel_91 = st.session_state.get(chave_txt_91, v_salvo_91).strip()
                    lnk_val_91 = link_91.strip()
                    
                    # Regra de Pontuação (Informativo - 0.0)
                    pts91_nova = 0.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_91, d91.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="9.1",
                        valor=val_sel_91,
                        pontos=float(pts91_nova),
                        link=lnk_val_91,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["9.1"] = {
                        "valor": val_sel_91,
                        "pontos": float(pts91_nova),
                        "link": lnk_val_91,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_91 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_91_salva or "")]

                    if lnk_val_91 != evidencia_91_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 9.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_91 = d91.get("pontos", 0.0)
                cor_status_91 = "#28a745"
                st.markdown(
                    f"<span style='color:{cor_status_91}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 9.1: {pts_exibido_91:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 9.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.1", st.session_state.get(f"links_pendentes_9_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 9.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_9_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 9.2 - Página de Divulgação do ITBI", expanded=True):
                st.subheader("9.2 • Divulgação Eletrônica da Regulamentação")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da regulamentação do ITBI:**")
                st.caption("⚠️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                # Estado inicial / persistente
                d92 = res_data.get("9.2") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_92 = d92.get("valor", "")
                evidencia_92_salva = d92.get("link", "")

                # Chaves padronizadas
                chave_txt_92 = f"txt_92_val_{ano_sel}_fiscal"
                chave_link_92 = f"l92_in_{ano_sel}_fiscal"
                chave_coment_92 = f"coment_9.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    v_input_92 = st.text_input(
                        "Link de divulgação do ITBI (ou XYZ):", 
                        value=v_salvo_92, 
                        key=chave_txt_92
                    )
                    
                    # Detecção visual de links no campo de texto
                    lk_detec_92 = re.findall(REGEX_PURE_URL, v_input_92 or "")
                    if lk_detec_92: 
                        st.markdown(
                            "**🔗 Detectado no campo:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in lk_detec_92
                                ]
                            )
                        )

                with c2:
                    link_92 = st.text_area(
                        "Link/Evidência Geral (9.2):", 
                        value=evidencia_92_salva, 
                        key=chave_link_92, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo de evidências
                    placeholder_links_92 = st.empty()
                    links_92_visuais = re.findall(REGEX_PURE_URL, link_92 or "")
                    if links_92_visuais: 
                        placeholder_links_92.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_92_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("9.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 9.2", key=f"btn_salvar_9_2_{ano_sel}", type="primary"):
                    val_sel_92 = st.session_state.get(chave_txt_92, v_salvo_92).strip()
                    lnk_val_92 = link_92.strip()
                    
                    # Regra de Pontuação (-3.0 para XYZ, 0.0 caso contrário)
                    pts92_nova = -3.0 if val_sel_92.upper() == "XYZ" else 0.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_92, d92.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="9.2",
                        valor=val_sel_92,
                        pontos=float(pts92_nova),
                        link=lnk_val_92,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["9.2"] = {
                        "valor": val_sel_92,
                        "pontos": float(pts92_nova),
                        "link": lnk_val_92,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_92 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_92_salva or "")]

                    if lnk_val_92 != evidencia_92_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 9.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_92 = d92.get("pontos", 0.0)
                cor_status_92 = "#dc3545" if pts_exibido_92 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_status_92}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 9.2: {pts_exibido_92:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 9.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.2", st.session_state.get(f"links_pendentes_9_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 9.3 • TOTALMENTE INDEPENDENTE (CHECKLIST)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_9_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 9.3 - Registro e Emissão da Guia do ITBI", expanded=True):
                st.subheader("9.3 • Emissão de Guia de Recolhimento")
                st.write("**Assinale a forma de registro e emissão da guia de recolhimento do ITBI: (Checklist)**")
                st.caption("🚨 *Nota: A mera impressão da guia de recolhimento do ITBI não é considerada forma de emissão.*")
                
                # Estado inicial / persistente
                d93 = res_data.get("9.3") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                evidencia_93_salva = d93.get("link", "")
                
                # Leitura segura da lista em JSON vinda do banco
                try:
                    val_banco93 = (d93.get("valor") or "[]").replace("'", '"')
                    sel93 = json.loads(val_banco93)
                    if not isinstance(sel93, list): 
                        sel93 = []
                except Exception:
                    sel93 = []

                opc93 = ["Site da Prefeitura", "Órgão Fazendário", "Cartório autorizado", "Outros"]

                # Chaves padronizadas
                chave_link_93 = f"l93_in_{ano_sel}_fiscal"
                chave_coment_93 = f"coment_9.3_{ano_sel}_fiscal"

                # Layout do Checklist em 2 colunas
                c3, c4 = st.columns([1, 1])
                for idx, opcao in enumerate(opc93):
                    target_col = c3 if idx % 2 == 0 else c4
                    with target_col:
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel93), 
                            key=f"chk_93_{idx}_{ano_sel}_fiscal"
                        )

                st.markdown("---")

                # Campo de Evidências / Link
                link_93 = st.text_area(
                    "Link/Evidência (9.3):", 
                    value=evidencia_93_salva, 
                    key=chave_link_93, 
                    placeholder="Insira os links e evidências...",
                    height=100
                )
                
                # Detecção visual de links no campo de evidências
                placeholder_links_93 = st.empty()
                links_93_visuais = re.findall(REGEX_PURE_URL, link_93 or "")
                if links_93_visuais: 
                    placeholder_links_93.markdown(
                        "**🔗 Ativos:** " 
                        + " | ".join(
                            [
                                f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                for u in links_93_visuais
                            ]
                        )
                    )

                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("9.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 9.3", key=f"btn_salvar_9_3_{ano_sel}", type="primary"):
                    # Coleta as opções marcadas no checklist
                    res93_atual = []
                    for idx_c, opc_c in enumerate(opc93):
                        if st.session_state.get(f"chk_93_{idx_c}_{ano_sel}_fiscal", opc_c in sel93):
                            res93_atual.append(opc_c)

                    val_sel_93 = json.dumps(res93_atual)
                    lnk_val_93 = link_93.strip()
                    
                    # Regra de Pontuação (Informativo - 0.0)
                    pts93_nova = 0.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_93, d93.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="9.3",
                        valor=val_sel_93,
                        pontos=float(pts93_nova),
                        link=lnk_val_93,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["9.3"] = {
                        "valor": val_sel_93,
                        "pontos": float(pts93_nova),
                        "link": lnk_val_93,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_93 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_93_salva or "")]

                    if lnk_val_93 != evidencia_93_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 9.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_93 = d93.get("pontos", 0.0)
                cor_status_93 = "#28a745"
                st.markdown(
                    f"<span style='color:{cor_status_93}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 9.3: {pts_exibido_93:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 9.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.3", st.session_state.get(f"links_pendentes_9_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 9.4 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_9_4_{ano_sel}", border=True):
            with st.expander("📌 Quesito 9.4 - Informações de Transmissões Imobiliárias", expanded=True):
                st.subheader("9.4 • Obrigatoriedade dos Cartórios de Registro")
                st.write("**O município instituiu normativo que obrigue o(s) Cartório(s) de Registro de Imóveis e Distribuidor(es) a informar periodicamente as transmissões imobiliárias realizadas no seu território, para fins de incidência do ITBI?**")
                
                # Estado inicial / persistente
                d94 = res_data.get("9.4") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc94 = ["Selecione...", "Sim – 02", "Não – 00"]
                
                v_salvo_94 = d94.get("valor", "Selecione...")
                if v_salvo_94 not in opc94: 
                    v_salvo_94 = "Selecione..."
                
                evidencia_94_salva = d94.get("link", "")

                # Chaves padronizadas
                chave_rad_94 = f"rad_94_{ano_sel}_fiscal"
                chave_link_94 = f"l94_in_{ano_sel}_fiscal"
                chave_coment_94 = f"coment_9.4_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio(
                        "Selecione 9.4:", 
                        opc94, 
                        index=opc94.index(v_salvo_94), 
                        key=chave_rad_94
                    )
                with c2: 
                    link_94 = st.text_area(
                        "Link/Evidência (9.4):", 
                        value=evidencia_94_salva, 
                        key=chave_link_94, 
                        placeholder="Insira os links e evidências gerais...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_94 = st.empty()
                    links_94_visuais = re.findall(REGEX_PURE_URL, link_94 or "")
                    if links_94_visuais: 
                        placeholder_links_94.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_94_visuais
                                ]
                            )
                        )
                
                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("9.4", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 9.4", key=f"btn_salvar_9_4_{ano_sel}", type="primary"):
                    val_sel_94 = st.session_state.get(chave_rad_94, v_salvo_94)
                    lnk_val_94 = link_94.strip()
                    
                    # Regra de Pontuação (2.0 para Sim, 0.0 caso contrário)
                    pts94_nova = 2.0 if "Sim" in val_sel_94 else 0.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_94, d94.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="9.4",
                        valor=val_sel_94,
                        pontos=float(pts94_nova),
                        link=lnk_val_94,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["9.4"] = {
                        "valor": val_sel_94,
                        "pontos": float(pts94_nova),
                        "link": lnk_val_94,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_94 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_94_salva or "")]

                    if lnk_val_94 != evidencia_94_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 9.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_94 = d94.get("pontos", 0.0)
                cor_status_94 = "#28a745" if pts_exibido_94 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_status_94}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 9.4: {pts_exibido_94:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 9.4 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.4", st.session_state.get(f"links_pendentes_9_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_4_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 9.4.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_9_4_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 9.4.1 - Aplicação de Penalidades aos Cartórios", expanded=True):
                st.subheader("9.4.1 • Aplicação de Penalidade/Multas")
                st.write("**O município aplica penalidade ou multa aos Cartórios, quando não cumpridos os termos da lei mencionada na resposta do item anterior?**")
                
                # Estado inicial / persistente
                d941 = res_data.get("9.4.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc941 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                v_salvo_941 = d941.get("valor", "Selecione...")
                if v_salvo_941 not in opc941: 
                    v_salvo_941 = "Selecione..."
                
                evidencia_941_salva = d941.get("link", "")

                # Chaves padronizadas
                chave_rad_941 = f"rad_941_{ano_sel}_fiscal"
                chave_link_941 = f"l941_in_{ano_sel}_fiscal"
                chave_coment_941 = f"coment_9.4.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio(
                        "Selecione 9.4.1:", 
                        opc941, 
                        index=opc941.index(v_salvo_941), 
                        key=chave_rad_941
                    )
                with c2: 
                    link_941 = st.text_area(
                        "Link/Evidência (9.4.1):", 
                        value=evidencia_941_salva, 
                        key=chave_link_941, 
                        placeholder="Insira os links e evidências gerais...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_941 = st.empty()
                    links_941_visuais = re.findall(REGEX_PURE_URL, link_941 or "")
                    if links_941_visuais: 
                        placeholder_links_941.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_941_visuais
                                ]
                            )
                        )
                
                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("9.4.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 9.4.1", key=f"btn_salvar_9_4_1_{ano_sel}", type="primary"):
                    val_sel_941 = st.session_state.get(chave_rad_941, v_salvo_941)
                    lnk_val_941 = link_941.strip()
                    
                    # Regra de Pontuação (3.0 para Sim, 0.0 caso contrário)
                    pts941_nova = 3.0 if "Sim" in val_sel_941 else 0.0
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_941, d941.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="9.4.1",
                        valor=val_sel_941,
                        pontos=float(pts941_nova),
                        link=lnk_val_941,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["9.4.1"] = {
                        "valor": val_sel_941,
                        "pontos": float(pts941_nova),
                        "link": lnk_val_941,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_941 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_941_salva or "")]

                    if lnk_val_941 != evidencia_941_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_4_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_4_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 9.4.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_941 = d941.get("pontos", 0.0)
                cor_status_941 = "#28a745" if pts_exibido_941 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_status_941}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 9.4.1: {pts_exibido_941:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 9.4.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_4_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.4.1", st.session_state.get(f"links_pendentes_9_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_4_1_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 9.5 • TOTALMENTE INDEPENDENTE (FORMULÁRIO MULTI-CHECK DOS MEIOS DE PAGAMENTO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_5_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.5 - Forma de Recolhimento da Guia", expanded=True):
                st.subheader("9.5 • Meios de Recolhimento do ITBI")
                st.write("**Assinale a forma de recolhimento da guia do ITBI:**")
                
                # Estado inicial / persistente
                d95 = res_data.get("9.5") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                valor_salvo_95 = d95.get("valor", "") or ""
                evidencia_95_salva = d95.get("link", "")

                # Chaves padronizadas para session_state
                chave_chk_banco = f"chk_95_banco_{ano_sel}_fiscal"
                chave_chk_caixa = f"chk_95_caixa_{ano_sel}_fiscal"
                chave_chk_loterica = f"chk_95_loterica_{ano_sel}_fiscal"
                chave_chk_outros = f"chk_95_outros_{ano_sel}_fiscal"
                chave_link_95 = f"txt_95_{ano_sel}_fiscal"
                chave_coment_95 = f"coment_9.5_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.write("*Selecione todas as opções aplicáveis:*")
                    st.checkbox(
                        "Sistema Bancário", 
                        value=("Sistema Bancário" in valor_salvo_95), 
                        key=chave_chk_banco
                    )
                    st.checkbox(
                        "Diretamente no Caixa da Prefeitura", 
                        value=("Diretamente no Caixa da Prefeitura" in valor_salvo_95), 
                        key=chave_chk_caixa
                    )
                    st.checkbox(
                        "Lotérica", 
                        value=("Lotérica" in valor_salvo_95), 
                        key=chave_chk_loterica
                    )
                    st.checkbox(
                        "Outros", 
                        value=("Outros" in valor_salvo_95), 
                        key=chave_chk_outros
                    )

                with c2:
                    link_95 = st.text_area(
                        "Link/Evidência (9.5):", 
                        value=evidencia_95_salva, 
                        key=chave_link_95, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_95 = st.empty()
                    links_95_visuais = re.findall(REGEX_PURE_URL, link_95 or "")
                    if links_95_visuais:
                        placeholder_links_95.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_95_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("9.5", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 9.5", key=f"btn_salvar_9_5_{ano_sel}", type="primary"):
                    # Consolidação dos checkboxes selecionados
                    lista_selecionados = []
                    if st.session_state.get(chave_chk_banco, False): 
                        lista_selecionados.append("Sistema Bancário")
                    if st.session_state.get(chave_chk_caixa, False): 
                        lista_selecionados.append("Diretamente no Caixa da Prefeitura")
                    if st.session_state.get(chave_chk_loterica, False): 
                        lista_selecionados.append("Lotérica")
                    if st.session_state.get(chave_chk_outros, False): 
                        lista_selecionados.append("Outros")

                    str_resultado_95 = "/".join(lista_selecionados) if lista_selecionados else "Nenhuma"
                    lnk_val_95 = link_95.strip()
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_95, d95.get("comentarios", ""))

                    # Salva no banco de dados (Pontuação fixa 0.0)
                    save_resp_ifiscal(
                        qid="9.5",
                        valor=str_resultado_95,
                        pontos=0.0,
                        link=lnk_val_95,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["9.5"] = {
                        "valor": str_resultado_95,
                        "pontos": 0.0,
                        "link": lnk_val_95,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_95 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_95_salva or "")]

                    if lnk_val_95 != evidencia_95_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 9.5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Quesito meramente informativo)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 9.5: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 9.5 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.5", st.session_state.get(f"links_pendentes_9_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_5_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 9.6 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_6_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.6 - Progressividade do ITBI (Súmula 656 STF)", expanded=True):
                st.subheader("9.6 • Alíquotas Progressivas Venais")
                st.write("**O município estabelece alíquotas progressivas para o ITBI, com base no valor venal? Súmula 656, do Supremo Tribunal Federal**")
                
                # Estado inicial / persistente
                d96 = res_data.get("9.6") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc96 = ["Selecione...", "Sim – -30", "Não – 00"]
                v_salvo_96 = d96.get("valor", "Selecione...")
                if v_salvo_96 not in opc96: 
                    v_salvo_96 = "Selecione..."
                evidencia_96_salva = d96.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_96 = f"rad_96_{ano_sel}_fiscal"
                chave_link_96 = f"txt_96_{ano_sel}_fiscal"
                chave_coment_96 = f"coment_9.6_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1: 
                    opc_selecionada_96 = st.radio(
                        "Selecione 9.6:", 
                        opc96, 
                        index=opc96.index(v_salvo_96), 
                        key=chave_rad_96
                    )
                with c2: 
                    link_96 = st.text_area(
                        "Link/Evidência (9.6):", 
                        value=evidencia_96_salva, 
                        key=chave_link_96, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_96 = st.empty()
                    links_96_visuais = re.findall(REGEX_PURE_URL, link_96 or "")
                    if links_96_visuais:
                        placeholder_links_96.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_96_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("9.6", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 9.6", key=f"btn_salvar_9_6_{ano_sel}", type="primary"):
                    val_96 = st.session_state.get(chave_rad_96, v_salvo_96)
                    lnk_val_96 = link_96.strip()
                    
                    # Cálculo dos pontos
                    pts_96_nova = -30.0 if "Sim" in val_96 else 0.0

                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_96, d96.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="9.6",
                        valor=val_96,
                        pontos=float(pts_96_nova),
                        link=lnk_val_96,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["9.6"] = {
                        "valor": val_96,
                        "pontos": float(pts_96_nova),
                        "link": lnk_val_96,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_96 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_96_salva or "")]

                    if lnk_val_96 != evidencia_96_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_9_6_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_9_6_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 9.6 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação aplicada
                pts_exibido_96 = d96.get("pontos", 0.0)
                cor_impacto_96 = "#dc3545" if pts_exibido_96 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_impacto_96}; font-weight:bold;'>"
                    f"📊 Impacto 9.6: {pts_exibido_96:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 9.6 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_9_6_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("9.6", st.session_state.get(f"links_pendentes_9_6_{ano_sel}", []))
            st.session_state[f"gatilho_modal_9_6_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 10.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_10_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 10.0 - Instituição da CIP", expanded=True):
                st.subheader("10.0 • Instituição da CIP")
                st.write("**A Contribuição para Custeio do Serviço de Iluminação Pública (CIP) foi instituída?**")
                
                # Estado inicial / persistente
                d100 = res_data.get("10.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc100 = ["Selecione...", "Sim", "Não"]
                v_salvo_100 = d100.get("valor", "Selecione...")
                if v_salvo_100 not in opc100: 
                    v_salvo_100 = "Selecione..."
                evidencia_100_salva = d100.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_100 = f"rad_100_{ano_sel}_fiscal"
                chave_link_100 = f"txt_100_{ano_sel}_fiscal"
                chave_coment_100 = f"coment_10.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 10.0:", 
                        opc100, 
                        index=opc100.index(v_salvo_100), 
                        key=chave_rad_100
                    )
                with c2:
                    link_100 = st.text_area(
                        "Link/Evidência Geral (10.0):", 
                        value=evidencia_100_salva, 
                        key=chave_link_100, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_100 = st.empty()
                    links_100_visuais = re.findall(REGEX_PURE_URL, link_100 or "")
                    if links_100_visuais:
                        placeholder_links_100.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_100_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("10.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 10.0", key=f"btn_salvar_10_0_{ano_sel}", type="primary"):
                    val_100 = st.session_state.get(chave_rad_100, v_salvo_100)
                    lnk_val_100 = link_100.strip()
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_100, d100.get("comentarios", ""))

                    # Salva no banco de dados (Pontuação fixa 0.0)
                    save_resp_ifiscal(
                        qid="10.0",
                        valor=val_100,
                        pontos=0.0,
                        link=lnk_val_100,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["10.0"] = {
                        "valor": val_100,
                        "pontos": 0.0,
                        "link": lnk_val_100,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_100 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_100_salva or "")]

                    if lnk_val_100 != evidencia_100_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_10_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 10.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Quesito informativo)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 10.0: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 10.0 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_10_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("10.0", st.session_state.get(f"links_pendentes_10_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 10.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_10_1_{ano_sel}", border=True):
            with st.expander("📌 Quesito 10.1 - Instrumento Normativo da CIP", expanded=True):
                st.subheader("10.1 • Instrumento de Regulamentação")
                st.write("**Informe o instrumento normativo de instituição da Contribuição para Custeio do Serviço de Iluminação Pública (CIP), número e data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")
                
                # Estado inicial / persistente
                d101 = res_data.get("10.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_101 = d101.get("valor", "")
                evidencia_101_salva = d101.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_101 = f"txt_101_val_{ano_sel}_fiscal"
                chave_link_101 = f"l101_in_{ano_sel}_fiscal"
                chave_coment_101 = f"coment_10.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    inst_normativo_101 = st.text_input(
                        "Instrumento normativo da CIP (Nº e Data):", 
                        value=v_salvo_101, 
                        key=chave_txt_101,
                        placeholder="Ex: Lei Complementar nº 123/2020, pub. em 15/12/2020"
                    )
                with c2:
                    link_101 = st.text_area(
                        "Link/Evidência (10.1):", 
                        value=evidencia_101_salva, 
                        key=chave_link_101, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_101 = st.empty()
                    links_101_visuais = re.findall(REGEX_PURE_URL, link_101 or "")
                    if links_101_visuais:
                        placeholder_links_101.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_101_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("10.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 10.1", key=f"btn_salvar_10_1_{ano_sel}", type="primary"):
                    val_101 = inst_normativo_101.strip()
                    lnk_val_101 = link_101.strip()
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_101, d101.get("comentarios", ""))

                    # Salva no banco de dados (Pontuação fixa 0.0)
                    save_resp_ifiscal(
                        qid="10.1",
                        valor=val_101,
                        pontos=0.0,
                        link=lnk_val_101,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["10.1"] = {
                        "valor": val_101,
                        "pontos": 0.0,
                        "link": lnk_val_101,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_101 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_101_salva or "")]

                    if lnk_val_101 != evidencia_101_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_10_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_10_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 10.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Quesito informativo)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 10.1: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 10.1 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_10_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("10.1", st.session_state.get(f"links_pendentes_10_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_10_1_{ano_sel}"] = False

# =============================================================================
        # QUESITO 10.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_10_2_{ano_sel}", border=True):
            with st.expander("📌 Quesito 10.2 - Página de Divulgação da CIP", expanded=True):
                st.subheader("10.2 • Divulgação Eletrônica do Normativo")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do instrumento normativo de instituição da CIP:**")
                st.caption("⚠️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                # Estado inicial / persistente
                d102 = res_data.get("10.2") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_102 = d102.get("valor", "")
                evidencia_102_salva = d102.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_102 = f"txt_102_val_{ano_sel}_fiscal"
                chave_link_102 = f"l102_in_{ano_sel}_fiscal"
                chave_coment_102 = f"coment_10.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    v_input_102 = st.text_input(
                        "Link de divulgação da CIP (ou XYZ):", 
                        value=v_salvo_102, 
                        key=chave_txt_102,
                        placeholder="Ex: https://... ou XYZ"
                    )
                    
                    # Detecção visual de links no próprio campo de valor
                    lk_detec_102 = re.findall(REGEX_PURE_URL, v_input_102 or "")
                    if lk_detec_102:
                        st.markdown(
                            "**🔗 Detectado no campo:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in lk_detec_102
                                ]
                            )
                        )

                with c2:
                    link_102 = st.text_area(
                        "Link/Evidência Geral (10.2):", 
                        value=evidencia_102_salva, 
                        key=chave_link_102, 
                        placeholder="Insira os links e evidências adicionais...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo de evidências
                    placeholder_links_102 = st.empty()
                    links_102_visuais = re.findall(REGEX_PURE_URL, link_102 or "")
                    if links_102_visuais:
                        placeholder_links_102.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_102_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("10.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 10.2", key=f"btn_salvar_10_2_{ano_sel}", type="primary"):
                    val_102 = v_input_102.strip()
                    lnk_val_102 = link_102.strip()
                    
                    # Aplicação da regra de pontuação: XYZ aplica penalidade (-3.0 pts)
                    pts102_nova = -3.0 if val_102.upper() == "XYZ" else 0.0

                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_102, d102.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="10.2",
                        valor=val_102,
                        pontos=pts102_nova,
                        link=lnk_val_102,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["10.2"] = {
                        "valor": val_102,
                        "pontos": pts102_nova,
                        "link": lnk_val_102,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_102 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_102_salva or "")]

                    if lnk_val_102 != evidencia_102_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_10_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_10_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 10.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição dinâmica do impacto de pontuação
                pts_exibido_102 = d102.get("pontos", 0.0)
                cor_impacto_102 = "#dc3545" if pts_exibido_102 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_impacto_102}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 10.2: {pts_exibido_102:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 10.2 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_10_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("10.2", st.session_state.get(f"links_pendentes_10_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_10_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 10.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_10_3_{ano_sel}", border=True):
            with st.expander("📌 Quesito 10.3 - Movimentação em Contas Específicas", expanded=True):
                st.subheader("10.3 • Exclusividade de Contas Bancárias")
                st.write("**Os recursos da Contribuição para Custeio do Serviço de Iluminação Pública (CIP) foram movimentados em contas específicas?**")
                
                # Estado inicial / persistente
                d103 = res_data.get("10.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc103 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                v_salvo_103 = d103.get("valor", "Selecione...")
                if v_salvo_103 not in opc103: 
                    v_salvo_103 = "Selecione..."
                evidencia_103_salva = d103.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_103 = f"rad_103_{ano_sel}_fiscal"
                chave_link_103 = f"txt_103_{ano_sel}_fiscal"
                chave_coment_103 = f"coment_10.3_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    opc_selecionada_103 = st.radio(
                        "Selecione 10.3:", 
                        opc103, 
                        index=opc103.index(v_salvo_103), 
                        key=chave_rad_103
                    )
                with c4:
                    link_103 = st.text_area(
                        "Link/Evidência de Conta Bancária Exclusiva (10.3):", 
                        value=evidencia_103_salva, 
                        key=chave_link_103, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo
                    placeholder_links_103 = st.empty()
                    links_103_visuais = re.findall(REGEX_PURE_URL, link_103 or "")
                    if links_103_visuais:
                        placeholder_links_103.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_103_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Renderiza o bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("10.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 10.3", key=f"btn_salvar_10_3_{ano_sel}", type="primary"):
                    val_103 = st.session_state.get(chave_rad_103, v_salvo_103)
                    lnk_val_103 = link_103.strip()
                    
                    # Cálculo dos pontos (Penalidade de -5.0 caso responda 'Não')
                    pts_103_nova = -5.0 if "Não" in val_103 else 0.0

                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_103, d103.get("comentarios", ""))

                    # Salva no banco de dados
                    save_resp_ifiscal(
                        qid="10.3",
                        valor=val_103,
                        pontos=float(pts_103_nova),
                        link=lnk_val_103,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["10.3"] = {
                        "valor": val_103,
                        "pontos": float(pts_103_nova),
                        "link": lnk_val_103,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de novos links para acionar o modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_103 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_103_salva or "")]

                    if lnk_val_103 != evidencia_103_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_10_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_10_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 10.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação aplicada
                pts_exibido_103 = d103.get("pontos", 0.0)
                cor_impacto_103 = "#dc3545" if pts_exibido_103 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_impacto_103}; font-weight:bold;'>"
                    f"📊 Impacto de Pontuação no Quesito 10.3: {pts_exibido_103:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 10.3 (Fora do container principal)
        if st.session_state.get(f"gatilho_modal_10_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("10.3", st.session_state.get(f"links_pendentes_10_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_10_3_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 11.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_11_0_{ano_sel}", border=True):
            with st.expander("📌 Quesito 11.0 - Regulamentação do IRRF", expanded=True):
                st.subheader("11.0 • Retenção de IRRF nas Contratações Municipais")
                st.write("**Houve regulamentação sobre a retenção de IRRF das contratações efetuadas pelo município nas compras de bens e serviços?**")
                
                # Estado inicial / persistente
                d110 = res_data.get("11.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc110 = ["Selecione...", "Sim – 03", "Não – 00"]
                v_salvo_110 = d110.get("valor", "Selecione...")
                if v_salvo_110 not in opc110:
                    v_salvo_110 = "Selecione..."
                evidencia_110_salva = d110.get("link", "")

                # Chaves padronizadas para o session_state
                chave_rad_110 = f"rad_110_{ano_sel}_fiscal"
                chave_link_110 = f"txt_110_{ano_sel}_fiscal"
                chave_coment_110 = f"coment_11.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1: 
                    opc_selecionada_110 = st.radio(
                        "Selecione 11.0:", 
                        opc110, 
                        index=opc110.index(v_salvo_110), 
                        key=chave_rad_110
                    )
                with c2: 
                    link_110 = st.text_area(
                        "Link/Evidência (11.0):", 
                        value=evidencia_110_salva, 
                        key=chave_link_110, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_110 = st.empty()
                    links_110_visuais = re.findall(REGEX_PURE_URL, link_110 or "")
                    if links_110_visuais:
                        placeholder_links_110.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_110_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado
                bloco_comentarios_ifiscal("11.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 11.0", key=f"btn_salvar_11_0_{ano_sel}", type="primary"):
                    val_110 = st.session_state.get(chave_rad_110, v_salvo_110)
                    lnk_val_110 = link_110.strip()
                    
                    # Cálculo de pontuação: 'Sim' vale 3.0 pontos, caso contrário 0.0
                    pts_110_nova = 3.0 if "Sim" in val_110 else 0.0

                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_110, d110.get("comentarios", ""))

                    # Salva no banco/estrutura de dados
                    save_resp_ifiscal(
                        qid="11.0",
                        valor=val_110,
                        pontos=float(pts_110_nova),
                        link=lnk_val_110,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza res_data localmente
                    res_data["11.0"] = {
                        "valor": val_110,
                        "pontos": float(pts_110_nova),
                        "link": lnk_val_110,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_110 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_110_salva or "")]

                    if lnk_val_110 != evidencia_110_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_11_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 11.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Indicador visual da pontuação obtida
                pts_exibido_110 = d110.get("pontos", 0.0)
                cor_impacto_110 = "#28a745" if pts_exibido_110 > 0 else "#6c757d"
                st.markdown(
                    f"<span style='color:{cor_impacto_110}; font-weight:bold;'>"
                    f"📊 Impacto 11.0: {pts_exibido_110:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_11_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("11.0", st.session_state.get(f"links_pendentes_11_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.0 • REGISTRO DA RENÚNCIA DE RECEITAS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.0 - Renúncia de Receitas ({ano_sel})", expanded=True):
                st.subheader("12.0 • Concessão de Benefícios / Incentivos")
                st.write(f"**No exercício de {ano_sel}, foram concedidos benefícios e incentivos de natureza tributária, financeira e creditícia da qual decorram em renúncia de receitas?**")
                
                # Estado inicial / persistente
                d120 = res_data.get("12.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc120 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_120 = d120.get("valor", "Selecione...").split(" | ")[0] if d120.get("valor") else "Selecione..."
                if valor_limpo_120 not in opc120: 
                    valor_limpo_120 = "Selecione..."
                evidencia_120_salva = d120.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_120 = f"rad_120_{ano_sel}_fiscal"
                chave_link_120 = f"txt_120_{ano_sel}_fiscal"
                chave_coment_120 = f"coment_12.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    opc_selecionada_120 = st.radio(
                        "Selecione 12.0:", 
                        opc120, 
                        index=opc120.index(valor_limpo_120), 
                        key=chave_rad_120
                    )
                with c2:
                    link_120 = st.text_area(
                        f"Link/Evidência Geral ({ano_sel}):", 
                        value=evidencia_120_salva, 
                        key=chave_link_120, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_120 = st.empty()
                    links_120_visuais = re.findall(REGEX_PURE_URL, link_120 or "")
                    if links_120_visuais:
                        placeholder_links_120.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_120_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.0", key=f"btn_salvar_12_0_{ano_sel}", type="primary"):
                    val_cru = st.session_state.get(chave_rad_120, valor_limpo_120)
                    lnk_val_120 = link_120.strip()
                    
                    # Formatação do valor incluindo o ano de referência
                    val_com_ano = f"{val_cru} | Exercício Ref: {ano_sel}" if val_cru != "Selecione..." else "Selecione..."
                    
                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_120, d120.get("comentarios", ""))

                    # Salva no banco de dados (Pontuação fixa 0.0)
                    save_resp_ifiscal(
                        qid="12.0",
                        valor=val_com_ano,
                        pontos=0.0,
                        link=lnk_val_120,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.0"] = {
                        "valor": val_com_ano,
                        "pontos": 0.0,
                        "link": lnk_val_120,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_120 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_120_salva or "")]

                    if lnk_val_120 != evidencia_120_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Quesito informativo/qualificatório)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 12.0: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.0", st.session_state.get(f"links_pendentes_12_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.1 • NORMAS E PROCEDIMENTOS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.1 - Normas de Renúncia ({ano_sel})", expanded=True):
                st.subheader("12.1 • Existência de Normas Regulamentares")
                st.write("**Há normas e procedimentos relativos à renúncia de receita?**")
                
                # Estado inicial / persistente
                d121 = res_data.get("12.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc121 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                
                v_salvo_121 = d121.get("valor", "Selecione...")
                if v_salvo_121 not in opc121: 
                    v_salvo_121 = "Selecione..."
                evidencia_121_salva = d121.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_121 = f"rad_121_{ano_sel}_fiscal"
                chave_link_121 = f"txt_121_{ano_sel}_fiscal"
                chave_coment_121 = f"coment_12.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    opc_selecionada_121 = st.radio(
                        "Selecione 12.1:", 
                        opc121, 
                        index=opc121.index(v_salvo_121), 
                        key=chave_rad_121
                    )
                with c2:
                    link_121 = st.text_area(
                        f"Link/Evidência Normativa ({ano_sel}):", 
                        value=evidencia_121_salva, 
                        key=chave_link_121, 
                        placeholder="Insira os links e evidências das normas...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_121 = st.empty()
                    links_121_visuais = re.findall(REGEX_PURE_URL, link_121 or "")
                    if links_121_visuais:
                        placeholder_links_121.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_121_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.1", key=f"btn_salvar_12_1_{ano_sel}", type="primary"):
                    val_cru_121 = st.session_state.get(chave_rad_121, v_salvo_121)
                    lnk_val_121 = link_121.strip()
                    
                    # Cálculo da pontuação conforme regra de negócio (-10 se 'Não', 0 se 'Sim' ou 'Selecione...')
                    pts121_nova = -10.0 if "Não" in val_cru_121 else 0.0
                    
                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_121, d121.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.1",
                        valor=val_cru_121,
                        pontos=float(pts121_nova),
                        link=lnk_val_121,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.1"] = {
                        "valor": val_cru_121,
                        "pontos": float(pts121_nova),
                        "link": lnk_val_121,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_121 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_121_salva or "")]

                    if lnk_val_121 != evidencia_121_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Destaque dinâmico: verde/vermelho)
                pts_exibido_121 = d121.get("pontos", 0.0)
                cor_pts = "#dc3545" if pts_exibido_121 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_pts}; font-weight:bold;'>"
                    f"📊 Impacto 12.1: {pts_exibido_121:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.1", st.session_state.get(f"links_pendentes_12_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.1.1 • INSTRUMENTO NORMATIVO DO 12.1
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_1_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.1.1 - Identificação do Normativo ({ano_sel})", expanded=True):
                st.subheader("12.1.1 • Detalhes do Instrumento Legal")
                st.write("**Informe o instrumento normativo de regulamentação dos procedimentos relativos à renúncia de receita, Número e Data da publicação:**")
                
                # Estado inicial / persistente
                d1211 = res_data.get("12.1.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_1211 = d1211.get("valor", "")
                evidencia_1211_salva = d1211.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_1211 = f"txt_1211_{ano_sel}_fiscal"
                chave_link_1211 = f"txt_lnk_1211_{ano_sel}_fiscal"
                chave_coment_1211 = f"coment_12.1.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    v_input_1211 = st.text_input(
                        "Instrumento normativo (Nº e Data):", 
                        value=v_salvo_1211, 
                        key=chave_txt_1211,
                        placeholder="Ex: Lei Municipal nº 1.234/2023 de 15/03/2023"
                    )
                    
                    # Detecção visual de links no próprio campo de texto livre
                    lk_detec_1211 = re.findall(REGEX_PURE_URL, v_input_1211 or "")
                    if lk_detec_1211:
                        st.markdown(
                            "**🔗 Detectado no campo:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in lk_detec_1211
                                ]
                            )
                        )

                with c2:
                    link_1211 = st.text_area(
                        "Link/Evidência da Publicação (12.1.1):", 
                        value=evidencia_1211_salva, 
                        key=chave_link_1211, 
                        placeholder="Insira os links e evidências do instrumento legal...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo de evidências
                    placeholder_links_1211 = st.empty()
                    links_1211_visuais = re.findall(REGEX_PURE_URL, link_1211 or "")
                    if links_1211_visuais:
                        placeholder_links_1211.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_1211_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.1.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.1.1", key=f"btn_salvar_12_1_1_{ano_sel}", type="primary"):
                    val_1211 = v_input_1211.strip()
                    lnk_val_1211 = link_1211.strip()
                    
                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_1211, d1211.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra/qualificatória 0.0)
                    save_resp_ifiscal(
                        qid="12.1.1",
                        valor=val_1211,
                        pontos=0.0,
                        link=lnk_val_1211,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.1.1"] = {
                        "valor": val_1211,
                        "pontos": 0.0,
                        "link": lnk_val_1211,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1211 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1211_salva or "")]

                    if lnk_val_1211 != evidencia_1211_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_1_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_1_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.1.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Quesito informativo)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto de Pontuação no Quesito 12.1.1: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.1.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_1_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.1.1", st.session_state.get(f"links_pendentes_12_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_1_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.1.2 • URL DO NORMATIVO (TRAVA XYZ)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_1_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.1.2 - URL de Divulgação ({ano_sel})", expanded=True):
                st.subheader("12.1.2 • Endereço Eletrônico da Norma")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do instrumento normativo de regulamentação:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                # Estado inicial / persistente
                d1212 = res_data.get("12.1.2") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_1212 = d1212.get("valor", "")
                evidencia_1212_salva = d1212.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_1212 = f"txt_1212_{ano_sel}_fiscal"
                chave_link_1212 = f"txt_lnk_1212_{ano_sel}_fiscal"
                chave_coment_1212 = f"coment_12.1.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    v1212_input = st.text_input(
                        "Página eletrônica (ou XYZ) - 12.1.2:", 
                        value=v_salvo_1212, 
                        key=chave_txt_1212,
                        placeholder="https://... ou XYZ"
                    )
                    
                    # Visualização de links detectados na URL informada
                    if v1212_input and v1212_input.strip().upper() != "XYZ":
                        links_url_1212 = re.findall(REGEX_PURE_URL, v1212_input or "")
                        if links_url_1212:
                            st.markdown(
                                "**🔗 URL Informada:** " 
                                + " | ".join(
                                    [
                                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                        for u in links_url_1212
                                    ]
                                )
                            )

                with c2:
                    link_1212 = st.text_area(
                        "Evidência Adicional (12.1.2):", 
                        value=evidencia_1212_salva, 
                        key=chave_link_1212, 
                        placeholder="Insira os links e evidências complementares...",
                        height=100
                    )
                    
                    # Detecção visual de links no campo de evidências
                    placeholder_links_1212 = st.empty()
                    links_1212_visuais = re.findall(REGEX_PURE_URL, link_1212 or "")
                    if links_1212_visuais:
                        placeholder_links_1212.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_1212_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.1.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.1.2", key=f"btn_salvar_12_1_2_{ano_sel}", type="primary"):
                    val_1212 = v1212_input.strip()
                    lnk_val_1212 = link_1212.strip()
                    
                    # Cálculo de pontuação conforme a Trava XYZ (-3.0 se XYZ, caso contrário 0.0)
                    pts1212_nova = -3.0 if val_1212.upper() == "XYZ" else 0.0

                    # Captura o comentário atualizado
                    comentario_para_salvar = st.session_state.get(chave_coment_1212, d1212.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.1.2",
                        valor=val_1212,
                        pontos=float(pts1212_nova),
                        link=lnk_val_1212,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.1.2"] = {
                        "valor": val_1212,
                        "pontos": float(pts1212_nova),
                        "link": lnk_val_1212,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links combinados (URL informada + Evidências) para modal de auditoria
                    lk_combinados_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, f"{val_1212} {lnk_val_1212}")]
                    lk_combinados_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, f"{v_salvo_1212} {evidencia_1212_salva}")]

                    if lk_combinados_atuais and lk_combinados_atuais != lk_combinados_antigos:
                        st.session_state[f"links_pendentes_12_1_2_{ano_sel}"] = lk_combinados_atuais
                        st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.1.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Destaque dinâmico: vermelho para penalidade XYZ)
                pts_exibido_1212 = d1212.get("pontos", 0.0)
                cor_impacto_1212 = "#dc3545" if pts_exibido_1212 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_impacto_1212}; font-weight:bold;'>"
                    f"📊 Impacto 12.1.2: {pts_exibido_1212:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.1.2 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_1_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.1.2", st.session_state.get(f"links_pendentes_12_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.2 • ACOMPANHAMENTO E AVALIAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.2 - Avaliação Periódica ({ano_sel})", expanded=True):
                st.subheader("12.2 • Monitoramento das Renúncias")
                st.write("**A Prefeitura Municipal realizou acompanhamento e (re)avaliação das renúncias de receita?**")
                
                # Estado inicial / persistente
                d122 = res_data.get("12.2") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc122 = [
                    "Selecione...",
                    "Sim, de todas as renúncias de receita – 00",
                    "Sim, de parte das renúncias de receita – -02 (perde 02 pontos)",
                    "Não – -05 (perde 05 pontos)"
                ]
                
                v_salvo_122 = d122.get("valor", "Selecione...")
                if v_salvo_122 not in opc122: 
                    v_salvo_122 = "Selecione..."
                evidencia_122_salva = d122.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_122 = f"rad_122_{ano_sel}_fiscal"
                chave_link_122 = f"txt_122_{ano_sel}_fiscal"
                chave_coment_122 = f"coment_12.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    opc_selecionada_122 = st.radio(
                        "Selecione 12.2:", 
                        opc122, 
                        index=opc122.index(v_salvo_122), 
                        key=chave_rad_122
                    )
                with c2:
                    link_122 = st.text_area(
                        f"Link/Evidência do Acompanhamento ({ano_sel}):", 
                        value=evidencia_122_salva, 
                        key=chave_link_122, 
                        placeholder="Insira os links e evidências do acompanhamento...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_122 = st.empty()
                    links_122_visuais = re.findall(REGEX_PURE_URL, link_122 or "")
                    if links_122_visuais:
                        placeholder_links_122.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_122_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.2", key=f"btn_salvar_12_2_{ano_sel}", type="primary"):
                    val_cru_122 = st.session_state.get(chave_rad_122, v_salvo_122)
                    lnk_val_122 = link_122.strip()
                    
                    # Cálculo da pontuação conforme regra de negócio
                    if "todas" in val_cru_122:
                        pts122_nova = 0.0
                    elif "parte" in val_cru_122:
                        pts122_nova = -2.0
                    elif val_cru_122 == "Selecione...":
                        pts122_nova = 0.0
                    else:
                        pts122_nova = -5.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_122, d122.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.2",
                        valor=val_cru_122,
                        pontos=float(pts122_nova),
                        link=lnk_val_122,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.2"] = {
                        "valor": val_cru_122,
                        "pontos": float(pts122_nova),
                        "link": lnk_val_122,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_122 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_122_salva or "")]

                    if lnk_val_122 != evidencia_122_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Destaque dinâmico: verde/vermelho)
                pts_exibido_122 = d122.get("pontos", 0.0)
                cor_pts = "#dc3545" if pts_exibido_122 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_pts}; font-weight:bold;'>"
                    f"📊 Impacto 12.2: {pts_exibido_122:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.2 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.2", st.session_state.get(f"links_pendentes_12_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_2_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.3 • DEMONSTRATIVO NA LDO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.3 - Demonstrativo AMF / LDO ({ano_sel})", expanded=True):
                st.subheader("12.3 • Previsão no Anexo de Metas Fiscais")
                st.write("**O Anexo de Metas Fiscais, que integra a LDO, contém demonstrativo da estimativa e compensação da renúncia de receita para o respectivo exercício orçamentário?**")
                
                # Estado inicial / persistente
                d123 = res_data.get("12.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc123 = [
                    "Selecione...",
                    "Todas as renúncias concedidas estão contidas no demonstrativo – 00",
                    "A maior parte das renúncias concedidas estão contidas no demonstrativo – -01 (perde 01 ponto)",
                    "A menor parte das renúncias concedidas estão contidas no demonstrativo – -03 (perde 03 pontos)",
                    "Não há demonstrativo – -05 (perde 05 pontos)"
                ]
                
                v_salvo_123 = d123.get("valor", "Selecione...")
                if v_salvo_123 not in opc123: 
                    v_salvo_123 = "Selecione..."
                evidencia_123_salva = d123.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_123 = f"rad_123_{ano_sel}_fiscal"
                chave_link_123 = f"txt_123_{ano_sel}_fiscal"
                chave_coment_123 = f"coment_12.3_{ano_sel}_fiscal"

                c5, c6 = st.columns([1, 1])
                with c5:
                    opc_selecionada_123 = st.radio(
                        "Selecione 12.3:", 
                        opc123, 
                        index=opc123.index(v_salvo_123), 
                        key=chave_rad_123
                    )
                with c6:
                    link_123 = st.text_area(
                        f"Link/Evidência do AMF da LDO ({ano_sel}):", 
                        value=evidencia_123_salva, 
                        key=chave_link_123, 
                        placeholder="Insira os links e evidências do AMF da LDO...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_123 = st.empty()
                    links_123_visuais = re.findall(REGEX_PURE_URL, link_123 or "")
                    if links_123_visuais:
                        placeholder_links_123.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_123_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.3", key=f"btn_salvar_12_3_{ano_sel}", type="primary"):
                    val_cru_123 = st.session_state.get(chave_rad_123, v_salvo_123)
                    lnk_val_123 = link_123.strip()
                    
                    # Cálculo da pontuação conforme regra de negócio
                    if "Todas" in val_cru_123:
                        pts123_nova = 0.0
                    elif "maior" in val_cru_123:
                        pts123_nova = -1.0
                    elif "menor" in val_cru_123:
                        pts123_nova = -3.0
                    elif val_cru_123 == "Selecione...":
                        pts123_nova = 0.0
                    else:
                        pts123_nova = -5.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_123, d123.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.3",
                        valor=val_cru_123,
                        pontos=float(pts123_nova),
                        link=lnk_val_123,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.3"] = {
                        "valor": val_cru_123,
                        "pontos": float(pts123_nova),
                        "link": lnk_val_123,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_123 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_123_salva or "")]

                    if lnk_val_123 != evidencia_123_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Destaque dinâmico: verde/vermelho)
                pts_exibido_123 = d123.get("pontos", 0.0)
                cor_pts = "#dc3545" if pts_exibido_123 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_pts}; font-weight:bold;'>"
                    f"📊 Impacto 12.3: {pts_exibido_123:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.3 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.3", st.session_state.get(f"links_pendentes_12_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_3_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.3.1 • COMPATIBILIDADE DE VALORES
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_3_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.3.1 - Conformidade Orçamentária ({ano_sel})", expanded=True):
                st.subheader("12.3.1 • Compatibilidade Fiscal das Estimativas")
                st.write(f"**O valor da renúncia de receita de {ano_sel} está compatível com a estimativa constante no Anexo de Metas Fiscais da Lei de Diretrizes Orçamentárias?**")
                
                # Estado inicial / persistente
                d1231 = res_data.get("12.3.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc1231 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                
                v_salvo_1231 = d1231.get("valor", "Selecione...")
                if v_salvo_1231 not in opc1231: 
                    v_salvo_1231 = "Selecione..."
                evidencia_1231_salva = d1231.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_1231 = f"rad_1231_{ano_sel}_fiscal"
                chave_link_1231 = f"txt_1231_{ano_sel}_fiscal"
                chave_coment_1231 = f"coment_12.3.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    opc_selecionada_1231 = st.radio(
                        "Selecione 12.3.1:", 
                        opc1231, 
                        index=opc1231.index(v_salvo_1231), 
                        key=chave_rad_1231
                    )
                with c2:
                    link_1231 = st.text_area(
                        f"Link/Evidência de Compatibilidade ({ano_sel}):", 
                        value=evidencia_1231_salva, 
                        key=chave_link_1231, 
                        placeholder="Insira os links e evidências de compatibilidade fiscal...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_1231 = st.empty()
                    links_1231_visuais = re.findall(REGEX_PURE_URL, link_1231 or "")
                    if links_1231_visuais:
                        placeholder_links_1231.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_1231_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.3.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.3.1", key=f"btn_salvar_12_3_1_{ano_sel}", type="primary"):
                    val_cru_1231 = st.session_state.get(chave_rad_1231, v_salvo_1231)
                    lnk_val_1231 = link_1231.strip()
                    
                    # Cálculo da pontuação conforme regra de negócio
                    pts1231_nova = -5.0 if "Não" in val_cru_1231 else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_1231, d1231.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.3.1",
                        valor=val_cru_1231,
                        pontos=float(pts1231_nova),
                        link=lnk_val_1231,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.3.1"] = {
                        "valor": val_cru_1231,
                        "pontos": float(pts1231_nova),
                        "link": lnk_val_1231,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1231 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1231_salva or "")]

                    if lnk_val_1231 != evidencia_1231_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_3_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_3_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.3.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Destaque dinâmico: verde/vermelho)
                pts_exibido_1231 = d1231.get("pontos", 0.0)
                cor_pts = "#dc3545" if pts_exibido_1231 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_pts}; font-weight:bold;'>"
                    f"📊 Impacto 12.3.1: {pts_exibido_1231:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.3.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_3_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.3.1", st.session_state.get(f"links_pendentes_12_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_3_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.4 • MENSURAÇÃO FINANCEIRA (MONETÁRIO)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_4_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.4 - Valor Total da Renúncia ({ano_sel})", expanded=True):
                st.subheader("12.4 • Montante Financeiro Estimado")
                st.write(f"**Informe o valor das renúncias no exercício de {ano_sel}:**")
                
                # Estado inicial / persistente
                d124 = res_data.get("12.4") or {"valor": "R$ 0,00", "pontos": 0.0, "link": "", "comentarios": ""}
                val_inicial = d124.get("valor", "R$ 0,00")
                if not val_inicial.startswith("R$"): 
                    val_inicial = f"R$ {val_inicial}"
                evidencia_124_salva = d124.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_124 = f"txt_124_dinamico_{ano_sel}_fiscal"
                chave_link_124 = f"txt_lnk_124_{ano_sel}_fiscal"
                chave_coment_124 = f"coment_12.4_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    val_digitado_124 = st.text_input(
                        "Informe o Valor Total (R$):", 
                        value=val_inicial, 
                        placeholder="Ex: 100.000,00", 
                        key=chave_txt_124
                    )
                with c2:
                    link_124 = st.text_area(
                        f"Link/Evidência da Memória de Cálculo ({ano_sel}):", 
                        value=evidencia_124_salva, 
                        key=chave_link_124, 
                        placeholder="Insira os links e evidências da memória de cálculo...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_124 = st.empty()
                    links_124_visuais = re.findall(REGEX_PURE_URL, link_124 or "")
                    if links_124_visuais:
                        placeholder_links_124.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_124_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.4", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.4", key=f"btn_salvar_12_4_{ano_sel}", type="primary"):
                    v_cru = st.session_state.get(chave_txt_124, val_inicial)
                    lnk_val_124 = link_124.strip()
                    
                    # Tratamento e sanitização do valor monetário
                    num_limpo = v_cru.replace("R$", "").replace(" ", "")
                    if "." in num_limpo and "," in num_limpo:
                        num_limpo = num_limpo.replace(".", "").replace(",", ".")
                    elif "," in num_limpo:
                        num_limpo = num_limpo.replace(",", ".")
                        
                    try:
                        valor_float = float(num_limpo)
                        valor_br = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        v124_salvar = f"R$ {valor_br}"
                    except ValueError:
                        v124_salvar = val_inicial  # Reverte em caso de falha no parsing numérico

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_124, d124.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.4",
                        valor=v124_salvar,
                        pontos=0.0,
                        link=lnk_val_124,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.4"] = {
                        "valor": v124_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_124,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_124 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_124_salva or "")]

                    if lnk_val_124 != evidencia_124_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Quesito meramente informativo)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 12.4: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.4 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.4", st.session_state.get(f"links_pendentes_12_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_4_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.5 • TRANSPARÊNCIA E PUBLICIDADE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_5_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.5 - Publicidade e Controle Social ({ano_sel})", expanded=True):
                st.subheader("12.5 • Divulgação dos Benefícios")
                st.write(f"**Houve publicidade e transparência dos benefícios concedidos por Renúncia de Receitas em {ano_sel}?**")
                
                # Estado inicial / persistente
                d125 = res_data.get("12.5") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc125 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                
                v_salvo_125 = d125.get("valor", "Selecione...")
                if v_salvo_125 not in opc125: 
                    v_salvo_125 = "Selecione..."
                
                evidencia_125_salva = d125.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_125 = f"rad_125_{ano_sel}_fiscal"
                chave_link_125 = f"txt_125_{ano_sel}_fiscal"
                chave_coment_125 = f"coment_12.5_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    val_selecionado_125 = st.radio(
                        "Selecione 12.5:", 
                        opc125, 
                        index=opc125.index(v_salvo_125), 
                        key=chave_rad_125
                    )
                with c2:
                    link_125 = st.text_area(
                        f"Link/Evidência de Publicidade Geral ({ano_sel}):", 
                        value=evidencia_125_salva, 
                        key=chave_link_125, 
                        placeholder="Insira os links e evidências da publicidade...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_125 = st.empty()
                    links_125_visuais = re.findall(REGEX_PURE_URL, link_125 or "")
                    if links_125_visuais:
                        placeholder_links_125.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_125_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.5", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.5", key=f"btn_salvar_12_5_{ano_sel}", type="primary"):
                    val_para_salvar = st.session_state.get(chave_rad_125, v_salvo_125)
                    lnk_val_125 = link_125.strip()
                    
                    # Cálculo do impacto na pontuação
                    pts125_nova = -10.0 if "Não" in val_para_salvar else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_125, d125.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.5",
                        valor=val_para_salvar,
                        pontos=float(pts125_nova),
                        link=lnk_val_125,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.5"] = {
                        "valor": val_para_salvar,
                        "pontos": float(pts125_nova),
                        "link": lnk_val_125,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_125 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_125_salva or "")]

                    if lnk_val_125 != evidencia_125_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação aplicada
                pts_exibido_125 = d125.get("pontos", 0.0)
                cor_impacto = "#dc3545" if pts_exibido_125 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_impacto}; font-weight:bold;'>"
                    f"📊 Impacto 12.5: {pts_exibido_125:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.5 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.5", st.session_state.get(f"links_pendentes_12_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_5_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.5.1 • CHECKLIST DE CONTEÚDO EXIBIDO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_5_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.5.1 - Escopo da Transparência ({ano_sel})", expanded=True):
                st.subheader("12.5.1 • Elementos Informativos Disponibilizados")
                st.write(f"**Assinale as informações divulgadas referente aos benefícios concedidos por Renúncia de Receitas em {ano_sel}: (Checklist)**")
                
                # Estado inicial / persistente
                d1251 = res_data.get("12.5.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    sel1251 = json.loads(d1251.get("valor", "[]").replace("'", '"'))
                    if not isinstance(sel1251, list):
                        sel1251 = []
                except Exception:
                    sel1251 = []
                
                evidencia_1251_salva = d1251.get("link", "")

                opc1251 = [
                    "Valor dos benefícios concedidos",
                    "Público beneficiado",
                    "Métodos utilizados na sua mensuração",
                    "Resultados socioeconômicos alcançados com a renúncia",
                    "Outros"
                ]

                # Chaves padronizadas para session_state
                chave_link_1251 = f"txt_lnk_1251_{ano_sel}_fiscal"
                chave_coment_1251 = f"coment_12.5.1_{ano_sel}_fiscal"

                c7, c8 = st.columns([1, 1])
                with c7:
                    st.write("**Itens divulgados:**")
                    # Renderiza cada opção do checklist mantendo o valor selecionado
                    for idx, opcao in enumerate(opc1251):
                        st.checkbox(
                            opcao,
                            value=(opcao in sel1251),
                            key=f"chk_1251_{idx}_{ano_sel}_fiscal"
                        )
                with c8:
                    link_1251 = st.text_area(
                        f"Link/Evidência dos Itens Declarados ({ano_sel}):", 
                        value=evidencia_1251_salva, 
                        key=chave_link_1251, 
                        placeholder="Insira os links e evidências dos itens divulgados...",
                        height=150
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_1251 = st.empty()
                    links_1251_visuais = re.findall(REGEX_PURE_URL, link_1251 or "")
                    if links_1251_visuais:
                        placeholder_links_1251.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_1251_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.5.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.5.1", key=f"btn_salvar_12_5_1_{ano_sel}", type="primary"):
                    # Compila as opções do checklist selecionadas no momento do clique
                    itens_selecionados = [
                        opcao for idx, opcao in enumerate(opc1251)
                        if st.session_state.get(f"chk_1251_{idx}_{ano_sel}_fiscal", False)
                    ]
                    
                    v_json_1251 = json.dumps(itens_selecionados)
                    lnk_val_1251 = link_1251.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_1251, d1251.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.5.1",
                        valor=v_json_1251,
                        pontos=0.0,
                        link=lnk_val_1251,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.5.1"] = {
                        "valor": v_json_1251,
                        "pontos": 0.0,
                        "link": lnk_val_1251,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_1251 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_1251_salva or "")]

                    if lnk_val_1251 != evidencia_1251_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_12_5_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_12_5_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.5.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação (Quesito meramente informativo)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 12.5.1: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.5.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_5_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.5.1", st.session_state.get(f"links_pendentes_12_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_5_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.5.2 • LINK DE DIVULGAÇÃO (TRAVA XYZ)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_12_5_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 12.5.2 - Link da Transparência ({ano_sel})", expanded=True):
                st.subheader("12.5.2 • Localizador na Rede Mundial")
                st.write(f"**Informe a página eletrônica (link na internet) de divulgação das informações referente aos benefícios concedidos por Renúncia de Receitas em {ano_sel}:**")
                st.caption("⚠️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                # Estado inicial / persistente
                d1252 = res_data.get("12.5.2") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_1252 = d1252.get("valor", "")
                evidencia_1252_salva = d1252.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_1252 = f"txt_1252_{ano_sel}_fiscal"
                chave_link_1252 = f"txt_lnk_1252_{ano_sel}_fiscal"
                chave_coment_1252 = f"coment_12.5.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    v1252_input = st.text_input(
                        f"Página eletrônica (ou XYZ) ({ano_sel}):", 
                        value=v_salvo_1252, 
                        key=chave_txt_1252,
                        placeholder="http://... ou XYZ"
                    )
                    
                    # Detecção e exibição visual dos links informados no campo de URL
                    if v1252_input and v1252_input.strip().upper() != "XYZ":
                        links_url_input = re.findall(REGEX_PURE_URL, v1252_input or "")
                        if links_url_input:
                            st.markdown(
                                "**🔗 URL Informada:** " 
                                + " | ".join(
                                    [
                                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                        for u in links_url_input
                                    ]
                                )
                            )

                with c2:
                    link_1252 = st.text_area(
                        f"Evidência Adicional ({ano_sel}):", 
                        value=evidencia_1252_salva, 
                        key=chave_link_1252, 
                        placeholder="Insira links ou evidências complementares...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links informados no campo de evidência
                    placeholder_links_1252 = st.empty()
                    links_1252_visuais = re.findall(REGEX_PURE_URL, link_1252 or "")
                    if links_1252_visuais:
                        placeholder_links_1252.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_1252_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("12.5.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 12.5.2", key=f"btn_salvar_12_5_2_{ano_sel}", type="primary"):
                    val_para_salvar = st.session_state.get(chave_txt_1252, v_salvo_1252).strip()
                    lnk_val_1252 = link_1252.strip()

                    # Cálculo da pontuação (Trava XYZ)
                    pts1252_nova = -3.0 if val_para_salvar.upper() == "XYZ" else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_1252, d1252.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="12.5.2",
                        valor=val_para_salvar,
                        pontos=float(pts1252_nova),
                        link=lnk_val_1252,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["12.5.2"] = {
                        "valor": val_para_salvar,
                        "pontos": float(pts1252_nova),
                        "link": lnk_val_1252,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    lk_combinados = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, f"{val_para_salvar} {lnk_val_1252}")]
                    lk_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, f"{v_salvo_1252} {evidencia_1252_salva}")]

                    if lk_combinados and lk_combinados != lk_antigos:
                        st.session_state[f"links_pendentes_12_5_2_{ano_sel}"] = lk_combinados
                        st.session_state[f"gatilho_modal_12_5_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 12.5.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação aplicada
                pts_exibido_1252 = d1252.get("pontos", 0.0)
                cor_impacto = "#dc3545" if pts_exibido_1252 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_impacto}; font-weight:bold;'>"
                    f"📊 Impacto 12.5.2: {pts_exibido_1252:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 12.5.2 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_12_5_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("12.5.2", st.session_state.get(f"links_pendentes_12_5_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_12_5_2_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 13.0 • REGULAMENTAÇÃO SOBRE DÍVIDA ATIVA
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_13_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.0 - Regulamentação da Dívida Ativa ({ano_sel})", expanded=True):
                st.subheader("13.0 • Dívida Ativa")
                st.write("**O município possui regulamentação sobre dívida ativa?**")
                
                # Estado inicial / persistente
                d130 = res_data.get("13.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc130 = ["Selecione...", "Sim – 01", "Não – 00"]
                
                valor_limpo_130 = d130.get("valor", "Selecione...")
                if valor_limpo_130 not in opc130: 
                    valor_limpo_130 = "Selecione..."
                
                evidencia_130_salva = d130.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_130 = f"rad_130_{ano_sel}_fiscal"
                chave_link_130 = f"txt_130_{ano_sel}_fiscal"
                chave_coment_130 = f"coment_13.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 13.0:", 
                        opc130, 
                        index=opc130.index(valor_limpo_130), 
                        key=chave_rad_130
                    )
                with c2:
                    link_130 = st.text_area(
                        f"Link/Evidência Geral ({ano_sel}):", 
                        value=evidencia_130_salva, 
                        key=chave_link_130, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_130 = st.empty()
                    links_130_visuais = re.findall(REGEX_PURE_URL, link_130 or "")
                    if links_130_visuais:
                        placeholder_links_130.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_130_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("13.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 13.0", key=f"btn_salvar_13_0_{ano_sel}", type="primary"):
                    val_para_salvar = st.session_state.get(chave_rad_130, valor_limpo_130)
                    lnk_val_130 = link_130.strip()

                    # Cálculo da pontuação
                    pts130_nova = 1.0 if "Sim" in val_para_salvar else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_130, d130.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="13.0",
                        valor=val_para_salvar,
                        pontos=float(pts130_nova),
                        link=lnk_val_130,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["13.0"] = {
                        "valor": val_para_salvar,
                        "pontos": float(pts130_nova),
                        "link": lnk_val_130,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_130 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_130_salva or "")]

                    if lnk_val_130 != evidencia_130_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 13.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_130 = d130.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 13.0: {pts_exibido_130:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 13.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_13_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.0", st.session_state.get(f"links_pendentes_13_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 13.1 • INSTRUMENTO NORMATIVO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_13_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.1 - Identificação do Normativo ({ano_sel})", expanded=True):
                st.subheader("13.1 • Instrumento Normativo da Dívida Ativa")
                st.write("**Instrumento normativo de regulamentação da dívida ativa, Número e Data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")
                
                # Estado inicial / persistente
                d131 = res_data.get("13.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_131 = d131.get("valor", "")
                evidencia_131_salva = d131.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_131 = f"txt_131_{ano_sel}_fiscal"
                chave_link_131 = f"txt_lnk_131_{ano_sel}_fiscal"
                chave_coment_131 = f"coment_13.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    v131_input = st.text_input(
                        f"Instrumento normativo (Nº e Data) ({ano_sel}):", 
                        value=v_salvo_131, 
                        key=chave_txt_131,
                        placeholder="Ex: Lei Complementar nº 123, de 10/01/2020"
                    )
                with c2:
                    link_131 = st.text_area(
                        f"Link/Evidência da Publicação (13.1) ({ano_sel}):", 
                        value=evidencia_131_salva, 
                        key=chave_link_131, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_131 = st.empty()
                    links_131_visuais = re.findall(REGEX_PURE_URL, link_131 or "")
                    if links_131_visuais:
                        placeholder_links_131.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_131_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("13.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 13.1", key=f"btn_salvar_13_1_{ano_sel}", type="primary"):
                    val_para_salvar = st.session_state.get(chave_txt_131, v_salvo_131).strip()
                    lnk_val_131 = link_131.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_131, d131.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="13.1",
                        valor=val_para_salvar,
                        pontos=0.0,
                        link=lnk_val_131,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["13.1"] = {
                        "valor": val_para_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_131,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_131 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_131_salva or "")]

                    if lnk_val_131 != evidencia_131_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 13.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 13.1: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 13.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_13_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.1", st.session_state.get(f"links_pendentes_13_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 13.2 • URL DO NORMATIVO (TRAVA XYZ)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_13_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.2 - URL de Divulgação ({ano_sel})", expanded=True):
                st.subheader("13.2 • Endereço Eletrônico da Norma")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da regulamentação da dívida ativa:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                # Estado inicial / persistente
                d132 = res_data.get("13.2") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_132 = d132.get("valor", "")
                evidencia_132_salva = d132.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_132 = f"txt_132_{ano_sel}_fiscal"
                chave_link_132 = f"txt_lnk_132_{ano_sel}_fiscal"
                chave_coment_132 = f"coment_13.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    v132_input = st.text_input(
                        f"Página eletrônica (ou XYZ) - 13.2 ({ano_sel}):", 
                        value=v_salvo_132, 
                        key=chave_txt_132,
                        placeholder="https://... ou XYZ"
                    )
                    
                    # Exibição visual do link do normativo se não for XYZ
                    if v132_input and v132_input.strip().upper() != "XYZ":
                        links_normativo = re.findall(REGEX_PURE_URL, v132_input or "")
                        if links_normativo:
                            st.markdown(
                                "**🔗 URL Informada:** " 
                                + " | ".join(
                                    [
                                        f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                        for u in links_normativo
                                    ]
                                )
                            )

                with c2:
                    link_132 = st.text_area(
                        f"Evidência Adicional (13.2) ({ano_sel}):", 
                        value=evidencia_132_salva, 
                        key=chave_link_132, 
                        placeholder="Insira os links e evidências adicionais...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links de evidência
                    placeholder_links_132 = st.empty()
                    links_132_visuais = re.findall(REGEX_PURE_URL, link_132 or "")
                    if links_132_visuais:
                        placeholder_links_132.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_132_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("13.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 13.2", key=f"btn_salvar_13_2_{ano_sel}", type="primary"):
                    val_para_salvar = st.session_state.get(chave_txt_132, v_salvo_132).strip()
                    lnk_val_132 = link_132.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_132, d132.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="13.2",
                        valor=val_para_salvar,
                        pontos=0.0,
                        link=lnk_val_132,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["13.2"] = {
                        "valor": val_para_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_132,
                        "comentarios": comentario_para_salvar
                    }

                    # Auditoria combinada de links (campo principal + evidência adicional)
                    lk_combinados_brutos = re.findall(REGEX_PURE_URL, f"{val_para_salvar} {lnk_val_132}")
                    lk_antigos_brutos = re.findall(REGEX_PURE_URL, f"{v_salvo_132} {evidencia_132_salva}")

                    lk_combinados = [u[0] if isinstance(u, tuple) else u for u in lk_combinados_brutos]
                    lk_antigos = [u[0] if isinstance(u, tuple) else u for u in lk_antigos_brutos]

                    if lk_combinados and lk_combinados != lk_antigos:
                        st.session_state[f"links_pendentes_13_2_{ano_sel}"] = lk_combinados
                        st.session_state[f"gatilho_modal_13_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Informações e comentários do Quesito 13.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_132 = d132.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 13.2: {pts_exibido_132:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 13.2 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_13_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.2", st.session_state.get(f"links_pendentes_13_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_2_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 13.3 • CHECKLIST DE CRITÉRIOS DA LEGISLAÇÃO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_13_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.3 - Critérios Estabelecidos (Checklist) ({ano_sel})", expanded=True):
                st.subheader("13.3 • Critérios da Legislação sobre Dívida Ativa")
                st.write("**Assinale os critérios estabelecidos na legislação sobre dívida ativa:**")
                
                # Estado inicial / persistente
                d133 = res_data.get("13.3") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                evidencia_133_salva = d133.get("link", "")
                
                # Tratamento do JSON de seleções anteriores
                try:
                    val_banco133 = str(d133.get("valor", "[]")).replace("'", '"')
                    sel133 = json.loads(val_banco133)
                    if not isinstance(sel133, list):
                        sel133 = []
                except Exception:
                    sel133 = []

                opcoes_133 = [
                    "Cobrança administrativa da dívida ativa – 1,5",
                    "Parcelamento da dívida ativa – 1,5",
                    "Restrição e controle da inadimplência nos parcelamentos da dívida ativa – 1,5",
                    "Início do trâmite da execução judicial da dívida ativa – 1,5",
                    "Anistia – 1,5",
                    "Remissão – 1,5"
                ]

                # Chaves padronizadas para session_state
                chave_link_133 = f"txt_lnk_133_{ano_sel}_fiscal"
                chave_coment_133 = f"coment_13.3_{ano_sel}_fiscal"

                # Renderização das opções em duas colunas sem on_change
                c3, c4 = st.columns([1, 1])
                for idx, opcao in enumerate(opcoes_133):
                    target_col = c3 if idx % 2 == 0 else c4
                    with target_col:
                        pode_marcar = opcao in sel133
                        st.checkbox(
                            opcao, 
                            value=pode_marcar, 
                            key=f"chk_133_{idx}_{ano_sel}_fiscal"
                        )

                st.markdown("---")

                # Campo de Evidências/Links Adicionais
                link_133 = st.text_area(
                    f"Link/Evidência Adicional do Checklist (13.3) ({ano_sel}):", 
                    value=evidencia_133_salva, 
                    key=chave_link_133, 
                    placeholder="Insira os links e evidências...",
                    height=100
                )
                
                # Detecção e exibição visual dos links no campo
                placeholder_links_133 = st.empty()
                links_133_visuais = re.findall(REGEX_PURE_URL, link_133 or "")
                if links_133_visuais:
                    placeholder_links_133.markdown(
                        "**🔗 Ativos:** " 
                        + " | ".join(
                            [
                                f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                for u in links_133_visuais
                            ]
                        )
                    )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("13.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 13.3", key=f"btn_salvar_13_3_{ano_sel}", type="primary"):
                    # Processa as opções marcadas
                    res133 = []
                    for idx, opcao in enumerate(opcoes_133):
                        if st.session_state.get(f"chk_133_{idx}_{ano_sel}_fiscal", False):
                            res133.append(opcao)

                    # Cálculo dinâmico de pontuação
                    pts133 = 0.0
                    mapeamento_pontos = {
                        "Cobrança administrativa": 1.5,
                        "Parcelamento": 1.5,
                        "Restrição e controle": 1.5,
                        "Início do trâmite": 1.5,
                        "Anistia": 1.5,
                        "Remissão": 1.5
                    }
                    for item in res133:
                        for chave, valor in mapeamento_pontos.items():
                            if chave in item:
                                pts133 += valor
                                break

                    val_para_salvar = json.dumps(res133)
                    lnk_val_133 = link_133.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_133, d133.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="13.3",
                        valor=val_para_salvar,
                        pontos=float(pts133),
                        link=lnk_val_133,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["13.3"] = {
                        "valor": val_para_salvar,
                        "pontos": float(pts133),
                        "link": lnk_val_133,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_133 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_133_salva or "")]

                    if lnk_val_133 != evidencia_133_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_13_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_13_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opções, pontuação e comentários do Quesito 13.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação aplicada
                pts_exibido_133 = d133.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 13.3: {pts_exibido_133:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 13.3 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_13_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("13.3", st.session_state.get(f"links_pendentes_13_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_3_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 14.0 • DÍVIDA ATIVA JUDICIAL
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_14_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.0 - Dívida Ativa Judicial ({ano_sel})", expanded=True):
                st.subheader("14.0 • Cobrança Judicial")
                st.write(f"**O Município possui dívida ativa executada de forma judicial em {ano_sel}?**")
                
                # Estado inicial / persistente
                d140 = res_data.get("14.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc140 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_140 = d140.get("valor", "Selecione...")
                if valor_limpo_140 not in opc140:
                    valor_limpo_140 = "Selecione..."
                
                evidencia_140_salva = d140.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_140 = f"rad_140_{ano_sel}_fiscal"
                chave_link_140 = f"txt_140_{ano_sel}_fiscal"
                chave_coment_140 = f"coment_14.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 14.0:", 
                        opc140, 
                        index=opc140.index(valor_limpo_140), 
                        key=chave_rad_140
                    )

                with c2:
                    link_140 = st.text_area(
                        f"Link/Evidência Geral de Execuções ({ano_sel}):", 
                        value=evidencia_140_salva, 
                        key=chave_link_140, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_140 = st.empty()
                    links_140_visuais = re.findall(REGEX_PURE_URL, link_140 or "")
                    if links_140_visuais:
                        placeholder_links_140.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_140_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("14.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 14.0", key=f"btn_salvar_14_0_{ano_sel}", type="primary"):
                    val_para_salvar = st.session_state.get(chave_rad_140, valor_limpo_140)
                    lnk_val_140 = link_140.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_140, d140.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="14.0",
                        valor=val_para_salvar,
                        pontos=0.0,
                        link=lnk_val_140,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["14.0"] = {
                        "valor": val_para_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_140,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_140 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_140_salva or "")]

                    if lnk_val_140 != evidencia_140_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 14.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_140 = d140.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 14.0: {pts_exibido_140:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 14.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_14_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.0", st.session_state.get(f"links_pendentes_14_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 14.1 • VALOR TOTAL EXECUTADO JUDICIALMENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_14_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.1 - Valor Judicial Total ({ano_sel})", expanded=True):
                st.subheader("14.1 • Mensuração da Dívida Executada")
                st.write(f"**Informe o valor total da dívida ativa executada de forma judicial no exercício de {ano_sel}:**")
                
                # Estado inicial / persistente
                d141 = res_data.get("14.1") or {"valor": "R$ 0,00", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_141 = d141.get("valor", "R$ 0,00")
                if not str(v_salvo_141).startswith("R$"):
                    v_salvo_141 = f"R$ {v_salvo_141}"
                
                evidencia_141_salva = d141.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_141 = f"txt_141_{ano_sel}_fiscal"
                chave_link_141 = f"txt_lnk_141_{ano_sel}_fiscal"
                chave_coment_141 = f"coment_14.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Informe o Valor Judicial Total (R$):", 
                        value=v_salvo_141, 
                        key=chave_txt_141, 
                        placeholder="Ex: 150.000,00"
                    )

                with c2:
                    link_141 = st.text_area(
                        f"Evidência Adicional (14.1) ({ano_sel}):", 
                        value=evidencia_141_salva, 
                        key=chave_link_141, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_141 = st.empty()
                    links_141_visuais = re.findall(REGEX_PURE_URL, link_141 or "")
                    if links_141_visuais:
                        placeholder_links_141.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_141_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("14.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 14.1", key=f"btn_salvar_14_1_{ano_sel}", type="primary"):
                    raw_input = st.session_state.get(chave_txt_141, v_salvo_141).strip()
                    lnk_val_141 = link_141.strip()

                    # Tratamento e sanitização de valor monetário
                    num_limpo = raw_input.replace("R$", "").replace(" ", "")
                    if "." in num_limpo and "," in num_limpo:
                        num_limpo = num_limpo.replace(".", "").replace(",", ".")
                    elif "," in num_limpo:
                        num_limpo = num_limpo.replace(",", ".")
                        
                    try:
                        valor_float = float(num_limpo) if num_limpo else 0.0
                        valor_br = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        v141_salvar = f"R$ {valor_br}"
                    except ValueError:
                        v141_salvar = v_salvo_141  # Fallback para o valor anteriormente salvo em caso de texto inválido

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_141, d141.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="14.1",
                        valor=v141_salvar,
                        pontos=0.0,
                        link=lnk_val_141,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["14.1"] = {
                        "valor": v141_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_141,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_141 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_141_salva or "")]

                    if lnk_val_141 != evidencia_141_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_14_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valor e comentários do Quesito 14.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_141 = d141.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 14.1: {pts_exibido_141:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 14.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_14_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("14.1", st.session_state.get(f"links_pendentes_14_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 15.0 • COBRANÇA EXTRAJUDICIAL DA DÍVIDA ATIVA
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_15_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 15.0 - Cobrança Extrajudicial ({ano_sel})", expanded=True):
                st.subheader("15.0 • Execução Extrajudicial")
                st.write(f"**A prefeitura realiza cobrança de dívida ativa de forma extrajudicial em {ano_sel}?**")
                
                # Estado inicial / persistente
                d150 = res_data.get("15.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc150 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_150 = d150.get("valor", "Selecione...")
                if valor_limpo_150 not in opc150:
                    valor_limpo_150 = "Selecione..."
                
                evidencia_150_salva = d150.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_150 = f"rad_150_{ano_sel}_fiscal"
                chave_link_150 = f"txt_150_{ano_sel}_fiscal"
                chave_coment_150 = f"coment_15.0_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio(
                        "Selecione 15.0:", 
                        opc150, 
                        index=opc150.index(valor_limpo_150), 
                        key=chave_rad_150
                    )

                with c4:
                    link_150 = st.text_area(
                        f"Link/Evidência de Cobranças Protestadas/Notificadas ({ano_sel}):", 
                        value=evidencia_150_salva, 
                        key=chave_link_150, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_150 = st.empty()
                    links_150_visuais = re.findall(REGEX_PURE_URL, link_150 or "")
                    if links_150_visuais:
                        placeholder_links_150.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_150_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("15.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 15.0", key=f"btn_salvar_15_0_{ano_sel}", type="primary"):
                    val_para_salvar = st.session_state.get(chave_rad_150, valor_limpo_150)
                    lnk_val_150 = link_150.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_150, d150.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="15.0",
                        valor=val_para_salvar,
                        pontos=0.0,
                        link=lnk_val_150,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["15.0"] = {
                        "valor": val_para_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_150,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_150 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_150_salva or "")]

                    if lnk_val_150 != evidencia_150_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 15.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_150 = d150.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 15.0: {pts_exibido_150:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 15.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_15_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.0", st.session_state.get(f"links_pendentes_15_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 15.1 • VALOR TOTAL COBRADO EXTRAJUDICIALMENTE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_15_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 15.1 - Valor Extrajudicial Total ({ano_sel})", expanded=True):
                st.subheader("15.1 • Mensuração da Cobrança Extrajudicial")
                st.write(f"**Informe o valor total da dívida ativa cobrada de forma extrajudicial no exercício de {ano_sel}:**")
                
                # Estado inicial / persistente
                d151 = res_data.get("15.1") or {"valor": "R$ 0,00", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_151 = d151.get("valor", "R$ 0,00")
                if not str(v_salvo_151).startswith("R$"):
                    v_salvo_151 = f"R$ {v_salvo_151}"
                
                evidencia_151_salva = d151.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_151 = f"txt_151_{ano_sel}_fiscal"
                chave_link_151 = f"txt_lnk_151_{ano_sel}_fiscal"
                chave_coment_151 = f"coment_15.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Informe o Valor Extrajudicial Total (R$):", 
                        value=v_salvo_151, 
                        key=chave_txt_151, 
                        placeholder="Ex: 85.300,50"
                    )

                with c2:
                    link_151 = st.text_area(
                        f"Evidência Adicional (15.1) ({ano_sel}):", 
                        value=evidencia_151_salva, 
                        key=chave_link_151, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_151 = st.empty()
                    links_151_visuais = re.findall(REGEX_PURE_URL, link_151 or "")
                    if links_151_visuais:
                        placeholder_links_151.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_151_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("15.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 15.1", key=f"btn_salvar_15_1_{ano_sel}", type="primary"):
                    raw_input = st.session_state.get(chave_txt_151, v_salvo_151).strip()
                    lnk_val_151 = link_151.strip()

                    # Tratamento e sanitização do valor monetário
                    num_limpo = raw_input.replace("R$", "").replace(" ", "")
                    if "." in num_limpo and "," in num_limpo:
                        num_limpo = num_limpo.replace(".", "").replace(",", ".")
                    elif "," in num_limpo:
                        num_limpo = num_limpo.replace(",", ".")
                        
                    try:
                        valor_float = float(num_limpo) if num_limpo else 0.0
                        valor_br = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        v151_salvar = f"R$ {valor_br}"
                    except ValueError:
                        v151_salvar = v_salvo_151  # Fallback caso digitem texto inválido

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_151, d151.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="15.1",
                        valor=v151_salvar,
                        pontos=0.0,
                        link=lnk_val_151,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["15.1"] = {
                        "valor": v151_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_151,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_151 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_151_salva or "")]

                    if lnk_val_151 != evidencia_151_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valor e comentários do Quesito 15.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_151 = d151.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 15.1: {pts_exibido_151:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 15.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_15_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.1", st.session_state.get(f"links_pendentes_15_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 15.2 • MODALIDADES DE COBRANÇA EXTRAJUDICIAL
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_15_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 15.2 - Modalidades Adotadas ({ano_sel})", expanded=True):
                st.subheader("15.2 • Modalidades de Cobrança Extrajudicial")
                st.write("**Assinale as modalidades de cobrança extrajudicial da dívida ativa adotadas pelo município:**")
                
                # Estado inicial / persistente
                d152 = res_data.get("15.2") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                evidencia_152_salva = d152.get("link", "")
                
                # Desserialização do JSON armazenado no banco
                try:
                    val_banco152 = str(d152.get("valor", "[]")).replace("'", '"')
                    sel152 = json.loads(val_banco152)
                    if not isinstance(sel152, list):
                        sel152 = []
                except Exception:
                    sel152 = []

                opcoes_152 = [
                    "Protesto Extrajudicial da CDA (Certidão da Dívida Ativa)",
                    "Parcelamento",
                    "Facilitação do Pagamento",
                    "Conciliação extrajudicial",
                    "Inclusão do nome do devedor em Cadastro (Ex. CADIN)",
                    "Inclusão do nome do devedor em serviços de proteção ao crédito",
                    "Outros"
                ]

                # Chaves padronizadas para session_state
                chave_link_152 = f"txt_152_{ano_sel}_fiscal"
                chave_coment_152 = f"coment_15.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    # Renderização dos checkboxes com base nos valores salvos
                    for idx, opcao in enumerate(opcoes_152):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel152), 
                            key=f"chk_152_{idx}_{ano_sel}_fiscal"
                        )

                with c2:
                    link_152 = st.text_area(
                        f"Link/Evidência de Legislação/Atos de Cobrança ({ano_sel}):", 
                        value=evidencia_152_salva, 
                        key=chave_link_152, 
                        placeholder="Insira os links e evidências...",
                        height=180
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_152 = st.empty()
                    links_152_visuais = re.findall(REGEX_PURE_URL, link_152 or "")
                    if links_152_visuais:
                        placeholder_links_152.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_152_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("15.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 15.2", key=f"btn_salvar_15_2_{ano_sel}", type="primary"):
                    # Captura das opções selecionadas nos checkboxes
                    res152_temp = []
                    for idx_chk, opcao_chk in enumerate(opcoes_152):
                        if st.session_state.get(f"chk_152_{idx_chk}_{ano_sel}_fiscal", False):
                            res152_temp.append(opcao_chk)
                    
                    valor_json = json.dumps(res152_temp, ensure_ascii=False)
                    lnk_val_152 = link_152.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_152, d152.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="15.2",
                        valor=valor_json,
                        pontos=0.0,
                        link=lnk_val_152,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["15.2"] = {
                        "valor": valor_json,
                        "pontos": 0.0,
                        "link": lnk_val_152,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_152 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_152_salva or "")]

                    if lnk_val_152 != evidencia_152_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_15_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_15_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Modalidades e comentários do Quesito 15.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_152 = d152.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 15.2: {pts_exibido_152:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 15.2 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_15_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("15.2", st.session_state.get(f"links_pendentes_15_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_2_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 16.0 • DÍVIDAS PRESCRITAS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_16_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 16.0 - Ocorrência de Prescrições ({ano_sel})", expanded=True):
                st.subheader("16.0 • Dívidas Prescritas")
                st.write(f"**No exercício de {ano_sel} houve dívidas prescritas?**")
                st.caption("ℹ️ *Considerar na prescrição ordinária apenas os valores passíveis de cobrança via judicial, conforme regulamento específico local.*")
                
                # Estado inicial / persistente
                d160 = res_data.get("16.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                
                opc160 = [
                    "Selecione...",
                    "Sim, houve prescrição ordinária – -10 (perde 10 pontos)",
                    "Sim, houve prescrição intercorrente – 00",
                    f"Não houve prescrição de dívidas em {ano_sel} – 00"
                ]
                
                valor_limpo_160 = d160.get("valor", "Selecione...")
                if valor_limpo_160 not in opc160:
                    valor_limpo_160 = "Selecione..."
                
                evidencia_160_salva = d160.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_160 = f"rad_160_{ano_sel}_fiscal"
                chave_link_160 = f"txt_160_{ano_sel}_fiscal"
                chave_coment_160 = f"coment_16.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 16.0:", 
                        opc160, 
                        index=opc160.index(valor_limpo_160), 
                        key=chave_rad_160
                    )

                with c2:
                    link_160 = st.text_area(
                        f"Link/Evidência Geral de Prescrições/Decretos ({ano_sel}):", 
                        value=evidencia_160_salva, 
                        key=chave_link_160, 
                        placeholder="Insira os links e evidências...",
                        height=120
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_160 = st.empty()
                    links_160_visuais = re.findall(REGEX_PURE_URL, link_160 or "")
                    if links_160_visuais:
                        placeholder_links_160.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_160_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("16.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.0", key=f"btn_salvar_16_0_{ano_sel}", type="primary"):
                    val_160 = st.session_state.get(chave_rad_160, valor_limpo_160)
                    lnk_val_160 = link_160.strip()

                    # Regra de pontuação
                    pts_160 = -10.0 if "ordinária" in val_160 else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_160, d160.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="16.0",
                        valor=val_160,
                        pontos=pts_160,
                        link=lnk_val_160,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["16.0"] = {
                        "valor": val_160,
                        "pontos": pts_160,
                        "link": lnk_val_160,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_160 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_160_salva or "")]

                    if lnk_val_160 != evidencia_160_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Resposta e comentários do Quesito 16.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação com cor dinâmica
                pts_exibido_160 = d160.get("pontos", 0.0)
                cor_p160 = "#dc3545" if pts_exibido_160 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_p160}; font-weight:bold;'>"
                    f"📊 Impacto 16.0: {pts_exibido_160:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 16.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_16_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.0", st.session_state.get(f"links_pendentes_16_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 16.1 • VALOR JUDICIAL PRESCRITO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_16_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 16.1 - Valor Prescrito Judicial ({ano_sel})", expanded=True):
                st.subheader("16.1 • Mensuração do Estoque Judicial Prescrito")
                st.write(f"**Informe o valor da dívida ativa prescrita na execução judicial em {ano_sel}:**")
                
                # Estado inicial / persistente
                d161 = res_data.get("16.1") or {"valor": "R$ 0,00", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_161 = str(d161.get("valor", "R$ 0,00"))
                if not v_salvo_161.startswith("R$") and v_salvo_161 != "":
                    v_salvo_161 = f"R$ {v_salvo_161}"
                
                evidencia_161_salva = d161.get("link", "")

                # Chaves padronizadas para session_state
                chave_val_161 = f"txt_161_{ano_sel}_fiscal"
                chave_link_161 = f"txt_lnk_161_{ano_sel}_fiscal"
                chave_coment_161 = f"coment_16.1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Informe o Valor Prescrito Judicial (R$):", 
                        value=v_salvo_161, 
                        key=chave_val_161, 
                        placeholder="Ex: 50.000,00"
                    )

                with c2:
                    link_161 = st.text_area(
                        f"Evidência Adicional ({ano_sel}):", 
                        value=evidencia_161_salva, 
                        key=chave_link_161, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_161 = st.empty()
                    links_161_visuais = re.findall(REGEX_PURE_URL, link_161 or "")
                    if links_161_visuais:
                        placeholder_links_161.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_161_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("16.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.1", key=f"btn_salvar_16_1_{ano_sel}", type="primary"):
                    raw_input = st.session_state.get(chave_val_161, v_salvo_161).strip()
                    lnk_val_161 = link_161.strip()

                    # Tratamento e conversão da máscara monetária R$
                    num_limpo = raw_input.replace("R$", "").replace(" ", "")
                    if "." in num_limpo and "," in num_limpo:
                        num_limpo = num_limpo.replace(".", "").replace(",", ".")
                    elif "," in num_limpo:
                        num_limpo = num_limpo.replace(",", ".")
                        
                    try:
                        valor_float = float(num_limpo) if num_limpo else 0.0
                        valor_br = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        v161_salvar = f"R$ {valor_br}"
                    except ValueError:
                        v161_salvar = v_salvo_161 if v_salvo_161 else "R$ 0,00"

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_161, d161.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="16.1",
                        valor=v161_salvar,
                        pontos=0.0,
                        link=lnk_val_161,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["16.1"] = {
                        "valor": v161_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_161,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_161 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_161_salva or "")]

                    if lnk_val_161 != evidencia_161_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valor e comentários do Quesito 16.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_161 = d161.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 16.1: {pts_exibido_161:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 16.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_16_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.1", st.session_state.get(f"links_pendentes_16_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 16.2 • VALOR EXTRAJUDICIAL PRESCRITO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_16_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 16.2 - Valor Prescrito Extrajudicial ({ano_sel})", expanded=True):
                st.subheader("16.2 • Mensuração do Estoque Extrajudicial Prescrito")
                st.write(f"**Informe o valor da dívida ativa cobrada de forma extrajudicial prescrita no exercício de {ano_sel}:**")
                
                # Estado inicial / persistente
                d162 = res_data.get("16.2") or {"valor": "R$ 0,00", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_162 = str(d162.get("valor", "R$ 0,00"))
                if not v_salvo_162.startswith("R$") and v_salvo_162 != "":
                    v_salvo_162 = f"R$ {v_salvo_162}"
                
                evidencia_162_salva = d162.get("link", "")

                # Chaves padronizadas para session_state
                chave_val_162 = f"txt_162_{ano_sel}_fiscal"
                chave_link_162 = f"txt_lnk_162_{ano_sel}_fiscal"
                chave_coment_162 = f"coment_16.2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Informe o Valor Prescrito Extrajudicial (R$):", 
                        value=v_salvo_162, 
                        key=chave_val_162, 
                        placeholder="Ex: 25.400,00"
                    )

                with c2:
                    link_162 = st.text_area(
                        f"Evidência Adicional ({ano_sel}):", 
                        value=evidencia_162_salva, 
                        key=chave_link_162, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_162 = st.empty()
                    links_162_visuais = re.findall(REGEX_PURE_URL, link_162 or "")
                    if links_162_visuais:
                        placeholder_links_162.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_162_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("16.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.2", key=f"btn_salvar_16_2_{ano_sel}", type="primary"):
                    raw_input = st.session_state.get(chave_val_162, v_salvo_162).strip()
                    lnk_val_162 = link_162.strip()

                    # Tratamento e conversão da máscara monetária R$
                    num_limpo = raw_input.replace("R$", "").replace(" ", "")
                    if "." in num_limpo and "," in num_limpo:
                        num_limpo = num_limpo.replace(".", "").replace(",", ".")
                    elif "," in num_limpo:
                        num_limpo = num_limpo.replace(",", ".")
                        
                    try:
                        valor_float = float(num_limpo) if num_limpo else 0.0
                        valor_br = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        v162_salvar = f"R$ {valor_br}"
                    except ValueError:
                        v162_salvar = v_salvo_162 if v_salvo_162 else "R$ 0,00"

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_162, d162.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal (Pontuação neutra = 0.0)
                    save_resp_ifiscal(
                        qid="16.2",
                        valor=v162_salvar,
                        pontos=0.0,
                        link=lnk_val_162,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["16.2"] = {
                        "valor": v162_salvar,
                        "pontos": 0.0,
                        "link": lnk_val_162,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_162 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_162_salva or "")]

                    if lnk_val_162 != evidencia_162_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valor e comentários do Quesito 16.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status da pontuação
                pts_exibido_162 = d162.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 16.2: {pts_exibido_162:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 16.2 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_16_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.2", st.session_state.get(f"links_pendentes_16_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_2_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 16.3 • PROVISÃO PARA PERDAS (PCASP)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_16_3_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 16.3 - Reconhecimento Contábil de Provisão ({ano_sel})", expanded=True):
                st.subheader("16.3 • Ajuste de Perdas Estimadas em Dívida Ativa")
                st.write(f"**O montante da dívida ativa prescrita cobrada de forma judicial e extrajudicial estava registrado na conta de Provisão para Perdas de Dívida Ativa?**")
                
                # Estado inicial / persistente
                d163 = res_data.get("16.3") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc163 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                
                valor_limpo_163 = str(d163.get("valor", "Selecione..."))
                if valor_limpo_163 not in opc163:
                    valor_limpo_163 = "Selecione..."
                
                evidencia_163_salva = d163.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_163 = f"rad_163_{ano_sel}_fiscal"
                chave_link_163 = f"txt_163_{ano_sel}_fiscal"
                chave_coment_163 = f"coment_16.3_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio(
                        "Selecione 16.3:", 
                        opc163, 
                        index=opc163.index(valor_limpo_163), 
                        key=chave_rad_163
                    )

                with c4:
                    link_163 = st.text_area(
                        f"Link/Evidência do Balanço Patrimonial / Razão Contábil ({ano_sel}):", 
                        value=evidencia_163_salva, 
                        key=chave_link_163, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_163 = st.empty()
                    links_163_visuais = re.findall(REGEX_PURE_URL, link_163 or "")
                    if links_163_visuais:
                        placeholder_links_163.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_163_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("16.3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 16.3", key=f"btn_salvar_16_3_{ano_sel}", type="primary"):
                    val_163_selecionado = st.session_state.get(chave_rad_163, valor_limpo_163)
                    lnk_val_163 = link_163.strip()

                    # Regra de pontuação
                    pts_163 = -5.0 if "Não" in val_163_selecionado else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_163, d163.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="16.3",
                        valor=val_163_selecionado,
                        pontos=pts_163,
                        link=lnk_val_163,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["16.3"] = {
                        "valor": val_163_selecionado,
                        "pontos": pts_163,
                        "link": lnk_val_163,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_163 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_163_salva or "")]

                    if lnk_val_163 != evidencia_163_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_16_3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_16_3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 16.3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição dinâmica da pontuação e cor do indicador
                pts_exibido_163 = d163.get("pontos", 0.0)
                cor_p163 = "#dc3545" if pts_exibido_163 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_p163}; font-weight:bold;'>"
                    f"📊 Impacto 16.3: {pts_exibido_163:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 16.3 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_16_3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("16.3", st.session_state.get(f"links_pendentes_16_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_3_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 17.0 • CONTROLE DE AÇÕES JUDICIAIS (POLO PASSIVO)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_17_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.0 - Controle de Ações Judiciais ({ano_sel})", expanded=True):
                st.subheader("17.0 • Controle do Polo Passivo")
                st.write(f"**A Prefeitura possui controle das ações judiciais em que é parte (polo passivo)?**")
                
                # Estado inicial / persistente
                d170 = res_data.get("17.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc170 = [
                    "Selecione...",
                    "Sim, de todas as ações – 00",
                    "Sim, da maior parte das ações – -01 (perde 01 ponto)",
                    "Sim, da menor parte das ações – -03 (perde 03 pontos)",
                    "Não – -05 (perde 05 pontos)"
                ]
                
                valor_limpo_170 = str(d170.get("valor", "Selecione..."))
                if valor_limpo_170 not in opc170:
                    valor_limpo_170 = "Selecione..."
                
                evidencia_170_salva = d170.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_170 = f"rad_170_{ano_sel}_fiscal"
                chave_link_170 = f"txt_170_{ano_sel}_fiscal"
                chave_coment_170 = f"coment_17.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 17.0:", 
                        opc170, 
                        index=opc170.index(valor_limpo_170), 
                        key=chave_rad_170
                    )

                with c2:
                    link_170 = st.text_area(
                        f"Link/Evidência do Sistema ou Relatório de Controle Legal ({ano_sel}):", 
                        value=evidencia_170_salva, 
                        key=chave_link_170, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_170 = st.empty()
                    links_170_visuais = re.findall(REGEX_PURE_URL, link_170 or "")
                    if links_170_visuais:
                        placeholder_links_170.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_170_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("17.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 17.0", key=f"btn_salvar_17_0_{ano_sel}", type="primary"):
                    val_170_selecionado = st.session_state.get(chave_rad_170, valor_limpo_170)
                    lnk_val_170 = link_170.strip()

                    # Regra de pontuação
                    if "todas" in val_170_selecionado:
                        pts_170 = 0.0
                    elif "maior" in val_170_selecionado:
                        pts_170 = -1.0
                    elif "menor" in val_170_selecionado:
                        pts_170 = -3.0
                    elif "Não" in val_170_selecionado:
                        pts_170 = -5.0
                    else:
                        pts_170 = 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_170, d170.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="17.0",
                        valor=val_170_selecionado,
                        pontos=pts_170,
                        link=lnk_val_170,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["17.0"] = {
                        "valor": val_170_selecionado,
                        "pontos": pts_170,
                        "link": lnk_val_170,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_170 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_170_salva or "")]

                    if lnk_val_170 != evidencia_170_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_17_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_17_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 17.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição dinâmica da pontuação e cor do indicador
                pts_exibido_170 = d170.get("pontos", 0.0)
                cor_p170 = "#dc3545" if pts_exibido_170 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_p170}; font-weight:bold;'>"
                    f"📊 Impacto 17.0: {pts_exibido_170:.1f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 17.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_17_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.0", st.session_state.get(f"links_pendentes_17_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 17.1 • DESCRIÇÃO DA METODOLOGIA DE CONTROLE
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_17_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.1 - Metodologia de Controle Descritiva ({ano_sel})", expanded=True):
                st.subheader("17.1 • Metodologia do Polo Passivo")
                st.write("**Descreva de que forma é realizado o controle das ações judiciais em que é parte (polo passivo):**")
                
                # Estado inicial / persistente
                d171 = res_data.get("17.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_171 = str(d171.get("valor", ""))
                evidencia_171_salva = d171.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_171 = f"txt_171_desc_{ano_sel}_fiscal"
                chave_link_171 = f"txt_lnk_171_{ano_sel}_fiscal"
                chave_coment_171 = f"coment_17.1_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.text_area(
                        "Descreva a metodologia/sistema de controle:",
                        value=v_salvo_171,
                        placeholder="Ex: O controle é realizado via sistema informatizado da Procuradoria Geral...",
                        key=chave_txt_171,
                        height=120
                    )

                with c4:
                    link_171 = st.text_area(
                        f"Evidência Adicional ({ano_sel}):", 
                        value=evidencia_171_salva, 
                        key=chave_link_171, 
                        placeholder="Insira os links e evidências...",
                        height=120
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_171 = st.empty()
                    links_171_visuais = re.findall(REGEX_PURE_URL, link_171 or "")
                    if links_171_visuais:
                        placeholder_links_171.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_171_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("17.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 17.1", key=f"btn_salvar_17_1_{ano_sel}", type="primary"):
                    val_171_digitado = st.session_state.get(chave_txt_171, v_salvo_171).strip()
                    lnk_val_171 = link_171.strip()

                    # Quesito meramente descritivo (0.0 ponto)
                    pts_171 = 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_171, d171.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="17.1",
                        valor=val_171_digitado,
                        pontos=pts_171,
                        link=lnk_val_171,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["17.1"] = {
                        "valor": val_171_digitado,
                        "pontos": pts_171,
                        "link": lnk_val_171,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_171 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_171_salva or "")]

                    if lnk_val_171 != evidencia_171_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_17_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_17_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Descrição e comentários do Quesito 17.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição fixa de pontuação neutra
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 17.1: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 17.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_17_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.1", st.session_state.get(f"links_pendentes_17_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 17.2 • VALOR ATUALIZADO DO POLO PASSIVO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_17_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.2 - Valor Consolidado do Polo Passivo ({ano_sel})", expanded=True):
                st.subheader("17.2 • Mensuração Econômica das Ações")
                st.write(f"**Qual o valor atualizado em 31/12/{ano_sel} de todas as ações judiciais em que é parte (polo passivo)?**")
                
                # Estado inicial / persistente
                d172 = res_data.get("17.2") or {"valor": "R$ 0,00", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_172 = str(d172.get("valor", "R$ 0,00"))
                if not v_salvo_172.startswith("R$"):
                    v_salvo_172 = f"R$ {v_salvo_172}"
                
                evidencia_172_salva = d172.get("link", "")

                # Chaves padronizadas para session_state
                chave_txt_172 = f"txt_172_{ano_sel}_fiscal"
                chave_link_172 = f"txt_lnk_172_{ano_sel}_fiscal"
                chave_coment_172 = f"coment_17.2_{ano_sel}_fiscal"

                c5, c6 = st.columns([1, 1])
                with c5:
                    st.text_input(
                        "Informe o Valor Total do Polo Passivo (R$):", 
                        value=v_salvo_172, 
                        key=chave_txt_172, 
                        placeholder="Ex: 1.250.000,00"
                    )

                with c6:
                    link_172 = st.text_area(
                        f"Evidência Adicional ({ano_sel}):", 
                        value=evidencia_172_salva, 
                        key=chave_link_172, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_172 = st.empty()
                    links_172_visuais = re.findall(REGEX_PURE_URL, link_172 or "")
                    if links_172_visuais:
                        placeholder_links_172.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_172_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("17.2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 17.2", key=f"btn_salvar_17_2_{ano_sel}", type="primary"):
                    raw_input_172 = st.session_state.get(chave_txt_172, v_salvo_172).strip()
                    lnk_val_172 = link_172.strip()

                    # Tratamento e sanitização do valor monetário
                    num_limpo = raw_input_172.replace("R$", "").replace(" ", "")
                    if "." in num_limpo and "," in num_limpo:
                        num_limpo = num_limpo.replace(".", "").replace(",", ".")
                    elif "," in num_limpo:
                        num_limpo = num_limpo.replace(",", ".")

                    try:
                        valor_float = float(num_limpo) if num_limpo else 0.0
                        valor_br = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        v172_salvar = f"R$ {valor_br}"
                    except ValueError:
                        v172_salvar = v_salvo_172 if v_salvo_172 else "R$ 0,00"

                    # Quesito monetário informativo (0.0 ponto)
                    pts_172 = 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_172, d172.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="17.2",
                        valor=v172_salvar,
                        pontos=pts_172,
                        link=lnk_val_172,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["17.2"] = {
                        "valor": v172_salvar,
                        "pontos": pts_172,
                        "link": lnk_val_172,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_172 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_172_salva or "")]

                    if lnk_val_172 != evidencia_172_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_17_2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_17_2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valor e comentários do Quesito 17.2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação fixa (0.0 ponto)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 17.2: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 17.2 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_17_2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("17.2", st.session_state.get(f"links_pendentes_17_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_2_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 18.0 • DISPONIBILIDADE DA TRANSPARÊNCIA FISCAL
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_18_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.0 - Divulgação da Gestão Fiscal ({ano_sel})", expanded=True):
                st.subheader("18.0 • Transparência na Gestão Fiscal")
                st.write(f"**Os dados relativos à transparência na gestão fiscal são divulgados na página eletrônica do Município em {ano_sel}?**")
                
                # Estado inicial / persistente
                d180 = res_data.get("18.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc180 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_180 = str(d180.get("valor", "Selecione..."))
                if valor_limpo_180 not in opc180:
                    valor_limpo_180 = "Selecione..."
                
                evidencia_180_salva = d180.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_180 = f"rad_180_{ano_sel}_fiscal"
                chave_link_180 = f"txt_180_{ano_sel}_fiscal"
                chave_coment_180 = f"coment_18.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 18.0:", 
                        opc180, 
                        index=opc180.index(valor_limpo_180), 
                        key=chave_rad_180
                    )

                with c2:
                    link_180 = st.text_area(
                        f"Link do Portal da Transparência / Página Eletrônica ({ano_sel}):", 
                        value=evidencia_180_salva, 
                        key=chave_link_180, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_180 = st.empty()
                    links_180_visuais = re.findall(REGEX_PURE_URL, link_180 or "")
                    if links_180_visuais:
                        placeholder_links_180.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_180_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("18.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 18.0", key=f"btn_salvar_18_0_{ano_sel}", type="primary"):
                    val_180_selecionado = st.session_state.get(chave_rad_180, valor_limpo_180)
                    lnk_val_180 = link_180.strip()

                    # Quesito informativo/direcionador (0.0 ponto)
                    pts_180 = 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_180, d180.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="18.0",
                        valor=val_180_selecionado,
                        pontos=pts_180,
                        link=lnk_val_180,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["18.0"] = {
                        "valor": val_180_selecionado,
                        "pontos": pts_180,
                        "link": lnk_val_180,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_180 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_180_salva or "")]

                    if lnk_val_180 != evidencia_180_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_18_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_18_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 18.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação neutra
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 18.0: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 18.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_18_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.0", st.session_state.get(f"links_pendentes_18_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_18_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 18.1 • CHECKLIST DE DOCUMENTOS DIVULGADOS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_18_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.1 - Checklist de Itens Divulgados ({ano_sel})", expanded=True):
                st.subheader("18.1 • Itens Publicados na Página Eletrônica")
                st.write("**Assinale os itens que são divulgados na página eletrônica do Município (Checklist):**")
                
                # Estado inicial / persistente
                d181 = res_data.get("18.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                evidencia_181_salva = d181.get("link", "")
                
                # Desserialização do valor salvo
                try:
                    val_banco181 = str(d181.get("valor", "[]")).replace("'", '"')
                    sel181 = json.loads(val_banco181)
                    if not isinstance(sel181, list):
                        sel181 = []
                except Exception:
                    sel181 = []

                opcoes_181 = {
                    "PPA, LDO e LOA – 2,5": 2.5,
                    "Balanços de exercício – 2,5": 2.5,
                    "Prestação de contas do ano anterior – 2,5": 2.5,
                    "Parecer prévio do TCE – 2,5": 2.5,
                    "Relatório de Gestão Fiscal (RGF) – 2,5": 2.5,
                    "Relatório Resumido da Execução Orçamentária (RREO) – 2,5": 2.5
                }

                # Chaves padronizadas para session_state
                chave_link_181 = f"txt_181_{ano_sel}_fiscal"
                chave_coment_181 = f"coment_18.1_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    for idx, (opcao, _) in enumerate(opcoes_181.items()):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel181), 
                            key=f"chk_181_{idx}_{ano_sel}_fiscal"
                        )

                with c4:
                    link_181 = st.text_area(
                        f"Link/Evidência dos Documentos Publicados ({ano_sel}):", 
                        value=evidencia_181_salva, 
                        key=chave_link_181, 
                        placeholder="Insira os links e evidências...",
                        height=140
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_181 = st.empty()
                    links_181_visuais = re.findall(REGEX_PURE_URL, link_181 or "")
                    if links_181_visuais:
                        placeholder_links_181.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_181_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("18.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 18.1", key=f"btn_salvar_18_1_{ano_sel}", type="primary"):
                    res181_temp = []
                    pts_acumulados = 0.0

                    # Apuração dos checkboxes selecionados
                    for idx_chk, (opcao_chk, pontos_chk) in enumerate(opcoes_181.items()):
                        chk_key = f"chk_181_{idx_chk}_{ano_sel}_fiscal"
                        if st.session_state.get(chk_key, False):
                            res181_temp.append(opcao_chk)
                            pts_acumulados += pontos_chk

                    valor_json_181 = json.dumps(res181_temp)
                    lnk_val_181 = link_181.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_181, d181.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="18.1",
                        valor=valor_json_181,
                        pontos=float(pts_acumulados),
                        link=lnk_val_181,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["18.1"] = {
                        "valor": valor_json_181,
                        "pontos": float(pts_acumulados),
                        "link": lnk_val_181,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_181 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_181_salva or "")]

                    if lnk_val_181 != evidencia_181_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_18_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_18_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Checklist e comentários do Quesito 18.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação acumulada
                pts_atuais_181 = d181.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 18.1: {pts_atuais_181} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 18.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_18_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("18.1", st.session_state.get(f"links_pendentes_18_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_18_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 19.0 • DIVULGAÇÃO DE RECEITAS EM TEMPO REAL
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_19_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.0 - Receitas em Tempo Real ({ano_sel})", expanded=True):
                st.subheader("19.0 • Divulgação de Receitas em Tempo Real")
                st.write(f"**Houve divulgação das receitas arrecadadas em tempo real em {ano_sel}?**")
                st.caption("ℹ️ *Tempo real é considerado até o 1º dia útil que sucede o do registro contábil.*")
                
                # Estado inicial / persistente
                d190 = res_data.get("19.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc190 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                valor_limpo_190 = str(d190.get("valor", "Selecione..."))
                if valor_limpo_190 not in opc190:
                    valor_limpo_190 = "Selecione..."
                
                evidencia_190_salva = d190.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_190 = f"rad_190_{ano_sel}_fiscal"
                chave_link_190 = f"txt_190_{ano_sel}_fiscal"
                chave_coment_190 = f"coment_19.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 19.0:", 
                        opc190, 
                        index=opc190.index(valor_limpo_190), 
                        key=chave_rad_190
                    )

                with c2:
                    link_190 = st.text_area(
                        f"Link do Portal da Transparência / Tempo Real ({ano_sel}):", 
                        value=evidencia_190_salva, 
                        key=chave_link_190, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_190 = st.empty()
                    links_190_visuais = re.findall(REGEX_PURE_URL, link_190 or "")
                    if links_190_visuais:
                        placeholder_links_190.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_190_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("19.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 19.0", key=f"btn_salvar_19_0_{ano_sel}", type="primary"):
                    val_190_selecionado = st.session_state.get(chave_rad_190, valor_limpo_190)
                    lnk_val_190 = link_190.strip()

                    # Cálculo da pontuação
                    pts_190 = 3.0 if "Sim" in val_190_selecionado else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_190, d190.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="19.0",
                        valor=val_190_selecionado,
                        pontos=pts_190,
                        link=lnk_val_190,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["19.0"] = {
                        "valor": val_190_selecionado,
                        "pontos": pts_190,
                        "link": lnk_val_190,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_190 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_190_salva or "")]

                    if lnk_val_190 != evidencia_190_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_19_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_19_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 19.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação
                pts_atuais_190 = d190.get("pontos", 0.0)
                cor_p190 = "#28a745" if pts_atuais_190 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_p190}; font-weight:bold;'>"
                    f"📊 Impacto 19.0: {pts_atuais_190} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 19.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_19_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.0", st.session_state.get(f"links_pendentes_19_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_19_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 19.1 • CHECKLIST DE ITENS DA RECEITA
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_19_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 19.1 - Checklist de Itens da Receita ({ano_sel})", expanded=True):
                st.subheader("19.1 • Detalhamento das Receitas em Tempo Real")
                st.write("**Assinale os itens da receita divulgados em tempo real (Checklist):**")
                
                # Estado inicial / persistente
                d191 = res_data.get("19.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                evidencia_191_salva = d191.get("link", "")
                
                # Desserialização do valor salvo
                try:
                    val_banco191 = str(d191.get("valor", "[]")).replace("'", '"')
                    sel191 = json.loads(val_banco191)
                    if not isinstance(sel191, list):
                        sel191 = []
                except Exception:
                    sel191 = []

                opcoes_191 = {
                    "Categoria econômica – 0,3": 0.3,
                    "Origem – 0,3": 0.3,
                    "Espécie – 0,3": 0.3,
                    "Desdobramento para identificação de peculiaridades – 0,3": 0.3,
                    "Tipo – 0,3": 0.3,
                    "Valor previsto – 0,3": 0.3,
                    "Valor arrecadado – 0,3": 0.3,
                    "Data de arrecadação – 0,3": 0.3,
                    "Recursos extraordinários – 0,3": 0.3,
                    "Outros – 0,3": 0.3
                }

                # Chaves padronizadas para session_state
                chave_link_191 = f"txt_191_{ano_sel}_fiscal"
                chave_coment_191 = f"coment_19.1_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    for idx, (opcao, _) in enumerate(opcoes_191.items()):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel191), 
                            key=f"chk_191_{idx}_{ano_sel}_fiscal"
                        )

                with c4:
                    link_191 = st.text_area(
                        f"Link/Evidência dos Itens Demonstrados ({ano_sel}):", 
                        value=evidencia_191_salva, 
                        key=chave_link_191, 
                        placeholder="Insira os links e evidências...",
                        height=220
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_191 = st.empty()
                    links_191_visuais = re.findall(REGEX_PURE_URL, link_191 or "")
                    if links_191_visuais:
                        placeholder_links_191.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_191_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("19.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 19.1", key=f"btn_salvar_19_1_{ano_sel}", type="primary"):
                    res191_temp = []
                    pts_acumulados = 0.0

                    # Apuração dos checkboxes selecionados
                    for idx_chk, (opcao_chk, pontos_chk) in enumerate(opcoes_191.items()):
                        chk_key = f"chk_191_{idx_chk}_{ano_sel}_fiscal"
                        if st.session_state.get(chk_key, False):
                            res191_temp.append(opcao_chk)
                            pts_acumulados += pontos_chk

                    pts_finais_191 = round(pts_acumulados, 2)
                    valor_json_191 = json.dumps(res191_temp)
                    lnk_val_191 = link_191.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_191, d191.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="19.1",
                        valor=valor_json_191,
                        pontos=float(pts_finais_191),
                        link=lnk_val_191,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["19.1"] = {
                        "valor": valor_json_191,
                        "pontos": float(pts_finais_191),
                        "link": lnk_val_191,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_191 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_191_salva or "")]

                    if lnk_val_191 != evidencia_191_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_19_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_19_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Checklist e comentários do Quesito 19.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação acumulada
                pts_atuais_191 = d191.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 19.1: {pts_atuais_191} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 19.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_19_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("19.1", st.session_state.get(f"links_pendentes_19_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_19_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 20.0 • DIVULGAÇÃO DE DESPESAS EM TEMPO REAL
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_20_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 20.0 - Despesas em Tempo Real ({ano_sel})", expanded=True):
                st.subheader("20.0 • Divulgação de Despesas em Tempo Real")
                st.write(f"**Houve divulgação das despesas executadas em tempo real em {ano_sel}?**")
                st.caption("ℹ️ *Tempo real é considerado até o 1º dia útil que sucede o do registro contábil.*")
                
                # Estado inicial / persistente
                d200 = res_data.get("20.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc200 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                valor_limpo_200 = str(d200.get("valor", "Selecione..."))
                if valor_limpo_200 not in opc200:
                    valor_limpo_200 = "Selecione..."
                
                evidencia_200_salva = d200.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_200 = f"rad_200_{ano_sel}_fiscal"
                chave_link_200 = f"txt_200_{ano_sel}_fiscal"
                chave_coment_200 = f"coment_20.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 20.0:", 
                        opc200, 
                        index=opc200.index(valor_limpo_200), 
                        key=chave_rad_200
                    )

                with c2:
                    link_200 = st.text_area(
                        f"Link do Portal da Transparência / Despesas Tempo Real ({ano_sel}):", 
                        value=evidencia_200_salva, 
                        key=chave_link_200, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_200 = st.empty()
                    links_200_visuais = re.findall(REGEX_PURE_URL, link_200 or "")
                    if links_200_visuais:
                        placeholder_links_200.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_200_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("20.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 20.0", key=f"btn_salvar_20_0_{ano_sel}", type="primary"):
                    val_200_selecionado = st.session_state.get(chave_rad_200, valor_limpo_200)
                    lnk_val_200 = link_200.strip()

                    # Cálculo da pontuação
                    pts_200 = 3.0 if "Sim" in val_200_selecionado else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_200, d200.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="20.0",
                        valor=val_200_selecionado,
                        pontos=pts_200,
                        link=lnk_val_200,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["20.0"] = {
                        "valor": val_200_selecionado,
                        "pontos": pts_200,
                        "link": lnk_val_200,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_200 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_200_salva or "")]

                    if lnk_val_200 != evidencia_200_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_20_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_20_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 20.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação
                pts_atuais_200 = d200.get("pontos", 0.0)
                cor_p200 = "#28a745" if pts_atuais_200 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_p200}; font-weight:bold;'>"
                    f"📊 Impacto 20.0: {pts_atuais_200} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 20.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_20_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("20.0", st.session_state.get(f"links_pendentes_20_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_20_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 20.1 • CHECKLIST DE ITENS DA DESPESA
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_20_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 20.1 - Checklist de Itens da Despesa ({ano_sel})", expanded=True):
                st.subheader("20.1 • Detalhamento das Despesas em Tempo Real")
                st.write("**Assinale os itens das despesas divulgados em tempo real (Checklist):**")
                
                # Estado inicial / persistente
                d201 = res_data.get("20.1") or {"valor": "[]", "pontos": 0.0, "link": "", "comentarios": ""}
                evidencia_201_salva = d201.get("link", "")
                
                # Desserialização do valor salvo
                try:
                    val_banco201 = str(d201.get("valor", "[]")).replace("'", '"')
                    sel201 = json.loads(val_banco201)
                    if not isinstance(sel201, list):
                        sel201 = []
                except Exception:
                    sel201 = []

                opcoes_201 = {
                    "Valor empenhado – 0,3": 0.3,
                    "Valor liquidado – 0,3": 0.3,
                    "Valor pago – 0,3": 0.3,
                    "Número do processo da execução - nº empenho – 0,3": 0.3,
                    "Unidade Orçamentária - UO – 0,3": 0.3,
                    "Função – 0,3": 0.3,
                    "Subfunção – 0,3": 0.3,
                    "Categoria Econômica da despesa – 0,3": 0.3,
                    "Grupo de Natureza da despesa – 0,3": 0.3,
                    "Modalidade de aplicação – 0,3": 0.3,
                    "Elemento – 0,6": 0.6,
                    "Subelemento – 0,6": 0.6,
                    "Fonte de recurso – 0,3": 0.3,
                    "Favorecido do pagamento – 0,3": 0.3,
                    "Modalidade da licitação – 0,3": 0.3,
                    "Número do processo licitatório – 0,3": 0.3,
                    "Bem fornecido ou serviço prestado – 0,3": 0.3,
                    "Outros – 0,3": 0.3
                }

                # Chaves padronizadas para session_state
                chave_link_201 = f"txt_201_{ano_sel}_fiscal"
                chave_coment_201 = f"coment_20.1_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    for idx, (opcao, _) in enumerate(opcoes_201.items()):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel201), 
                            key=f"chk_201_{idx}_{ano_sel}_fiscal"
                        )

                with c4:
                    link_201 = st.text_area(
                        f"Link/Evidência das Despesas ({ano_sel}):", 
                        value=evidencia_201_salva, 
                        key=chave_link_201, 
                        placeholder="Insira os links e evidências...",
                        height=320
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_201 = st.empty()
                    links_201_visuais = re.findall(REGEX_PURE_URL, link_201 or "")
                    if links_201_visuais:
                        placeholder_links_201.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_201_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("20.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 20.1", key=f"btn_salvar_20_1_{ano_sel}", type="primary"):
                    res201_temp = []
                    pts_acumulados = 0.0

                    # Apuração dos checkboxes selecionados
                    for idx_chk, (opcao_chk, pontos_chk) in enumerate(opcoes_201.items()):
                        chk_key = f"chk_201_{idx_chk}_{ano_sel}_fiscal"
                        if st.session_state.get(chk_key, False):
                            res201_temp.append(opcao_chk)
                            pts_acumulados += pontos_chk

                    pts_finais_201 = round(pts_acumulados, 2)
                    valor_json_201 = json.dumps(res201_temp)
                    lnk_val_201 = link_201.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_201, d201.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="20.1",
                        valor=valor_json_201,
                        pontos=float(pts_finais_201),
                        link=lnk_val_201,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["20.1"] = {
                        "valor": valor_json_201,
                        "pontos": float(pts_finais_201),
                        "link": lnk_val_201,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_201 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_201_salva or "")]

                    if lnk_val_201 != evidencia_201_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_20_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_20_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Checklist e comentários do Quesito 20.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação acumulada
                pts_atuais_201 = d201.get("pontos", 0.0)
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto 20.1: {pts_atuais_201} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 20.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_20_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("20.1", st.session_state.get(f"links_pendentes_20_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_20_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 21.0 • DIVULGAÇÃO DE REMUNERAÇÃO INDIVIDUALIZADA
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_21_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 21.0 - Remuneração Individualizada ({ano_sel})", expanded=True):
                st.subheader("21.0 • Transparência de Remunerações")
                st.write(f"**Houve divulgação de remuneração individualizada por nome do agente público, contendo dados sobre os vencimentos, descontos, indenizações e valor líquido em {ano_sel}?**")
                
                # Estado inicial / persistente
                d210 = res_data.get("21.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc210 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                valor_limpo_210 = str(d210.get("valor", "Selecione..."))
                if valor_limpo_210 not in opc210:
                    valor_limpo_210 = "Selecione..."
                
                evidencia_210_salva = d210.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_210 = f"rad_210_{ano_sel}_fiscal"
                chave_link_210 = f"txt_210_{ano_sel}_fiscal"
                chave_coment_210 = f"coment_21.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 21.0:", 
                        opc210, 
                        index=opc210.index(valor_limpo_210), 
                        key=chave_rad_210
                    )

                with c2:
                    link_210 = st.text_area(
                        f"Link Geral do Portal de Transparência / Pessoal ({ano_sel}):", 
                        value=evidencia_210_salva, 
                        key=chave_link_210, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_210 = st.empty()
                    links_210_visuais = re.findall(REGEX_PURE_URL, link_210 or "")
                    if links_210_visuais:
                        placeholder_links_210.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_210_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("21.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 21.0", key=f"btn_salvar_21_0_{ano_sel}", type="primary"):
                    val_210_selecionado = st.session_state.get(chave_rad_210, valor_limpo_210)
                    lnk_val_210 = link_210.strip()

                    # Cálculo da pontuação
                    pts_210 = 3.0 if "Sim" in val_210_selecionado else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_210, d210.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="21.0",
                        valor=val_210_selecionado,
                        pontos=pts_210,
                        link=lnk_val_210,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["21.0"] = {
                        "valor": val_210_selecionado,
                        "pontos": pts_210,
                        "link": lnk_val_210,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_210 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_210_salva or "")]

                    if lnk_val_210 != evidencia_210_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_21_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_21_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 21.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação
                pts_atuais_210 = d210.get("pontos", 0.0)
                cor_p210 = "#28a745" if pts_atuais_210 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_p210}; font-weight:bold;'>"
                    f"📊 Impacto 21.0: {pts_atuais_210} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 21.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_21_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("21.0", st.session_state.get(f"links_pendentes_21_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_21_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 21.1 • ENDEREÇO ELETRÔNICO DA FOLHA DE PAGAMENTO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_21_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 21.1 - Endereço Eletrônico de Divulgação ({ano_sel})", expanded=True):
                st.subheader("21.1 • URL Direta da Folha")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da remuneração individualizada por nome do agente público:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                # Estado inicial / persistente
                d211 = res_data.get("21.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_211 = str(d211.get("valor", ""))
                evidencia_211_salva = d211.get("link", "")

                # Chaves padronizadas para session_state
                chave_val_211 = f"txt_211_val_{ano_sel}_fiscal"
                chave_link_211 = f"txt_lnk_211_{ano_sel}_fiscal"
                chave_coment_211 = f"coment_21.1_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    val_211_input = st.text_input(
                        "Link de divulgação da folha de pagamento (ou XYZ):", 
                        value=v_salvo_211, 
                        key=chave_val_211,
                        placeholder="Ex: https://... ou XYZ"
                    )
                    
                    # Detecção e exibição visual dos links no próprio valor informado
                    placeholder_val_211 = st.empty()
                    links_val_visuais = re.findall(REGEX_PURE_URL, val_211_input or "")
                    if links_val_visuais:
                        placeholder_val_211.markdown(
                            "**🔗 Link Informado:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_val_visuais
                                ]
                            )
                        )

                with c4:
                    link_211 = st.text_area(
                        f"Evidência Adicional ({ano_sel}):", 
                        value=evidencia_211_salva, 
                        key=chave_link_211, 
                        placeholder="Insira os links e evidências adicionais...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links na evidência secundária
                    placeholder_links_211 = st.empty()
                    links_211_visuais = re.findall(REGEX_PURE_URL, link_211 or "")
                    if links_211_visuais:
                        placeholder_links_211.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_211_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("21.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 21.1", key=f"btn_salvar_21_1_{ano_sel}", type="primary"):
                    val_211_final = st.session_state.get(chave_val_211, v_salvo_211).strip()
                    lnk_val_211 = link_211.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_211, d211.get("comentarios", ""))

                    # Quesito meramente informativo (pontuação fixa em 0.0)
                    save_resp_ifiscal(
                        qid="21.1",
                        valor=val_211_final,
                        pontos=0.0,
                        link=lnk_val_211,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["21.1"] = {
                        "valor": val_211_final,
                        "pontos": 0.0,
                        "link": lnk_val_211,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal (Varre valor principal e evidência)
                    links_atuais_val = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, val_211_final or "")]
                    links_antigos_val = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_211 or "")]
                    
                    links_atuais_lnk = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_211 or "")]
                    links_antigos_lnk = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_211_salva or "")]

                    # Combinação dos links novos pendentes de auditoria
                    links_pendentes = []
                    if val_211_final != v_salvo_211 and links_atuais_val and links_atuais_val != links_antigos_val:
                        links_pendentes.extend(links_atuais_val)
                    if lnk_val_211 != evidencia_211_salva and links_atuais_lnk and links_atuais_lnk != links_antigos_lnk:
                        links_pendentes.extend(links_atuais_lnk)

                    if links_pendentes:
                        st.session_state[f"links_pendentes_21_1_{ano_sel}"] = list(set(links_pendentes))
                        st.session_state[f"gatilho_modal_21_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("URL/Valor e comentários do Quesito 21.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação informativa (sempre 0.0)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 21.1: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 21.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_21_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("21.1", st.session_state.get(f"links_pendentes_21_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_21_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 22.0 • DIVULGAÇÃO DE DIÁRIAS E PASSAGENS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_22_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 22.0 - Diárias e Passagens ({ano_sel})", expanded=True):
                st.subheader("22.0 • Transparência de Diárias e Passagens")
                st.write(f"**Houve divulgação de diárias e passagens por nome de favorecido e constando data, destino, cargo e motivo de viagem em {ano_sel}?**")
                
                # Estado inicial / persistente
                d220 = res_data.get("22.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc220 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                valor_limpo_220 = str(d220.get("valor", "Selecione..."))
                if valor_limpo_220 not in opc220:
                    valor_limpo_220 = "Selecione..."
                
                evidencia_220_salva = d220.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_220 = f"rad_220_{ano_sel}_fiscal"
                chave_link_220 = f"txt_220_{ano_sel}_fiscal"
                chave_coment_220 = f"coment_22.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 22.0:", 
                        opc220, 
                        index=opc220.index(valor_limpo_220), 
                        key=chave_rad_220
                    )

                with c2:
                    link_220 = st.text_area(
                        f"Link Geral do Portal de Transparência / Diárias ({ano_sel}):", 
                        value=evidencia_220_salva, 
                        key=chave_link_220, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_220 = st.empty()
                    links_220_visuais = re.findall(REGEX_PURE_URL, link_220 or "")
                    if links_220_visuais:
                        placeholder_links_220.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_220_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("22.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 22.0", key=f"btn_salvar_22_0_{ano_sel}", type="primary"):
                    val_220_selecionado = st.session_state.get(chave_rad_220, valor_limpo_220)
                    lnk_val_220 = link_220.strip()

                    # Cálculo da pontuação
                    pts_220 = 3.0 if "Sim" in val_220_selecionado else 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_220, d220.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="22.0",
                        valor=val_220_selecionado,
                        pontos=pts_220,
                        link=lnk_val_220,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["22.0"] = {
                        "valor": val_220_selecionado,
                        "pontos": pts_220,
                        "link": lnk_val_220,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_220 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_220_salva or "")]

                    if lnk_val_220 != evidencia_220_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_22_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_22_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 22.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação
                pts_atuais_220 = d220.get("pontos", 0.0)
                cor_p220 = "#28a745" if pts_atuais_220 > 0 else "#dc3545"
                st.markdown(
                    f"<span style='color:{cor_p220}; font-weight:bold;'>"
                    f"📊 Impacto 22.0: {pts_atuais_220} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 22.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_22_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("22.0", st.session_state.get(f"links_pendentes_22_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_22_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 22.1 • ENDEREÇO ELETRÔNICO DE DIÁRIAS E PASSAGENS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_22_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 22.1 - Endereço Eletrônico de Divulgação ({ano_sel})", expanded=True):
                st.subheader("22.1 • URL Direta de Diárias e Passagens")
                st.write("**Informe a página eletrônica (link na internet) de divulgação de diárias e passagens:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                # Estado inicial / persistente
                d221 = res_data.get("22.1") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_221 = str(d221.get("valor", ""))
                evidencia_221_salva = d221.get("link", "")

                # Chaves padronizadas para session_state
                chave_val_221 = f"txt_221_val_{ano_sel}_fiscal"
                chave_link_221 = f"txt_lnk_221_{ano_sel}_fiscal"
                chave_coment_221 = f"coment_22.1_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    val_221_input = st.text_input(
                        "Link de divulgação das diárias e passagens (ou XYZ):", 
                        value=v_salvo_221, 
                        key=chave_val_221,
                        placeholder="Ex: https://... ou XYZ"
                    )
                    
                    # Detecção e exibição visual dos links no próprio valor informado
                    placeholder_val_221 = st.empty()
                    links_val_visuais = re.findall(REGEX_PURE_URL, val_221_input or "")
                    if links_val_visuais:
                        placeholder_val_221.markdown(
                            "**🔗 Link Informado:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_val_visuais
                                ]
                            )
                        )

                with c4:
                    link_221 = st.text_area(
                        f"Evidência Adicional ({ano_sel}):", 
                        value=evidencia_221_salva, 
                        key=chave_link_221, 
                        placeholder="Insira os links e evidências adicionais...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links na evidência secundária
                    placeholder_links_221 = st.empty()
                    links_221_visuais = re.findall(REGEX_PURE_URL, link_221 or "")
                    if links_221_visuais:
                        placeholder_links_221.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_221_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("22.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 22.1", key=f"btn_salvar_22_1_{ano_sel}", type="primary"):
                    val_221_final = st.session_state.get(chave_val_221, v_salvo_221).strip()
                    lnk_val_221 = link_221.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_221, d221.get("comentarios", ""))

                    # Quesito meramente informativo (pontuação fixa em 0.0)
                    save_resp_ifiscal(
                        qid="22.1",
                        valor=val_221_final,
                        pontos=0.0,
                        link=lnk_val_221,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["22.1"] = {
                        "valor": val_221_final,
                        "pontos": 0.0,
                        "link": lnk_val_221,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal (Varre valor principal e evidência)
                    links_atuais_val = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, val_221_final or "")]
                    links_antigos_val = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, v_salvo_221 or "")]
                    
                    links_atuais_lnk = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_221 or "")]
                    links_antigos_lnk = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_221_salva or "")]

                    # Combinação dos links novos pendentes de auditoria
                    links_pendentes = []
                    if val_221_final != v_salvo_221 and links_atuais_val and links_atuais_val != links_antigos_val:
                        links_pendentes.extend(links_atuais_val)
                    if lnk_val_221 != evidencia_221_salva and links_atuais_lnk and links_atuais_lnk != links_antigos_lnk:
                        links_pendentes.extend(links_atuais_lnk)

                    if links_pendentes:
                        st.session_state[f"links_pendentes_22_1_{ano_sel}"] = list(set(links_pendentes))
                        st.session_state[f"gatilho_modal_22_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("URL/Valor e comentários do Quesito 22.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação informativa (sempre 0.0)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 22.1: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 22.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_22_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("22.1", st.session_state.get(f"links_pendentes_22_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_22_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 23.0 • REPASSES CORRENTES AO RGPS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_23_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 23.0 - Repasses Correntes RGPS ({ano_sel})", expanded=True):
                st.subheader("23.0 • Repasses Correntes (RGPS)")
                st.write(f"**Os repasses para o Regime Geral de Previdência Social (RGPS) da competência de {ano_sel} foram realizados em qual prazo?**")
                
                # Estado inicial / persistente
                d230 = res_data.get("23.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc230 = [
                    "Selecione...",
                    "Todos os repasses foram dentro do prazo legal – 00",
                    "A maior parte dos repasses recolhidos até 30 dias após o vencimento – -04 (perde 04 pontos)",
                    "A maior parte dos repasses recolhidos de 31 a 90 dias do vencimento – -15 (perde 15 pontos)",
                    "A maior parte dos repasses recolhidos acima de 90 dias do vencimento – -21 (perde 21 pontos)",
                    "Os repasses não foram realizados – -30 (perde 30 pontos)"
                ]
                
                valor_limpo_230 = str(d230.get("valor", "Selecione..."))
                if valor_limpo_230 not in opc230:
                    valor_limpo_230 = "Selecione..."
                
                evidencia_230_salva = d230.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_230 = f"rad_230_{ano_sel}_fiscal"
                chave_link_230 = f"txt_230_{ano_sel}_fiscal"
                chave_coment_230 = f"coment_23.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 23.0:", 
                        opc230, 
                        index=opc230.index(valor_limpo_230), 
                        key=chave_rad_230
                    )

                with c2:
                    link_230 = st.text_area(
                        f"Link/Evidência de Comprovantes de Repasse / GFIP / GPS ({ano_sel}):", 
                        value=evidencia_230_salva, 
                        key=chave_link_230, 
                        placeholder="Insira os links e evidências...",
                        height=140
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_230 = st.empty()
                    links_230_visuais = re.findall(REGEX_PURE_URL, link_230 or "")
                    if links_230_visuais:
                        placeholder_links_230.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_230_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("23.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 23.0", key=f"btn_salvar_23_0_{ano_sel}", type="primary"):
                    val_230_selecionado = st.session_state.get(chave_rad_230, valor_limpo_230)
                    lnk_val_230 = link_230.strip()

                    # Cálculo da pontuação conforme a opção selecionada
                    if "dentro do prazo" in val_230_selecionado:
                        pts_230 = 0.0
                    elif "até 30 dias" in val_230_selecionado:
                        pts_230 = -4.0
                    elif "31 a 90 dias" in val_230_selecionado:
                        pts_230 = -15.0
                    elif "acima de 90 dias" in val_230_selecionado:
                        pts_230 = -21.0
                    elif "não foram realizados" in val_230_selecionado:
                        pts_230 = -30.0
                    else:
                        pts_230 = 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_230, d230.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="23.0",
                        valor=val_230_selecionado,
                        pontos=pts_230,
                        link=lnk_val_230,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["23.0"] = {
                        "valor": val_230_selecionado,
                        "pontos": pts_230,
                        "link": lnk_val_230,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_230 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_230_salva or "")]

                    if lnk_val_230 != evidencia_230_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_23_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_23_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 23.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação
                pts_atuais_230 = d230.get("pontos", 0.0)
                cor_p230 = "#dc3545" if pts_atuais_230 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_p230}; font-weight:bold;'>"
                    f"📊 Impacto 23.0: {pts_atuais_230} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 23.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_23_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("23.0", st.session_state.get(f"links_pendentes_23_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_23_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 24.0 • ADESÃO A PARCELAMENTOS DE DÉBITOS (RGPS)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_24_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 24.0 - Adesão a Parcelamento RGPS ({ano_sel})", expanded=True):
                st.subheader("24.0 • Identificação de Parcelamentos")
                st.write(f"**A Prefeitura aderiu a algum parcelamento de encargos sociais (Regime Geral de Previdência Social - RGPS)?**")
                
                # Estado inicial / persistente
                d240 = res_data.get("24.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc240 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_240 = str(d240.get("valor", "Selecione..."))
                if valor_limpo_240 not in opc240:
                    valor_limpo_240 = "Selecione..."
                
                evidencia_240_salva = d240.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_240 = f"rad_240_{ano_sel}_fiscal"
                chave_link_240 = f"txt_240_{ano_sel}_fiscal"
                chave_coment_240 = f"coment_24.0_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio(
                        "Selecione 24.0:", 
                        opc240, 
                        index=opc240.index(valor_limpo_240), 
                        key=chave_rad_240
                    )

                with c4:
                    link_240 = st.text_area(
                        f"Link/Evidência do Termo de Parcelamento / Extrato da RFB ({ano_sel}):", 
                        value=evidencia_240_salva, 
                        key=chave_link_240, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_240 = st.empty()
                    links_240_visuais = re.findall(REGEX_PURE_URL, link_240 or "")
                    if links_240_visuais:
                        placeholder_links_240.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_240_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("24.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 24.0", key=f"btn_salvar_24_0_{ano_sel}", type="primary"):
                    val_240_selecionado = st.session_state.get(chave_rad_240, valor_limpo_240)
                    lnk_val_240 = link_240.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_240, d240.get("comentarios", ""))

                    # Quesito qualificador/informativo (pontuação 0.0)
                    save_resp_ifiscal(
                        qid="24.0",
                        valor=val_240_selecionado,
                        pontos=0.0,
                        link=lnk_val_240,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["24.0"] = {
                        "valor": val_240_selecionado,
                        "pontos": 0.0,
                        "link": lnk_val_240,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_240 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_240_salva or "")]

                    if lnk_val_240 != evidencia_240_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_24_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_24_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 24.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação informativa (sempre 0.0)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 24.0: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 24.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_24_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("24.0", st.session_state.get(f"links_pendentes_24_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_24_0_{ano_sel}"] = False


        # =============================================================================
        # BLOCO ISOLADO: QUESITO 24.1 • SITUAÇÃO DAS PARCELAS DE PARCELAMENTO (RGPS)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_24_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 24.1 - Adimplemento das Parcelas RGPS ({ano_sel})", expanded=True):
                st.subheader("24.1 • Regularidade das Parcelas")
                st.write(f"**As parcelas referentes ao parcelamento para o Regime Geral de Previdência Social (RGPS) com vencimento em {ano_sel} foram realizadas em qual prazo?**")
                
                # Estado inicial / persistente
                d241 = res_data.get("24.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc241 = [
                    "Selecione...",
                    "Todas as parcelas foram recolhidas dentro do prazo legal – 00",
                    "A maior parte das parcelas recolhidas até 30 dias após o vencimento – -04 (perde 04 pontos)",
                    "A maior parte das parcelas recolhidas de 31 a 90 dias do vencimento – -15 (perde 15 pontos)",
                    "A maior parte das parcelas recolhidas acima de 90 dias do vencimento – -21 (perde 21 pontos)",
                    "As parcelas não foram recolhidas – -30 (perde 30 pontos)"
                ]
                
                valor_limpo_241 = str(d241.get("valor", "Selecione..."))
                if valor_limpo_241 not in opc241:
                    valor_limpo_241 = "Selecione..."
                
                evidencia_241_salva = d241.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_241 = f"rad_241_{ano_sel}_fiscal"
                chave_link_241 = f"txt_241_{ano_sel}_fiscal"
                chave_coment_241 = f"coment_24.1_{ano_sel}_fiscal"

                c5, c6 = st.columns([1, 1])
                with c5:
                    st.radio(
                        "Selecione 24.1:", 
                        opc241, 
                        index=opc241.index(valor_limpo_241), 
                        key=chave_rad_241
                    )

                with c6:
                    link_241 = st.text_area(
                        f"Link/Evidência de Comprovantes de Pagamento do Parcelamento ({ano_sel}):", 
                        value=evidencia_241_salva, 
                        key=chave_link_241, 
                        placeholder="Insira os links e evidências...",
                        height=140
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_241 = st.empty()
                    links_241_visuais = re.findall(REGEX_PURE_URL, link_241 or "")
                    if links_241_visuais:
                        placeholder_links_241.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_241_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("24.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 24.1", key=f"btn_salvar_24_1_{ano_sel}", type="primary"):
                    val_241_selecionado = st.session_state.get(chave_rad_241, valor_limpo_241)
                    lnk_val_241 = link_241.strip()

                    # Cálculo da pontuação conforme a opção selecionada
                    if "dentro do prazo" in val_241_selecionado:
                        pts_241 = 0.0
                    elif "até 30 dias" in val_241_selecionado:
                        pts_241 = -4.0
                    elif "31 a 90 dias" in val_241_selecionado:
                        pts_241 = -15.0
                    elif "acima de 90 dias" in val_241_selecionado:
                        pts_241 = -21.0
                    elif "não foram recolhidas" in val_241_selecionado:
                        pts_241 = -30.0
                    else:
                        pts_241 = 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_241, d241.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="24.1",
                        valor=val_241_selecionado,
                        pontos=pts_241,
                        link=lnk_val_241,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["24.1"] = {
                        "valor": val_241_selecionado,
                        "pontos": pts_241,
                        "link": lnk_val_241,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_241 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_241_salva or "")]

                    if lnk_val_241 != evidencia_241_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_24_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_24_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 24.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação
                pts_atuais_241 = d241.get("pontos", 0.0)
                cor_p241 = "#dc3545" if pts_atuais_241 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_p241}; font-weight:bold;'>"
                    f"📊 Impacto 24.1: {pts_atuais_241} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 24.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_24_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("24.1", st.session_state.get(f"links_pendentes_24_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_24_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 25.0 • COMPENSAÇÃO DE ENCARGOS SOCIAIS (RFB)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_25_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 25.0 - Compensação de Encargos Sociais ({ano_sel})", expanded=True):
                st.subheader("25.0 • Compensações Junto à RFB")
                st.write(f"**O Município efetuou, no exercício de {ano_sel}, compensação de encargos sociais junto à Receita Federal do Brasil?**")
                
                # Estado inicial / persistente
                d250 = res_data.get("25.0") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc250 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_250 = str(d250.get("valor", "Selecione..."))
                if valor_limpo_250 not in opc250:
                    valor_limpo_250 = "Selecione..."
                
                evidencia_250_salva = d250.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_250 = f"rad_250_{ano_sel}_fiscal"
                chave_link_250 = f"txt_250_{ano_sel}_fiscal"
                chave_coment_250 = f"coment_25.0_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio(
                        "Selecione 25.0:", 
                        opc250, 
                        index=opc250.index(valor_limpo_250), 
                        key=chave_rad_250
                    )

                with c2:
                    link_250 = st.text_area(
                        f"Link/Evidência da Declaração de Compensação (PER/DCOMP) ({ano_sel}):", 
                        value=evidencia_250_salva, 
                        key=chave_link_250, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_250 = st.empty()
                    links_250_visuais = re.findall(REGEX_PURE_URL, link_250 or "")
                    if links_250_visuais:
                        placeholder_links_250.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_250_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("25.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 25.0", key=f"btn_salvar_25_0_{ano_sel}", type="primary"):
                    val_250_selecionado = st.session_state.get(chave_rad_250, valor_limpo_250)
                    lnk_val_250 = link_250.strip()

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_250, d250.get("comentarios", ""))

                    # Quesito qualificador/informativo (pontuação 0.0)
                    save_resp_ifiscal(
                        qid="25.0",
                        valor=val_250_selecionado,
                        pontos=0.0,
                        link=lnk_val_250,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["25.0"] = {
                        "valor": val_250_selecionado,
                        "pontos": 0.0,
                        "link": lnk_val_250,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_250 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_250_salva or "")]

                    if lnk_val_250 != evidencia_250_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_25_0_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_25_0_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 25.0 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação informativa (sempre 0.0)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 25.0: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 25.0 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_25_0_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("25.0", st.session_state.get(f"links_pendentes_25_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_25_0_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 25.1 • AUTORIZAÇÃO FORMAL DE COMPENSAÇÃO (RFB)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_25_1_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 25.1 - Lastro Formal das Compensações ({ano_sel})", expanded=True):
                st.subheader("25.1 • Regularidade / Decisão Autorizativa")
                st.write("**Houve autorização formal administrativa da Receita Federal do Brasil (RFB) ou decisão judicial para realizar as compensações?**")
                
                # Estado inicial / persistente
                d251 = res_data.get("25.1") or {"valor": "Selecione...", "pontos": 0.0, "link": "", "comentarios": ""}
                opc251 = ["Selecione...", "Sim – 00", "Não – -25 (perde 25 pontos)"]
                
                valor_limpo_251 = str(d251.get("valor", "Selecione..."))
                if valor_limpo_251 not in opc251:
                    valor_limpo_251 = "Selecione..."
                
                evidencia_251_salva = d251.get("link", "")

                # Chaves padronizadas para session_state
                chave_rad_251 = f"rad_251_{ano_sel}_fiscal"
                chave_link_251 = f"txt_251_{ano_sel}_fiscal"
                chave_coment_251 = f"coment_25.1_{ano_sel}_fiscal"

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio(
                        "Selecione 25.1:", 
                        opc251, 
                        index=opc251.index(valor_limpo_251), 
                        key=chave_rad_251
                    )

                with c4:
                    link_251 = st.text_area(
                        f"Link/Evidência do Ato Autorizativo ou Sentença Judicial ({ano_sel}):", 
                        value=evidencia_251_salva, 
                        key=chave_link_251, 
                        placeholder="Insira os links e evidências...",
                        height=100
                    )
                    
                    # Detecção e exibição visual dos links no campo
                    placeholder_links_251 = st.empty()
                    links_251_visuais = re.findall(REGEX_PURE_URL, link_251 or "")
                    if links_251_visuais:
                        placeholder_links_251.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_251_visuais
                                ]
                            )
                        )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("25.1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 25.1", key=f"btn_salvar_25_1_{ano_sel}", type="primary"):
                    val_251_selecionado = st.session_state.get(chave_rad_251, valor_limpo_251)
                    lnk_val_251 = link_251.strip()

                    # Cálculo da pontuação conforme a escolha
                    if "Sim" in val_251_selecionado:
                        pts_251 = 0.0
                    elif "Não" in val_251_selecionado:
                        pts_251 = -25.0
                    else:
                        pts_251 = 0.0

                    # Captura o comentário atualizado da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_251, d251.get("comentarios", ""))

                    # Salva no banco de dados via função do iFiscal
                    save_resp_ifiscal(
                        qid="25.1",
                        valor=val_251_selecionado,
                        pontos=pts_251,
                        link=lnk_val_251,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["25.1"] = {
                        "valor": val_251_selecionado,
                        "pontos": pts_251,
                        "link": lnk_val_251,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para acionamento do modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_251 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_251_salva or "")]

                    if lnk_val_251 != evidencia_251_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_25_1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_25_1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Opção e comentários do Quesito 25.1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação atual
                pts_atuais_251 = d251.get("pontos", 0.0)
                cor_p251 = "#dc3545" if pts_atuais_251 < 0 else "#28a745"
                st.markdown(
                    f"<span style='color:{cor_p251}; font-weight:bold;'>"
                    f"📊 Impacto 25.1: {pts_atuais_251} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL 25.1 (Executado fora da caixa do container)
        if st.session_state.get(f"gatilho_modal_25_1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("25.1", st.session_state.get(f"links_pendentes_25_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_25_1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 26.0 • CONSIDERAÇÕES FINAIS / OUVIDORIA
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_26_0_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 26.0 - Impressões Finais ({ano_sel})", expanded=True):
                st.subheader("26.0 • Ouvidoria e Espaço Crítico")
                st.write("**Gostaria de registrar suas impressões, comentários e sugestões a respeito do presente questionário?**")
                st.caption("ℹ️ *Utilize o espaço abaixo de forma livre para documentar observações sobre a usabilidade, críticas ou pontos de melhoria.*")
                
                # Estado inicial / persistente
                d260 = res_data.get("26.0") or {"valor": "", "pontos": 0.0, "link": "", "comentarios": ""}
                v_salvo_260 = str(d260.get("valor", ""))

                # Chaves padronizadas para session_state
                chave_txt_260 = f"txt_260_val_{ano_sel}_fiscal"
                chave_coment_260 = f"coment_26.0_{ano_sel}_fiscal"

                impressoes_260 = st.text_area(
                    "Impressões, comentários e sugestões:", 
                    value=v_salvo_260, 
                    key=chave_txt_260, 
                    placeholder="Digite aqui suas observações sobre o questionário...",
                    height=180
                )

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("26.0", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Quesito 26.0", key=f"btn_salvar_26_0_{ano_sel}", type="primary"):
                    val_260_digitado = impressoes_260.strip()

                    # Captura o comentário adicional da sessão
                    comentario_para_salvar = st.session_state.get(chave_coment_260, d260.get("comentarios", ""))

                    # Quesito de ouvidoria / informativo (pontuação 0.0)
                    save_resp_ifiscal(
                        qid="26.0",
                        valor=val_260_digitado,
                        pontos=0.0,
                        link="",
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza o estado local res_data
                    res_data["26.0"] = {
                        "valor": val_260_digitado,
                        "pontos": 0.0,
                        "link": "",
                        "comentarios": comentario_para_salvar
                    }

                    st.cache_data.clear()
                    st.toast("Impressões e observações do Quesito 26.0 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição de pontuação (sempre 0.0)
                st.markdown(
                    "<span style='color:#28a745; font-weight:bold;'>"
                    "📊 Impacto 26.0: 0.0 pontos aplicados</span>",
                    unsafe_allow_html=True
                )

    with aba_quest:
        st.info("Preencha as informações fiscais e financeiras do município.")

    with aba_ext:
        st.info("📊 Módulo de Indicadores Financeiros (AUDESP / Dados Externos)")

        # -------------------------------------------------------------------------
        # SEÇÃO 8: INDICADORES FINANCEIROS (F1 A F18)
        # -------------------------------------------------------------------------
        st.markdown('<div class="section-header"><h3>8. Indicadores Financeiros (AUDESP)</h3></div>', unsafe_allow_html=True)

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F1 • ANÁLISE DA RECEITA (EXECUÇÃO ORÇAMENTÁRIA)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f1_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F1 - Análise da Receita ({ano_sel})", expanded=True):
                st.subheader("F1 • Análise da Receita (Execução Orçamentária) – Resultado Consolidado")
                st.write("**Divisão da receita arrecadada pela receita prevista atualizada (O / P = Q)**")
                
                # Tabela Oficial de Parâmetros e Pontuações do Indicador
                st.markdown("""
                | Resultado de $Q$ | Pontuação do Indicador |
                | :--- | :--- |
                | Maior ou igual a 1,5 | 0 |
                | Maior que 1,15 e menor que 1,5 | Graduação entre 75 e 0 |
                | Maior ou igual a 0,85 e menor ou igual a 1,15 | 75 |
                | Maior que 0,5 e menor que 0,85 | Graduação entre 0 e 75 |
                | Menor ou igual a 0,5 | 0 |
                """)
                
                # Memórias matemáticas oficiais
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regras de Distribuição Proporcional nos Intervalos:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 1,15 e menores que 1,5:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((Q – 1,5) * (-1) / 0,35) * 75</code> <br><i>Exemplo: se Q = 1,25, a nota do indicador será 53,57 pontos.</i></li>
                        <li style="margin-top: 8px;"><b>Para resultados maiores que 0,5 e menores que 0,85:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((Q – 0,5) / 0,35) * 75</code> <br><i>Exemplo: se Q = 0,75, a nota do indicador será 53,57 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função de conversão monetária BR para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente
                dF1 = res_data.get("F1") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_o, val_salvo_p = str(dF1.get("valor", "0.00/1.00")).split("/")
                    float_o = float(val_salvo_o)
                    float_p = float(val_salvo_p)
                except Exception:
                    float_o, float_p = 0.0, 1.0

                str_inicial_o = f"R$ {float_o:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_p = f"R$ {float_p:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f1_salva = dF1.get("link", "")

                # Chaves padronizadas para session_state
                chave_input_o = f"txt_f1_o_{ano_sel}_fiscal"
                chave_input_p = f"txt_f1_p_{ano_sel}_fiscal"
                chave_link_f1 = f"txt_f1_link_{ano_sel}_fiscal"
                chave_coment_f1 = f"coment_F1_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_o_str = st.text_input(
                        "Receita Arrecadada (O) - R$:",
                        value=str_inicial_o,
                        placeholder="Ex: 1.500.000,00",
                        key=chave_input_o
                    )
                    
                    input_p_str = st.text_input(
                        "Receita Prevista Atualizada (P) - R$:",
                        value=str_inicial_p,
                        placeholder="Ex: 1.250.000,00",
                        key=chave_input_p
                    )

                with c2:
                    link_f1 = st.text_area(
                        f"Link/Evidência (F1) ({ano_sel}):", 
                        value=evidencia_f1_salva, 
                        key=chave_link_f1, 
                        placeholder="Insira os links e evidências...",
                        height=130
                    )
                    
                    placeholder_links_f1 = st.empty()
                    links_f1_visuais = re.findall(REGEX_PURE_URL, link_f1 or "")
                    if links_f1_visuais:
                        placeholder_links_f1.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f1_visuais
                                ]
                            )
                        )

                # Exibição do cálculo projetado no momento
                v_arr_exib = converte_moeda_br_para_float(input_o_str)
                v_prev_exib = max(converte_moeda_br_para_float(input_p_str), 0.01)
                Q_exib = v_arr_exib / v_prev_exib

                if Q_exib >= 1.5 or Q_exib <= 0.5:
                    pts_exib = 0.0
                elif 0.85 <= Q_exib <= 1.15:
                    pts_exib = 75.0
                elif 1.15 < Q_exib < 1.5:
                    pts_exib = ((Q_exib - 1.5) * (-1) / 0.35) * 75
                else:
                    pts_exib = ((Q_exib - 0.5) / 0.35) * 75

                fmt_v_arr = f"R$ {v_arr_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                fmt_v_prev = f"R$ {v_prev_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Execução:</b> {fmt_v_arr} / {fmt_v_prev}<br>
                    📊 <b>Resultado do Indicador (Q):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{Q_exib:.4f}</code><br>
                    🎯 <b>Pontuação Calculada:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{pts_exib:.2f} pontos</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F1", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F1", key=f"btn_salvar_f1_{ano_sel}", type="primary"):
                    v_arr = converte_moeda_br_para_float(st.session_state.get(chave_input_o, input_o_str))
                    v_prev = max(converte_moeda_br_para_float(st.session_state.get(chave_input_p, input_p_str)), 0.01)

                    # Recálculo oficial no salvamento
                    Q_calc = v_arr / v_prev

                    if Q_calc >= 1.5 or Q_calc <= 0.5:
                        pts_f1 = 0.0
                    elif 0.85 <= Q_calc <= 1.15:
                        pts_f1 = 75.0
                    elif 1.15 < Q_calc < 1.5:
                        pts_f1 = ((Q_calc - 1.5) * (-1) / 0.35) * 75
                    else:
                        pts_f1 = ((Q_calc - 0.5) / 0.35) * 75

                    str_banco = f"{v_arr:.2f}/{v_prev:.2f}"
                    lnk_val_f1 = link_f1.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f1, dF1.get("comentarios", ""))

                    # Salva no banco de dados via iFiscal
                    save_resp_ifiscal(
                        qid="F1",
                        valor=str_banco,
                        pontos=pts_f1,
                        link=lnk_val_f1,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data
                    res_data["F1"] = {
                        "valor": str_banco,
                        "pontos": pts_f1,
                        "link": lnk_val_f1,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f1 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f1_salva or "")]

                    if lnk_val_f1 != evidencia_f1_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f1_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f1_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valores e cálculo do Indicador F1 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f1_salvos = float(dF1.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto F1: {pts_f1_salvos:.2f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F1 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f1_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F1", st.session_state.get(f"links_pendentes_f1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f1_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F2 • ANÁLISE DA DESPESA (EXECUÇÃO ORÇAMENTÁRIA)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f2_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F2 - Análise da Despesa ({ano_sel})", expanded=True):
                st.subheader("F2 • Análise da Despesa (Execução Orçamentária) – Resultado Consolidado")
                st.write("**Divisão da despesa executada pela despesa fixada final (R / S = T)**")
                
                # Tabela Oficial de Parâmetros e Pontuações do Indicador F2
                st.markdown("""
                | Resultado de $T$ | Pontuação do Indicador |
                | :--- | :--- |
                | Maior ou igual a 1,1 | 0 |
                | Maior que 1,0 e menor que 1,1 | Graduação entre 75 e 0 |
                | Maior ou igual a 0,9 e menor ou igual a 1,0 | 75 |
                | Maior que 0,5 e menor que 0,9 | Graduação entre 0 e 75 |
                | Menor ou igual a 0,5 | 0 |
                """)
                
                # Memórias matemáticas oficiais do indicador F2
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regras de Distribuição Proporcional nos Intervalos (Despesa):</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 1,0 e menores que 1,1:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((T – 1,1) * (-1) / 0,10) * 75</code> <br><i>Exemplo: se T = 1,05, a nota do indicador será 37,50 pontos.</i></li>
                        <li style="margin-top: 8px;"><b>Para resultados maiores que 0,5 e menores que 0,9:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((T – 0,5) / 0,40) * 75</code> <br><i>Exemplo: se T = 0,75, a nota do indicador será 46,88 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função de conversão monetária BR para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente
                dF2 = res_data.get("F2") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_r, val_salvo_s = str(dF2.get("valor", "0.00/1.00")).split("/")
                    float_r = float(val_salvo_r)
                    float_s = float(val_salvo_s)
                except Exception:
                    float_r, float_s = 0.0, 1.0

                str_inicial_r = f"R$ {float_r:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_s = f"R$ {float_s:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f2_salva = dF2.get("link", "")

                # Chaves padronizadas para session_state
                chave_input_r = f"txt_f2_r_{ano_sel}_fiscal"
                chave_input_s = f"txt_f2_s_{ano_sel}_fiscal"
                chave_link_f2 = f"txt_f2_link_{ano_sel}_fiscal"
                chave_coment_f2 = f"coment_F2_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_r_str = st.text_input(
                        "Despesa Executada (R) - R$:",
                        value=str_inicial_r,
                        placeholder="Ex: 1.050.000,00",
                        key=chave_input_r
                    )
                    
                    input_s_str = st.text_input(
                        "Despesa Fixada Final (S) - R$:",
                        value=str_inicial_s,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_s
                    )

                with c2:
                    link_f2 = st.text_area(
                        f"Link/Evidência (F2) ({ano_sel}):", 
                        value=evidencia_f2_salva, 
                        key=chave_link_f2, 
                        placeholder="Insira os links e evidências...",
                        height=130
                    )
                    
                    placeholder_links_f2 = st.empty()
                    links_f2_visuais = re.findall(REGEX_PURE_URL, link_f2 or "")
                    if links_f2_visuais:
                        placeholder_links_f2.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f2_visuais
                                ]
                            )
                        )

                # Exibição do cálculo projetado no momento
                v_exec_exib = converte_moeda_br_para_float(input_r_str)
                v_fix_exib = max(converte_moeda_br_para_float(input_s_str), 0.01)
                T_exib = v_exec_exib / v_fix_exib

                if T_exib >= 1.1 or T_exib <= 0.5:
                    pts_exib = 0.0
                elif 0.9 <= T_exib <= 1.0:
                    pts_exib = 75.0
                elif 1.0 < T_exib < 1.1:
                    pts_exib = ((T_exib - 1.1) * (-1) / 0.10) * 75
                else: # Faixa entre 0.5 e 0.9
                    pts_exib = ((T_exib - 0.5) / 0.40) * 75

                fmt_v_exec = f"R$ {v_exec_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                fmt_v_fix = f"R$ {v_fix_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Execução:</b> {fmt_v_exec} / {fmt_v_fix}<br>
                    📊 <b>Resultado do Indicador (T):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{T_exib:.4f}</code><br>
                    🎯 <b>Pontuação Calculada:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{pts_exib:.2f} pontos</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F2", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F2", key=f"btn_salvar_f2_{ano_sel}", type="primary"):
                    v_exec = converte_moeda_br_para_float(st.session_state.get(chave_input_r, input_r_str))
                    v_fix = max(converte_moeda_br_para_float(st.session_state.get(chave_input_s, input_s_str)), 0.01)

                    # Recálculo oficial no salvamento
                    T_calc = v_exec / v_fix

                    if T_calc >= 1.1 or T_calc <= 0.5:
                        pts_f2 = 0.0
                    elif 0.9 <= T_calc <= 1.0:
                        pts_f2 = 75.0
                    elif 1.0 < T_calc < 1.1:
                        pts_f2 = ((T_calc - 1.1) * (-1) / 0.10) * 75
                    else: # Faixa entre 0.5 e 0.9
                        pts_f2 = ((T_calc - 0.5) / 0.40) * 75

                    str_banco = f"{v_exec:.2f}/{v_fix:.2f}"
                    lnk_val_f2 = link_f2.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f2, dF2.get("comentarios", ""))

                    # Salva no banco de dados via iFiscal
                    save_resp_ifiscal(
                        qid="F2",
                        valor=str_banco,
                        pontos=pts_f2,
                        link=lnk_val_f2,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data
                    res_data["F2"] = {
                        "valor": str_banco,
                        "pontos": pts_f2,
                        "link": lnk_val_f2,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f2 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f2_salva or "")]

                    if lnk_val_f2 != evidencia_f2_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f2_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f2_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valores e cálculo do Indicador F2 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f2_salvos = float(dF2.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto F2: {pts_f2_salvos:.2f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F2 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f2_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F2", st.session_state.get(f"links_pendentes_f2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f2_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F3 • ANÁLISE DO RESULTADO DA EXECUÇÃO ORÇAMENTÁRIA
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f3_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F3 - Análise do Resultado da Execução Orçamentária ({ano_sel})", expanded=True):
                st.subheader("F3 • Análise do Resultado da Execução Orçamentária – Resultado Consolidado")
                st.write("**Razão entre a despesa executada e a receita arrecadada (R / O = V)**")
                
                # Tabela Oficial de Parâmetros e Pontuações do Indicador F3
                st.markdown("""
                | Resultado de $V$ | Condição de Cobertura Contábil | Pontuação do Indicador |
                | :--- | :--- | :--- |
                | Maior ou igual a 1,2 | Qualquer caso | 0 |
                | Maior que 1,1 e menor que 1,2 | **Com** cobertura do déficit por Superávit | Graduação entre 100 e 0 |
                | Maior que 1,0 e menor que 1,2 | **Sem** cobertura do déficit por Superávit | 0 |
                | Maior que 1,0 e menor ou igual a 1,1 | **Com** cobertura do déficit por Superávit | 100 |
                | Maior ou igual a 0,9 e menor ou igual a 1,0 | Qualquer caso | 100 |
                | Maior que 0,75 e menor que 0,9 | Qualquer caso | Graduação entre 0 e 100 |
                | Menor ou igual a 0,75 | Qualquer caso | 0 |
                """)
                
                # Memórias matemáticas oficiais do indicador F3
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Fórmulas de Distribuição nos Intervalos e Regra de Cobertura ($X$):</b></p>
                    <p style="font-size: 13px; margin-bottom: 8px;"><i>Déficit ($V > 1$): O módulo da diferença $|O - R| = X$ é comparado aos créditos abertos por superávit financeiro. Se o crédito for igual ou maior, há cobertura financeira.</i></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Se V está entre 1,1 e 1,2 (Com Cobertura):</b> <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((V – 1,2) * (-1) / 0,10) * 100</code> <br><i>Exemplo: se V = 1,15, a nota será 50,00 pontos.</i></li>
                        <li style="margin-top: 8px;"><b>Se V está entre 0,75 e 0,90:</b> <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((V – 0,75) / 0,15) * 100</code> <br><i>Exemplo: se V = 0,80, a nota será 33,33 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função de conversão monetária BR para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (Estrutura R/O/C)
                dF3 = res_data.get("F3") or {"valor": "0.00/1.00/0.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_r, val_salvo_o, val_salvo_c = str(dF3.get("valor", "0.00/1.00/0.00")).split("/")
                    float_r = float(val_salvo_r)
                    float_o = float(val_salvo_o)
                    float_c = float(val_salvo_c)
                except Exception:
                    float_r, float_o, float_c = 0.0, 1.0, 0.0

                str_inicial_r = f"R$ {float_r:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_o = f"R$ {float_o:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_c = f"R$ {float_c:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f3_salva = dF3.get("link", "")

                # Chaves padronizadas para session_state
                chave_input_r = f"txt_f3_r_{ano_sel}_fiscal"
                chave_input_o = f"txt_f3_o_{ano_sel}_fiscal"
                chave_input_c = f"txt_f3_c_{ano_sel}_fiscal"
                chave_link_f3 = f"txt_f3_link_{ano_sel}_fiscal"
                chave_coment_f3 = f"coment_F3_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_r_str = st.text_input(
                        "Despesa Executada (R) - R$:",
                        value=str_inicial_r,
                        placeholder="Ex: 1.050.000,00",
                        key=chave_input_r
                    )
                    
                    input_o_str = st.text_input(
                        "Receita Arrecadada (O) - R$:",
                        value=str_inicial_o,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_o
                    )

                    input_c_str = st.text_input(
                        "Créditos por Superávit Financeiro - R$:",
                        value=str_inicial_c,
                        placeholder="Ex: 50.000,00",
                        key=chave_input_c
                    )

                with c2:
                    link_f3 = st.text_area(
                        f"Link/Evidência (F3) ({ano_sel}):", 
                        value=evidencia_f3_salva, 
                        key=chave_link_f3, 
                        placeholder="Insira os links e evidências...",
                        height=215
                    )
                    
                    placeholder_links_f3 = st.empty()
                    links_f3_visuais = re.findall(REGEX_PURE_URL, link_f3 or "")
                    if links_f3_visuais:
                        placeholder_links_f3.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f3_visuais
                                ]
                            )
                        )

                # Exibição do cálculo projetado no momento
                v_exec_exib = converte_moeda_br_para_float(input_r_str)
                v_arrec_exib = max(converte_moeda_br_para_float(input_o_str), 0.01)
                v_cred_superavit_exib = converte_moeda_br_para_float(input_c_str)

                V_exib = v_exec_exib / v_arrec_exib
                X_exib = abs(v_arrec_exib - v_exec_exib)
                tem_cobertura_exib = v_cred_superavit_exib >= X_exib

                # Motor de regras para exibição visual
                if V_exib >= 1.2:
                    pts_exib = 0.0
                elif 1.1 < V_exib < 1.2:
                    pts_exib = ((V_exib - 1.2) * (-1) / 0.10) * 100 if tem_cobertura_exib else 0.0
                elif 1.0 < V_exib <= 1.1:
                    pts_exib = 100.0 if tem_cobertura_exib else 0.0
                elif 0.9 <= V_exib <= 1.0:
                    pts_exib = 100.0
                elif 0.75 < V_exib < 0.9:
                    pts_exib = ((V_exib - 0.75) / 0.15) * 100
                else: # V_exib <= 0.75
                    pts_exib = 0.0

                fmt_v_exec = f"R$ {v_exec_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                fmt_v_arrec = f"R$ {v_arrec_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                fmt_X = f"R$ {X_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                status_cobertura_exib = "🟢 Déficit Coberto por Superávit" if tem_cobertura_exib else "🔴 Déficit Não Coberto"
                if V_exib <= 1.0:
                    status_cobertura_exib = "🔵 Superávit Orçamentário Corrente"

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Análise Contábil:</b> {fmt_v_exec} / {fmt_v_arrec}<br>
                    📊 <b>Resultado do Indicador (V):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{V_exib:.4f}</code><br>
                    ⚖️ <b>Diferença em Módulo (X):</b> {fmt_X} | <b>Situação:</b> <i>{status_cobertura_exib}</i><br>
                    🎯 <b>Pontuação Calculada:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{pts_exib:.2f} pontos</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F3", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F3", key=f"btn_salvar_f3_{ano_sel}", type="primary"):
                    v_exec = converte_moeda_br_para_float(st.session_state.get(chave_input_r, input_r_str))
                    v_arrec = max(converte_moeda_br_para_float(st.session_state.get(chave_input_o, input_o_str)), 0.01)
                    v_cred_superavit = converte_moeda_br_para_float(st.session_state.get(chave_input_c, input_c_str))

                    # Recálculo oficial no salvamento
                    V_calc = v_exec / v_arrec
                    X_calc = abs(v_arrec - v_exec)
                    tem_cobertura_calc = v_cred_superavit >= X_calc

                    if V_calc >= 1.2:
                        pts_f3 = 0.0
                    elif 1.1 < V_calc < 1.2:
                        pts_f3 = ((V_calc - 1.2) * (-1) / 0.10) * 100 if tem_cobertura_calc else 0.0
                    elif 1.0 < V_calc <= 1.1:
                        pts_f3 = 100.0 if tem_cobertura_calc else 0.0
                    elif 0.9 <= V_calc <= 1.0:
                        pts_f3 = 100.0
                    elif 0.75 < V_calc < 0.9:
                        pts_f3 = ((V_calc - 0.75) / 0.15) * 100
                    else: # V_calc <= 0.75
                        pts_f3 = 0.0

                    str_banco = f"{v_exec:.2f}/{v_arrec:.2f}/{v_cred_superavit:.2f}"
                    lnk_val_f3 = link_f3.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f3, dF3.get("comentarios", ""))

                    # Salva no banco de dados via iFiscal
                    save_resp_ifiscal(
                        qid="F3",
                        valor=str_banco,
                        pontos=pts_f3,
                        link=lnk_val_f3,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data
                    res_data["F3"] = {
                        "valor": str_banco,
                        "pontos": pts_f3,
                        "link": lnk_val_f3,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f3 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f3_salva or "")]

                    if lnk_val_f3 != evidencia_f3_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f3_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f3_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valores e cálculo do Indicador F3 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f3_salvos = float(dF3.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto F3: {pts_f3_salvos:.2f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F3 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f3_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F3", st.session_state.get(f"links_pendentes_f3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f3_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F4 • ANÁLISE DO ESFORÇO PARA PAGAMENTO DE RESTOS A PAGAR
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f4_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F4 - Análise do Esforço para Pagamento de Restos a Pagar ({ano_sel})", expanded=True):
                st.subheader("F4 • Análise do Esforço para Pagamento de Restos a Pagar até o Bimestre")
                st.write("**Divisão dos pagamentos realizados pela posição inicial líquida de cancelamentos [A / (B - C) = Z]**")
                
                # Tabela Oficial de Parâmetros e Pontuações do Indicador F4
                st.markdown("""
                | Resultado de $Z$ | Pontuação do Indicador |
                | :--- | :--- |
                | Maior ou igual a 0,95 | 25 |
                | Maior que 0,75 e menor que 0,95 | Graduação entre 0 e 25 |
                | Menor ou igual a 0,75 | 0 |
                """)
                
                # Memórias matemáticas oficiais do indicador F4
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 0,75 e menores que 0,95:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((Z – 0,75) / 0,20) * 25</code> <br><i>Exemplo: se Z = 0,80, a nota do indicador será 6,25 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função de conversão monetária BR para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (Estrutura A/B/C)
                dF4 = res_data.get("F4") or {"valor": "0.00/1.00/0.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_a, val_salvo_b, val_salvo_c = str(dF4.get("valor", "0.00/1.00/0.00")).split("/")
                    float_a = float(val_salvo_a)
                    float_b = float(val_salvo_b)
                    float_c = float(val_salvo_c)
                except Exception:
                    float_a, float_b, float_c = 0.0, 1.0, 0.0

                str_inicial_a = f"R$ {float_a:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_b = f"R$ {float_b:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_c = f"R$ {float_c:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f4_salva = dF4.get("link", "")

                # Chaves padronizadas para session_state
                chave_input_a = f"txt_f4_a_{ano_sel}_fiscal"
                chave_input_b = f"txt_f4_b_{ano_sel}_fiscal"
                chave_input_c = f"txt_f4_c_{ano_sel}_fiscal"
                chave_link_f4 = f"txt_f4_link_{ano_sel}_fiscal"
                chave_coment_f4 = f"coment_F4_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_a_str = st.text_input(
                        "Pagamentos Realizados (A) - R$:",
                        value=str_inicial_a,
                        placeholder="Ex: 750.000,00",
                        key=chave_input_a
                    )
                    
                    input_b_str = st.text_input(
                        "Posição Inicial de Restos a Pagar (B) - R$:",
                        value=str_inicial_b,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_b
                    )

                    input_c_str = st.text_input(
                        "Cancelamentos no Exercício (C) - R$:",
                        value=str_inicial_c,
                        placeholder="Ex: 50.000,00",
                        key=chave_input_c
                    )

                with c2:
                    link_f4 = st.text_area(
                        f"Link/Evidência (F4 - Item GF26 AUDESP) ({ano_sel}):", 
                        value=evidencia_f4_salva, 
                        key=chave_link_f4, 
                        placeholder="Insira os links e evidências...",
                        height=215
                    )
                    
                    placeholder_links_f4 = st.empty()
                    links_f4_visuais = re.findall(REGEX_PURE_URL, link_f4 or "")
                    if links_f4_visuais:
                        placeholder_links_f4.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f4_visuais
                                ]
                            )
                        )

                # Exibição do cálculo projetado no momento
                v_pago_exib = converte_moeda_br_para_float(input_a_str)
                v_pos_inicial_exib = converte_moeda_br_para_float(input_b_str)
                v_cancelado_exib = converte_moeda_br_para_float(input_c_str)

                posicao_liquida_exib = max(v_pos_inicial_exib - v_cancelado_exib, 0.01)
                Z_exib = v_pago_exib / posicao_liquida_exib

                if Z_exib >= 0.95:
                    pts_exib = 25.0
                elif 0.75 < Z_exib < 0.95:
                    pts_exib = ((Z_exib - 0.75) / 0.20) * 25.0
                else: # Z_exib <= 0.75
                    pts_exib = 0.0

                fmt_v_pago = f"R$ {v_pago_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                fmt_v_pos_inicial = f"R$ {v_pos_inicial_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                fmt_v_cancelado = f"R$ {v_cancelado_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo do Esforço:</b> {fmt_v_pago} / ({fmt_v_pos_inicial} - {fmt_v_cancelado})<br>
                    📊 <b>Resultado do Indicador (Z):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{Z_exib:.4f}</code><br>
                    🎯 <b>Pontuação Calculada:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{pts_exib:.2f} pontos</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F4", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F4", key=f"btn_salvar_f4_{ano_sel}", type="primary"):
                    v_pago = converte_moeda_br_para_float(st.session_state.get(chave_input_a, input_a_str))
                    v_pos_inicial = converte_moeda_br_para_float(st.session_state.get(chave_input_b, input_b_str))
                    v_cancelado = converte_moeda_br_para_float(st.session_state.get(chave_input_c, input_c_str))

                    # Recálculo oficial no salvamento
                    posicao_liquida = max(v_pos_inicial - v_cancelado, 0.01)
                    Z_calc = v_pago / posicao_liquida

                    if Z_calc >= 0.95:
                        pts_f4 = 25.0
                    elif 0.75 < Z_calc < 0.95:
                        pts_f4 = ((Z_calc - 0.75) / 0.20) * 25.0
                    else: # Z_calc <= 0.75
                        pts_f4 = 0.0

                    str_banco = f"{v_pago:.2f}/{v_pos_inicial:.2f}/{v_cancelado:.2f}"
                    lnk_val_f4 = link_f4.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f4, dF4.get("comentarios", ""))

                    # Salva no banco de dados via iFiscal
                    save_resp_ifiscal(
                        qid="F4",
                        valor=str_banco,
                        pontos=pts_f4,
                        link=lnk_val_f4,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data
                    res_data["F4"] = {
                        "valor": str_banco,
                        "pontos": pts_f4,
                        "link": lnk_val_f4,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f4 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f4_salva or "")]

                    if lnk_val_f4 != evidencia_f4_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f4_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f4_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valores e cálculo do Indicador F4 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f4_salvos = float(dF4.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto F4: {pts_f4_salvos:.2f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F4 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f4_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F4", st.session_state.get(f"links_pendentes_f4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f4_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F5 • ANÁLISE DO NÍVEL DE CANCELAMENTO DE RESTOS A PAGAR
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f5_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F5 - Análise do Nível de Cancelamento de Restos a Pagar ({ano_sel})", expanded=True):
                st.subheader("F5 • Análise do Nível de Cancelamento de Restos a Pagar")
                st.write("**Divisão dos cancelamentos realizados pela posição inicial de restos a pagar [C / B = K]**")
                
                # Tabela Oficial de Parâmetros e Pontuações do Indicador F5
                st.markdown("""
                | Resultado de $K$ | Pontuação do Indicador |
                | :--- | :--- |
                | Maior ou igual a 0,20 | 0 |
                | Maior que 0,05 e menor que 0,20 | Graduação entre 0 e 25 |
                | Menor ou igual a 0,05 | 25 |
                """)
                
                # Memórias matemáticas oficiais do indicador F5
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 0,05 e menores que 0,20:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((0,20 – K) / 0,15) * 25</code> <br><i>Exemplo: se K = 0,06, a nota do indicador será 23,33 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função de conversão monetária BR para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (Estrutura C/B)
                dF5 = res_data.get("F5") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_c, val_salvo_b = str(dF5.get("valor", "0.00/1.00")).split("/")
                    float_c = float(val_salvo_c)
                    float_b = float(val_salvo_b)
                except Exception:
                    float_c, float_b = 0.0, 1.0

                str_inicial_c = f"R$ {float_c:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_b = f"R$ {float_b:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f5_salva = dF5.get("link", "")

                # Chaves padronizadas para session_state
                chave_input_c = f"txt_f5_c_{ano_sel}_fiscal"
                chave_input_b = f"txt_f5_b_{ano_sel}_fiscal"
                chave_link_f5 = f"txt_f5_link_{ano_sel}_fiscal"
                chave_coment_f5 = f"coment_F5_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_c_str = st.text_input(
                        "Cancelamentos no Exercício (C) - R$:",
                        value=str_inicial_c,
                        placeholder="Ex: 50.000,00",
                        key=chave_input_c
                    )

                    input_b_str = st.text_input(
                        "Posição Inicial de Restos a Pagar (B) - R$:",
                        value=str_inicial_b,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_b
                    )

                with c2:
                    link_f5 = st.text_area(
                        f"Link/Evidência (F5 - Item GF26 AUDESP) ({ano_sel}):", 
                        value=evidencia_f5_salva, 
                        key=chave_link_f5, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f5 = st.empty()
                    links_f5_visuais = re.findall(REGEX_PURE_URL, link_f5 or "")
                    if links_f5_visuais:
                        placeholder_links_f5.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f5_visuais
                                ]
                            )
                        )

                # Exibição do cálculo projetado no momento
                v_cancelado_exib = converte_moeda_br_para_float(input_c_str)
                v_pos_inicial_exib = max(converte_moeda_br_para_float(input_b_str), 0.01) # Evita divisão por zero

                K_exib = v_cancelado_exib / v_pos_inicial_exib

                if K_exib >= 0.20:
                    pts_exib = 0.0
                elif 0.05 < K_exib < 0.20:
                    pts_exib = ((0.20 - K_exib) / 0.15) * 25.0
                else: # K_exib <= 0.05
                    pts_exib = 25.0

                fmt_v_cancelado = f"R$ {v_cancelado_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                fmt_v_pos_inicial = f"R$ {v_pos_inicial_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo do Nível de Cancelamento:</b> {fmt_v_cancelado} / {fmt_v_pos_inicial}<br>
                    📊 <b>Resultado do Indicador (K):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{K_exib:.4f}</code><br>
                    🎯 <b>Pontuação Calculada:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{pts_exib:.2f} pontos</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F5", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F5", key=f"btn_salvar_f5_{ano_sel}", type="primary"):
                    v_cancelado = converte_moeda_br_para_float(st.session_state.get(chave_input_c, input_c_str))
                    v_pos_inicial = max(converte_moeda_br_para_float(st.session_state.get(chave_input_b, input_b_str)), 0.01)

                    # Recálculo oficial no salvamento
                    K_calc = v_cancelado / v_pos_inicial

                    if K_calc >= 0.20:
                        pts_f5 = 0.0
                    elif 0.05 < K_calc < 0.20:
                        pts_f5 = ((0.20 - K_calc) / 0.15) * 25.0
                    else: # K_calc <= 0.05
                        pts_f5 = 25.0

                    str_banco = f"{v_cancelado:.2f}/{v_pos_inicial:.2f}"
                    lnk_val_f5 = link_f5.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f5, dF5.get("comentarios", ""))

                    # Salva no banco de dados via iFiscal
                    save_resp_ifiscal(
                        qid="F5",
                        valor=str_banco,
                        pontos=pts_f5,
                        link=lnk_val_f5,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data
                    res_data["F5"] = {
                        "valor": str_banco,
                        "pontos": pts_f5,
                        "link": lnk_val_f5,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f5 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f5_salva or "")]

                    if lnk_val_f5 != evidencia_f5_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f5_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f5_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Valores e cálculo do Indicador F5 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f5_salvos = float(dF5.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto F5: {pts_f5_salvos:.2f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F5 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f5_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F5", st.session_state.get(f"links_pendentes_f5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f5_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F6 • DESPESAS COM PESSOAL – PODER EXECUTIVO (LRF)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f6_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F6 - Despesas com Pessoal – Poder Executivo ({ano_sel})", expanded=True):
                st.subheader("F6 • Despesas com Pessoal – Poder Executivo (LRF)")
                st.write("**Índice da Despesa Total com Pessoal do Executivo em relação à Receita Corrente Líquida (RCL)**")
                
                # Tabela Oficial de Parâmetros e Impactos do Indicador F6
                st.markdown("""
                | Resultado do Índice (%) | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Maior que 54,00% (Acima do Limite Legal) | 🚨 Rebaixa 1 faixa do i-Fiscal |
                | Entre 51,30% e 54,00% (Acima do Limite de Alerta) | ⚠️ -20 (Perde 20 pontos) |
                | Menor que 51,30% (Dentro do Limite) | ✅ 00 (Sem penalidades) |
                """)
                st.caption("ℹ️ *Dados obtidos a partir do Relatório de Instrução, item GF27 do Sistema AUDESP.*")
                st.markdown("<br>", unsafe_allow_html=True)

                # Função para converter string percentual BR para float decimal (ex: "51,30%" -> 0.513)
                def converte_percentual_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("%", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        val = float(limpo)
                        # Se o usuário digitou ex: 51.30 -> converte para 0.513
                        return val / 100.0 if val > 1.0 else val
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente
                dF6 = res_data.get("F6") or {"valor": "0.0000", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    float_f6 = float(dF6.get("valor", "0.0"))
                except Exception:
                    float_f6 = 0.0

                str_inicial_f6 = f"{float_f6 * 100:.2f}%".replace(".", ",")
                evidencia_f6_salva = dF6.get("link", "")

                # Chaves padronizadas para o session_state
                chave_input_f6 = f"txt_f6_indice_{ano_sel}_fiscal"
                chave_link_f6 = f"txt_f6_link_{ano_sel}_fiscal"
                chave_coment_f6 = f"coment_F6_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_f6_str = st.text_input(
                        "Índice de Despesa com Pessoal (%):",
                        value=str_inicial_f6,
                        placeholder="Ex: 51,30%",
                        key=chave_input_f6
                    )

                with c2:
                    link_f6 = st.text_area(
                        f"Link/Evidência (F6 - Item GF27 AUDESP) ({ano_sel}):", 
                        value=evidencia_f6_salva, 
                        key=chave_link_f6, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f6 = st.empty()
                    links_f6_visuais = re.findall(REGEX_PURE_URL, link_f6 or "")
                    if links_f6_visuais:
                        placeholder_links_f6.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f6_visuais
                                ]
                            )
                        )

                # Avaliação de projeção do índice no momento da digitação
                v_indice_exib = converte_percentual_br_para_float(input_f6_str)

                if v_indice_exib > 0.54:
                    pts_f6_exib = 0.0
                    texto_resultado_exib = "🚨 CRÍTICO: Maior que 54,00% (Gera Rebaixamento de Faixa Geral)"
                    estilo_status_exib = "color: #dc2626; font-weight: bold;"
                elif 0.513 <= v_indice_exib <= 0.54:
                    pts_f6_exib = -20.0
                    texto_resultado_exib = "⚠️ ALERTA: Entre 51,30% e 54,00% (Penalidade: -20,00 pontos)"
                    estilo_status_exib = "color: #d97706; font-weight: bold;"
                else:
                    pts_f6_exib = 0.0
                    texto_resultado_exib = "✅ REGULAR: Menor que 51,30% (Sem penalidades)"
                    estilo_status_exib = "color: #16a34a; font-weight: bold;"

                fmt_percentual = f"{v_indice_exib * 100:.2f}%".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📊 <b>Índice Calculado:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{fmt_percentual}</code><br>
                    ⚖️ <b>Status LRF (Projeção):</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F6", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F6", key=f"btn_salvar_f6_{ano_sel}", type="primary"):
                    v_indice = converte_percentual_br_para_float(st.session_state.get(chave_input_f6, input_f6_str))

                    # Regra oficial de enquadramento
                    if v_indice > 0.54:
                        pts_f6 = 0.0  # O rebaixamento da faixa do i-Fiscal é tratado na consolidação geral
                    elif 0.513 <= v_indice <= 0.54:
                        pts_f6 = -20.0
                    else:
                        pts_f6 = 0.0

                    str_banco = f"{v_indice:.4f}"
                    lnk_val_f6 = link_f6.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f6, dF6.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura iFiscal
                    save_resp_ifiscal(
                        qid="F6",
                        valor=str_banco,
                        pontos=pts_f6,
                        link=lnk_val_f6,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data
                    res_data["F6"] = {
                        "valor": str_banco,
                        "pontos": pts_f6,
                        "link": lnk_val_f6,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f6 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f6_salva or "")]

                    if lnk_val_f6 != evidencia_f6_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f6_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f6_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Índice do Indicador F6 salvo com sucesso!", icon="✅")
                    st.rerun()

                # Exibição da pontuação/impacto salvo
                pts_f6_salvos = float(dF6.get("pontos", 0.0))
                val_salvo_pct = float_f6 * 100.0

                if float_f6 > 0.54:
                    status_f6_tag = "<span style='color:#dc2626; font-weight:bold;'>🚨 Rebaixamento de Faixa Geral</span>"
                elif pts_f6_salvos < 0:
                    status_f6_tag = f"<span style='color:#d97706; font-weight:bold;'>⚠️ Penalidade: {pts_f6_salvos:.2f} pontos</span>"
                else:
                    status_f6_tag = "<span style='color:#28a745; font-weight:bold;'>✅ Sem Penalidade (0,00 pts)</span>"

                st.markdown(
                    f"📊 Impacto F6 Salvo ({val_salvo_pct:.2f}%): {status_f6_tag}",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F6 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f6_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F6", st.session_state.get(f"links_pendentes_f6_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f6_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F7 • DESPESAS COM PESSOAL – PODER LEGISLATIVO (LRF)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f7_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F7 - Despesas com Pessoal – Poder Legislativo ({ano_sel})", expanded=True):
                st.subheader("F7 • Despesas com Pessoal – Poder Legislativo (LRF)")
                st.write("**Índice da Despesa Total com Pessoal do Legislativo em relação à Receita Corrente Líquida (DPPL / RCL = AB)**")
                
                # Tabela Oficial de Parâmetros
                st.markdown(r"""
                | Resultado do Índice $AB$ (%) | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Maior que 6,00% ($> 0,06$) | 🚨 -10 (Perde 10 pontos) |
                | Entre 5,60% e 6,00% ($\ge 0,056$ e $\le 0,06$) | ⚠️ Graduação entre 0 e -10 pontos |
                | Menor que 5,60% ($< 0,056$) | ✅ 00 pontos (Sem penalidades) |
                """)
                
                # Memórias matemáticas oficiais do indicador F7
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo Crítico (Base Decimal):</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 5,70% (0,057) e menores ou iguais a 6,00% (0,060):</b> A graduação de penalidade é calculada estritamente sobre a base decimal. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AB – 0,057) / 0,003) * (-10)</code> <br><i>Exemplo: se AB = 5,80% (0,058), a perda será de -3,33 pontos. Se AB = 6,00% (0,060), atinge o teto de -10,00 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função de conversão de percentual para float decimal (base 1.0)
                def converte_percentual_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("%", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        val = float(limpo)
                        val_dec = val / 100.0 if val > 1.0 else val
                        return round(val_dec, 4)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente
                dF7 = res_data.get("F7") or {"valor": "0.0000", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    float_ab = float(dF7.get("valor", "0.0"))
                except Exception:
                    float_ab = 0.0

                str_inicial_ab = f"{float_ab * 100:.2f}%".replace(".", ",")
                evidencia_f7_salva = dF7.get("link", "")

                # Chaves padronizadas para session_state
                chave_input_f7 = f"txt_f7_ab_{ano_sel}_fiscal"
                chave_link_f7 = f"txt_f7_link_{ano_sel}_fiscal"
                chave_coment_f7 = f"coment_F7_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_ab_str = st.text_input(
                        "Índice de Pessoal do Legislativo (AB) - %:",
                        value=str_inicial_ab,
                        placeholder="Ex: 5,80%",
                        key=chave_input_f7
                    )

                with c2:
                    link_f7 = st.text_area(
                        f"Link/Evidência (F7 - Item GF27 AUDESP) ({ano_sel}):", 
                        value=evidencia_f7_salva, 
                        key=chave_link_f7, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f7 = st.empty()
                    links_f7_visuais = re.findall(REGEX_PURE_URL, link_f7 or "")
                    if links_f7_visuais:
                        placeholder_links_f7.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f7_visuais
                                ]
                            )
                        )

                # Cálculo projetado para exibição visual imediata
                v_indice_exib = converte_percentual_br_para_float(input_ab_str)

                if v_indice_exib > 0.0600:
                    pts_exib = -10.0
                    texto_resultado_exib = "🚨 CRÍTICO: Limite Máximo Extrapolado (> 6,00%)"
                    estilo_status_exib = "color: #dc2626; font-weight: bold;"
                elif 0.0570 <= v_indice_exib <= 0.0600:
                    pts_exib = ((v_indice_exib - 0.0570) / 0.0030) * (-10.0)
                    texto_resultado_exib = "⚠️ ALERTA DE GRADUAÇÃO (Fórmula Aplicada)"
                    estilo_status_exib = "color: #d97706; font-weight: bold;"
                elif 0.0560 <= v_indice_exib < 0.0570:
                    pts_exib = 0.0
                    texto_resultado_exib = "⚠️ Atenção: Faixa Prudencial de Alerta (Sem penalidade)"
                    estilo_status_exib = "color: #b45309;"
                else: # v_indice_exib < 0.0560
                    pts_exib = 0.0
                    texto_resultado_exib = "✅ REGULAR: Menor que 5,60%"
                    estilo_status_exib = "color: #16a34a; font-weight: bold;"

                fmt_percentual = f"{v_indice_exib * 100:.2f}%".replace(".", ",")
                fmt_decimal = f"{v_indice_exib:.4f}".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📊 <b>Índice Informado:</b> {fmt_percentual} | 🕵️ <b>Base Decimal de Análise:</b> <code style="font-size: 14px; font-weight: bold; color: #b45309;">{fmt_decimal}</code><br>
                    ⚖️ <b>Situação do Poder Legislativo:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Pontuação Calculada:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{pts_exib:.2f} pontos</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F7", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F7", key=f"btn_salvar_f7_{ano_sel}", type="primary"):
                    v_indice = converte_percentual_br_para_float(st.session_state.get(chave_input_f7, input_ab_str))

                    # Recálculo oficial no salvamento
                    if v_indice > 0.0600:
                        pts_f7 = -10.0
                    elif 0.0570 <= v_indice <= 0.0600:
                        pts_f7 = ((v_indice - 0.0570) / 0.0030) * (-10.0)
                    else: # v_indice < 0.0570
                        pts_f7 = 0.0

                    str_banco = f"{v_indice:.4f}"
                    lnk_val_f7 = link_f7.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f7, dF7.get("comentarios", ""))

                    # Salva no banco de dados via iFiscal
                    save_resp_ifiscal(
                        qid="F7",
                        valor=str_banco,
                        pontos=pts_f7,
                        link=lnk_val_f7,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data
                    res_data["F7"] = {
                        "valor": str_banco,
                        "pontos": pts_f7,
                        "link": lnk_val_f7,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f7 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f7_salva or "")]

                    if lnk_val_f7 != evidencia_f7_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f7_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f7_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Índice do Indicador F7 salvo com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f7_salvos = float(dF7.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto F7: {pts_f7_salvos:.2f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F7 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f7_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F7", st.session_state.get(f"links_pendentes_f7_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f7_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F8 • APURAÇÃO DO RESULTADO FINANCEIRO (SUPERÁVIT/DÉFICIT)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f8_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F8 - Apuração do Resultado Financeiro ({ano_sel})", expanded=True):
                st.subheader("F8 • Apuração do Resultado Financeiro (Superávit/Déficit) – Resultado Consolidado")
                st.write("**Divisão entre o Ativo Financeiro e o Passivo Financeiro (AC / AD = AE)**")
                
                # Tabela Oficial de Parâmetros e Pontuações do Indicador F8
                st.markdown("""
                | Resultado de $AE$ | Pontuação do Indicador |
                | :--- | :--- |
                | Maior ou igual a 1,30 | 0,00 pts |
                | Maior que 1,10 e menor que 1,30 | Graduação entre 75,00 e 0,00 pts |
                | Maior ou igual a 1,00 e menor ou igual a 1,10 | 75,00 pts |
                | Maior que 0,75 e menor que 1,00 | Graduação entre 0,00 e 75,00 pts |
                | Menor ou igual a 0,75 | 0,00 pts |
                """)
                
                # Memórias matemáticas oficiais do indicador F8
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regras de Distribuição Proporcional nos Intervalos:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 1,10 e menores que 1,30 (Superávit Elevado):</b> Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AE – 1,30) * (-1) / 0,20) * 75</code> <br><i>Exemplo: se AE = 1,20, a nota do indicador será 37,50 pontos.</i></li>
                        <li style="margin-top: 8px;"><b>Para resultados maiores que 0,75 e menores que 1,00 (Tendência a Déficit):</b> Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AE – 0,75) / 0,25) * 75</code> <br><i>Exemplo: se AE = 0,85, a nota do indicador será 30,00 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (formato no banco: "AC/AD")
                dF8 = res_data.get("F8") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_ac, val_salvo_ad = str(dF8.get("valor", "0.00/1.00")).split("/")
                    float_ac = float(val_salvo_ac)
                    float_ad = float(val_salvo_ad)
                except Exception:
                    float_ac, float_ad = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_ac = f"R$ {float_ac:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_ad = f"R$ {float_ad:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f8_salva = dF8.get("link", "")

                # Chaves de controle para session_state
                chave_input_ac = f"txt_f8_ac_{ano_sel}_fiscal"
                chave_input_ad = f"txt_f8_ad_{ano_sel}_fiscal"
                chave_link_f8 = f"txt_f8_link_{ano_sel}_fiscal"
                chave_coment_f8 = f"coment_F8_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_ac_str = st.text_input(
                        "Ativo Financeiro (AC) - R$:",
                        value=str_inicial_ac,
                        placeholder="Ex: 1.200.000,00",
                        key=chave_input_ac
                    )
                    
                    input_ad_str = st.text_input(
                        "Passivo Financeiro (AD) - R$:",
                        value=str_inicial_ad,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_ad
                    )

                with c2:
                    link_f8 = st.text_area(
                        f"Link/Evidência (F8 - Balanço Patrimonial AUDESP) ({ano_sel}):", 
                        value=evidencia_f8_salva, 
                        key=chave_link_f8, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f8 = st.empty()
                    links_f8_visuais = re.findall(REGEX_PURE_URL, link_f8 or "")
                    if links_f8_visuais:
                        placeholder_links_f8.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f8_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real com os dados da tela
                v_ativo_exib = converte_moeda_br_para_float(input_ac_str)
                v_passivo_exib = max(converte_moeda_br_para_float(input_ad_str), 0.01) # Evita divisão por zero

                AE_exib = v_ativo_exib / v_passivo_exib

                if v_ativo_exib == 0.0 and (link_f8.strip() == ""):
                    pts_f8_exib = 0.0
                    texto_pontuacao_exib = "⏳ Aguardando preenchimento dos valores..."
                else:
                    if AE_exib >= 1.30 or AE_exib <= 0.75:
                        pts_f8_exib = 0.0
                    elif 1.00 <= AE_exib <= 1.10:
                        pts_f8_exib = 75.0
                    elif 1.10 < AE_exib < 1.30:
                        pts_f8_exib = ((AE_exib - 1.30) * (-1) / 0.20) * 75.0
                    else: # 0.75 < AE_exib < 1.00
                        pts_f8_exib = ((AE_exib - 0.75) / 0.25) * 75.0
                    
                    texto_pontuacao_exib = f"{pts_f8_exib:.2f} pontos"

                str_ativo_fmt = f"R$ {v_ativo_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_passivo_fmt = f"R$ {v_passivo_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_ae_fmt = f"{AE_exib:.4f}".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Balanço Contábil:</b> {str_ativo_fmt} / {str_passivo_fmt}<br>
                    📊 <b>Resultado do Indicador (AE):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_ae_fmt}</code><br>
                    🎯 <b>Pontuação Calculada:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F8", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F8", key=f"btn_salvar_f8_{ano_sel}", type="primary"):
                    v_ativo = converte_moeda_br_para_float(st.session_state.get(chave_input_ac, input_ac_str))
                    v_passivo = max(converte_moeda_br_para_float(st.session_state.get(chave_input_ad, input_ad_str)), 0.01)

                    AE = v_ativo / v_passivo

                    if AE >= 1.30 or AE <= 0.75:
                        pts_f8 = 0.0
                    elif 1.00 <= AE <= 1.10:
                        pts_f8 = 75.0
                    elif 1.10 < AE < 1.30:
                        pts_f8 = ((AE - 1.30) * (-1) / 0.20) * 75.0
                    else: # 0.75 < AE < 1.00
                        pts_f8 = ((AE - 0.75) / 0.25) * 75.0

                    str_banco = f"{v_ativo:.2f}/{v_passivo:.2f}"
                    lnk_val_f8 = link_f8.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f8, dF8.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F8",
                        valor=str_banco,
                        pontos=pts_f8,
                        link=lnk_val_f8,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F8"] = {
                        "valor": str_banco,
                        "pontos": pts_f8,
                        "link": lnk_val_f8,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f8 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f8_salva or "")]

                    if lnk_val_f8 != evidencia_f8_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f8_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f8_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F8 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f8_salvos = float(dF8.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Pontuação F8 Salva: {pts_f8_salvos:.2f} pontos obtidos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F8 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f8_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F8", st.session_state.get(f"links_pendentes_f8_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f8_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F9 • APURAÇÃO DA DÍVIDA FUNDADA (DCL / RCL)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f9_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F9 - Apuração da Dívida Fundada ({ano_sel})", expanded=True):
                st.subheader("F9 • Apuração da Dívida Fundada (DCL / RCL)")
                st.write("**Razão entre a Dívida Consolidada Líquida e a Receita Corrente Líquida [DCL / RCL = AF]**")
                
                # Tabela Oficial de Parâmetros
                st.markdown(r"""
                | Resultado do Índice $AF$ | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Maior que 1,20 ($> 1,2$) | 🚨 -10 (Perde 10 pontos fixos) |
                | Entre 1,10 e 1,20 ($\ge 1,1$ e $\le 1,2$) | ⚠️ Graduação entre 0 e -10 pontos |
                | Menor que 1,10 ($< 1,1$) | ✅ 00 ponto (Sem penalidades) |
                """)
                st.caption("ℹ️ *Dados extraídos do Relatório de Instrução, item GF-28 do Sistema AUDESP.*")
                
                # Memórias matemáticas oficiais do indicador F9
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo Crítico:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 1,10 e menores que 1,20:</b> A graduação será distribuída igualitariamente no intervalo através da fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AF – 1,1) / 0,10) * (-10)</code> <br><i>Exemplo: se AF = 1,15, a nota do indicador será exatamente -5,00 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (formato salvo no banco: "DCL/RCL")
                dF9 = res_data.get("F9") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_dcl, val_salvo_rcl = str(dF9.get("valor", "0.00/1.00")).split("/")
                    float_dcl = float(val_salvo_dcl)
                    float_rcl = float(val_salvo_rcl)
                except Exception:
                    float_dcl, float_rcl = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_dcl = f"R$ {float_dcl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_rcl = f"R$ {float_rcl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f9_salva = dF9.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_dcl = f"txt_f9_dcl_{ano_sel}_fiscal"
                chave_input_rcl = f"txt_f9_rcl_{ano_sel}_fiscal"
                chave_link_f9 = f"txt_f9_link_{ano_sel}_fiscal"
                chave_coment_f9 = f"coment_F9_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_dcl_str = st.text_input(
                        "Dívida Consolidada Líquida (DCL) - R$:",
                        value=str_inicial_dcl,
                        placeholder="Ex: 12.000.000,00",
                        key=chave_input_dcl
                    )
                    
                    input_rcl_str = st.text_input(
                        "Receita Corrente Líquida (RCL) - R$:",
                        value=str_inicial_rcl,
                        placeholder="Ex: 10.000.000,00",
                        key=chave_input_rcl
                    )

                with c2:
                    link_f9 = st.text_area(
                        f"Link/Evidência (F9 - Item GF-28 AUDESP) ({ano_sel}):", 
                        value=evidencia_f9_salva, 
                        key=chave_link_f9, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f9 = st.empty()
                    links_f9_visuais = re.findall(REGEX_PURE_URL, link_f9 or "")
                    if links_f9_visuais:
                        placeholder_links_f9.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f9_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                v_dcl_exib = converte_moeda_br_para_float(input_dcl_str)
                v_rcl_exib = max(converte_moeda_br_para_float(input_rcl_str), 0.01) # Evita divisão por zero

                AF_exib = round(v_dcl_exib / v_rcl_exib, 4)

                if v_dcl_exib == 0.0 and (link_f9.strip() == ""):
                    pts_f9_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ 0,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if AF_exib > 1.2000:
                        pts_f9_exib = -10.0
                        texto_resultado_exib = "🚨 CRÍTICO: Índice Superior ao Teto (> 1,20)"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"
                    elif 1.1000 <= AF_exib <= 1.2000:
                        pts_f9_exib = ((AF_exib - 1.1000) / 0.1000) * (-10.0)
                        texto_resultado_exib = "⚠️ ALERTA DE GRADUAÇÃO (Fórmula Aplicada)"
                        estilo_status_exib = "color: #d97706; font-weight: bold;"
                    else:  # AF_exib < 1.1000
                        pts_f9_exib = 0.0
                        texto_resultado_exib = "✅ REGULAR: Menor que 1,10 (Sem penalidades)"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"

                    texto_pontuacao_exib = f"{pts_f9_exib:.2f} pontos"

                str_dcl_fmt = f"R$ {v_dcl_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_rcl_fmt = f"R$ {v_rcl_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_af_fmt = f"{AF_exib:.4f}".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Razão:</b> {str_dcl_fmt} / {str_rcl_fmt}<br>
                    📊 <b>Resultado do Indicador (AF):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_af_fmt}</code><br>
                    ⚖️ <b>Situação da Dívida Líquida:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F9", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F9", key=f"btn_salvar_f9_{ano_sel}", type="primary"):
                    v_dcl = converte_moeda_br_para_float(st.session_state.get(chave_input_dcl, input_dcl_str))
                    v_rcl = max(converte_moeda_br_para_float(st.session_state.get(chave_input_rcl, input_rcl_str)), 0.01)

                    AF = round(v_dcl / v_rcl, 4)

                    if AF > 1.2000:
                        pts_f9 = -10.0
                    elif 1.1000 <= AF <= 1.2000:
                        pts_f9 = ((AF - 1.1000) / 0.1000) * (-10.0)
                    else:  # AF < 1.1000
                        pts_f9 = 0.0

                    str_banco = f"{v_dcl:.2f}/{v_rcl:.2f}"
                    lnk_val_f9 = link_f9.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f9, dF9.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F9",
                        valor=str_banco,
                        pontos=pts_f9,
                        link=lnk_val_f9,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F9"] = {
                        "valor": str_banco,
                        "pontos": pts_f9,
                        "link": lnk_val_f9,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f9 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f9_salva or "")]

                    if lnk_val_f9 != evidencia_f9_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f9_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f9_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F9 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f9_salvos = float(dF9.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Impacto F9 Salvo: {pts_f9_salvos:.2f} pontos aplicados</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F9 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f9_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F9", st.session_state.get(f"links_pendentes_f9_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f9_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F10 • APURAÇÃO DOS PAGAMENTOS DOS PRECATÓRIOS (AG / AH)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f10_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F10 - Apuração dos Pagamentos dos Precatórios ({ano_sel})", expanded=True):
                st.subheader("F10 • Apuração dos Pagamentos dos Precatórios (AG / AH)")
                st.write("**Razão entre o Estoque Final e o Estoque Inicial de Precatórios [AG / AH = AI]**")
                
                # Tabela Oficial de Parâmetros
                st.markdown(r"""
                | Resultado do Índice $AI$ | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Menor ou igual a 0,9 ($\le 0,9$) | ✅ 75,00 pontos (Pontuação Máxima) |
                | Entre 0,9 e 1,0 ($> 0,9$ e $< 1,0$) | ⚠️ Graduação entre 0,00 e 75,00 pontos |
                | Maior ou igual a 1,0 ($\ge 1,0$) | 🚨 0,00 ponto (Sem bonificação) |
                """)
                st.caption("ℹ️ *Dados extraídos da contabilidade encaminhada pelo Sistema AUDESP.*")
                
                # Memórias matemáticas oficiais do indicador F10
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo Crítico:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 0,90 e menores que 1,00:</b> A graduação será distribuída igualitariamente no intervalo através da fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AI – 1,0) * (-1) / 0,10) * 75</code> <br><i>Exemplo: se AI = 0,95, a nota do indicador será exatamente 37,50 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (formato salvo no banco: "AG/AH")
                dF10 = res_data.get("F10") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_ag, val_salvo_ah = str(dF10.get("valor", "0.00/1.00")).split("/")
                    float_ag = float(val_salvo_ag)
                    float_ah = float(val_salvo_ah)
                except Exception:
                    float_ag, float_ah = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_ag = f"R$ {float_ag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_ah = f"R$ {float_ah:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f10_salva = dF10.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_ag = f"txt_f10_ag_{ano_sel}_fiscal"
                chave_input_ah = f"txt_f10_ah_{ano_sel}_fiscal"
                chave_link_f10 = f"txt_f10_link_{ano_sel}_fiscal"
                chave_coment_f10 = f"coment_F10_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_ag_str = st.text_input(
                        "Estoque Final dos Precatórios (AG) - R$:",
                        value=str_inicial_ag,
                        placeholder="Ex: 950.000,00",
                        key=chave_input_ag
                    )
                    
                    input_ah_str = st.text_input(
                        "Estoque Inicial dos Precatórios (AH) - R$:",
                        value=str_inicial_ah,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_ah
                    )

                with c2:
                    link_f10 = st.text_area(
                        f"Link/Evidência (F10 - Precatórios AUDESP) ({ano_sel}):", 
                        value=evidencia_f10_salva, 
                        key=chave_link_f10, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f10 = st.empty()
                    links_f10_visuais = re.findall(REGEX_PURE_URL, link_f10 or "")
                    if links_f10_visuais:
                        placeholder_links_f10.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f10_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                v_ag_exib = converte_moeda_br_para_float(input_ag_str)
                v_ah_exib = max(converte_moeda_br_para_float(input_ah_str), 0.01) # Evita divisão por zero

                AI_exib = round(v_ag_exib / v_ah_exib, 4)

                if v_ag_exib == 0.0 and (link_f10.strip() == ""):
                    pts_f10_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ 0,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if AI_exib <= 0.9000:
                        pts_f10_exib = 75.0
                        texto_resultado_exib = "✅ REGULAR: Redução Ótima do Estoque (≤ 0,90)"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    elif 0.9000 < AI_exib < 1.0000:
                        pts_f10_exib = ((AI_exib - 1.0000) * (-1.0) / 0.1000) * 75.0
                        texto_resultado_exib = "⚠️ ALERTA DE GRADUAÇÃO (Redução Parcial)"
                        estilo_status_exib = "color: #d97706; font-weight: bold;"
                    else:  # AI_exib >= 1.0000
                        pts_f10_exib = 0.0
                        texto_resultado_exib = "🚨 CRÍTICO: Estoque Mantido ou Aumentado (≥ 1,00)"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"

                    texto_pontuacao_exib = f"{pts_f10_exib:.2f} pontos"

                str_ag_fmt = f"R$ {v_ag_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_ah_fmt = f"R$ {v_ah_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_ai_fmt = f"{AI_exib:.4f}".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Razão:</b> {str_ag_fmt} / {str_ah_fmt}<br>
                    📊 <b>Resultado do Indicador (AI):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_ai_fmt}</code><br>
                    ⚖️ <b>Situação do Estoque:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F10", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F10", key=f"btn_salvar_f10_{ano_sel}", type="primary"):
                    v_ag = converte_moeda_br_para_float(st.session_state.get(chave_input_ag, input_ag_str))
                    v_ah = max(converte_moeda_br_para_float(st.session_state.get(chave_input_ah, input_ah_str)), 0.01)

                    AI = round(v_ag / v_ah, 4)

                    if AI <= 0.9000:
                        pts_f10 = 75.0
                    elif 0.9000 < AI < 1.0000:
                        pts_f10 = ((AI - 1.0000) * (-1.0) / 0.1000) * 75.0
                    else:  # AI >= 1.0000
                        pts_f10 = 0.0

                    str_banco = f"{v_ag:.2f}/{v_ah:.2f}"
                    lnk_val_f10 = link_f10.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f10, dF10.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F10",
                        valor=str_banco,
                        pontos=pts_f10,
                        link=lnk_val_f10,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F10"] = {
                        "valor": str_banco,
                        "pontos": pts_f10,
                        "link": lnk_val_f10,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f10 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f10_salva or "")]

                    if lnk_val_f10 != evidencia_f10_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f10_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f10_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F10 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do impacto da pontuação salva
                pts_f10_salvos = float(dF10.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Pontuação F10 Salva: {pts_f10_salvos:.2f} pontos obtidos</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F10 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f10_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F10", st.session_state.get(f"links_pendentes_f10_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f10_{ano_sel}"] = False,


        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F11 • REPASSE DE DUODÉCIMOS ÀS CÂMARAS (REP / RCL)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f11_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F11 - Repasse de Duodécimos às Câmaras ({ano_sel})", expanded=True):
                st.subheader("F11 • Repasse de Duodécimos às Câmaras (Valor Repassado / RCL)")
                st.write("**Razão entre as Transferências à Câmara e a Receita Corrente Líquida**")
                
                # Tabela Oficial de Regras de Pontuação / Penalidade
                st.markdown(r"""
                | Percentual de Repasse | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Menor ou igual a 6,00% ($\le 6\%$) | ✅ 0,00 ponto (Sem penalidades / Regular) |
                | Maior que 6,00% ($> 6\%$) | 🚨 **REBAIXAR IEG-M PARA FAIXA C** (Nota Geral afetada) |
                """)
                st.caption("ℹ️ *Dados extraídos com base no item 'Transferências à Câmara dos Vereadores' do modelo de relatório de contas municipais do Sistema AUDESP.*")

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (formato salvo no banco: "REP/RCL")
                dF11 = res_data.get("F11") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_rep, val_salvo_rcl = str(dF11.get("valor", "0.00/1.00")).split("/")
                    float_rep = float(val_salvo_rep)
                    float_rcl = float(val_salvo_rcl)
                except Exception:
                    float_rep, float_rcl = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_rep = f"R$ {float_rep:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_rcl = f"R$ {float_rcl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f11_salva = dF11.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_rep = f"txt_f11_rep_{ano_sel}_fiscal"
                chave_input_rcl = f"txt_f11_rcl_{ano_sel}_fiscal"
                chave_link_f11 = f"txt_f11_link_{ano_sel}_fiscal"
                chave_coment_f11 = f"coment_F11_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    input_rep_str = st.text_input(
                        "Transferências à Câmara dos Vereadores - R$:",
                        value=str_inicial_rep,
                        placeholder="Ex: 600.000,00",
                        key=chave_input_rep
                    )
                    
                    input_rcl_str = st.text_input(
                        "Receita Corrente Líquida (RCL) - R$ (F11):",
                        value=str_inicial_rcl,
                        placeholder="Ex: 10.000.000,00",
                        key=chave_input_rcl
                    )

                with c2:
                    link_f11 = st.text_area(
                        f"Link/Evidência (F11 - Duodécimo Câmara) ({ano_sel}):", 
                        value=evidencia_f11_salva, 
                        key=chave_link_f11, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f11 = st.empty()
                    links_f11_visuais = re.findall(REGEX_PURE_URL, link_f11 or "")
                    if links_f11_visuais:
                        placeholder_links_f11.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f11_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                v_rep_exib = converte_moeda_br_para_float(input_rep_str)
                v_rcl_exib = max(converte_moeda_br_para_float(input_rcl_str), 0.01) # Evita divisão por zero

                perc_repasse_exib = round(v_rep_exib / v_rcl_exib, 4)
                perc_exibicao = perc_repasse_exib * 100

                if v_rep_exib == 0.0 and (link_f11.strip() == ""):
                    pts_f11_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ Verificar Limite"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if perc_repasse_exib > 0.0600:
                        pts_f11_exib = 0.0
                        texto_resultado_exib = "🚨 CRÍTICO: Limite Excedido! Rebaixar IEG-M para Faixa C"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"
                    else:
                        pts_f11_exib = 0.0
                        texto_resultado_exib = "✅ REGULAR: Dentro do teto constitucional de 6,00%"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"

                    texto_pontuacao_exib = f"{pts_f11_exib:.2f} pontos"

                str_rep_fmt = f"R$ {v_rep_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_rcl_fmt = f"R$ {v_rcl_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_perc_fmt = f"{perc_exibicao:.2f}%".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo do Repasse:</b> ({str_rep_fmt} / {str_rcl_fmt}) * 100<br>
                    📊 <b>Percentual Apurado:</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_perc_fmt}</code> (Limite Constitucional: 6,00%)<br>
                    ⚖️ <b>Situação Constitucional:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F11", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F11", key=f"btn_salvar_f11_{ano_sel}", type="primary"):
                    v_rep = converte_moeda_br_para_float(st.session_state.get(chave_input_rep, input_rep_str))
                    v_rcl = max(converte_moeda_br_para_float(st.session_state.get(chave_input_rcl, input_rcl_str)), 0.01)

                    perc_repasse = round(v_rep / v_rcl, 4)

                    pts_f11 = 0.0  # F11 atua como gatilho de rebaixamento e mantém pontuação base zerada

                    str_banco = f"{v_rep:.2f}/{v_rcl:.2f}"
                    lnk_val_f11 = link_f11.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f11, dF11.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F11",
                        valor=str_banco,
                        pontos=pts_f11,
                        link=lnk_val_f11,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F11"] = {
                        "valor": str_banco,
                        "pontos": pts_f11,
                        "link": lnk_val_f11,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f11 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f11_salva or "")]

                    if lnk_val_f11 != evidencia_f11_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f11_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f11_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F11 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f11_salvos = float(dF11.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F11 Registrado: {pts_f11_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F11 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f11_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F11", st.session_state.get(f"links_pendentes_f11_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f11_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F12 • PONTUALIDADE NA PRESTAÇÃO DE CONTAS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f12_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F12 - Pontualidade na Prestação de Contas ({ano_sel})", expanded=True):
                st.subheader("F12 • Pontualidade na Prestação de Contas")
                st.write("**Cumprimento dos prazos de envio de Atas, Pareceres, Balancetes, Mapas de Precatórios e Conciliações**")
                
                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Situação da Entrega | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Encaminhou no prazo | ✅ 50,00 pontos (Pontuação Máxima) |
                | Encaminhou fora do prazo | ⚠️ 25,00 pontos (Penalidade Parcial) |
                | Não encaminhou | 🚨 0,00 ponto (Sem pontuação) |
                """)
                st.caption("ℹ️ *Informações extraídas do Sistema AUDESP – Relatório de Situação de Entrega.*")

                # Estado inicial / persistente no banco
                dF12 = res_data.get("F12") or {"valor": "Aguardando preenchimento...", "pontos": 0.0, "link": "", "comentarios": ""}
                val_salvo_status = dF12.get("valor", "Aguardando preenchimento...")
                evidencia_f12_salva = dF12.get("link", "")

                opcoes_status = [
                    "Aguardando preenchimento...",
                    "Encaminhou no prazo",
                    "Encaminhou fora do prazo",
                    "Não encaminhou"
                ]

                try:
                    idx_inicial = opcoes_status.index(val_salvo_status)
                except ValueError:
                    idx_inicial = 0

                # Chaves padronizadas para o session_state do iFiscal
                chave_sb_f12 = f"sb_f12_status_{ano_sel}_fiscal"
                chave_link_f12 = f"txt_f12_link_{ano_sel}_fiscal"
                chave_coment_f12 = f"coment_F12_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])
                
                with c1:
                    status_selecionado = st.selectbox(
                        "Situação da entrega dos documentos no AUDESP:",
                        options=opcoes_status,
                        index=idx_inicial,
                        key=chave_sb_f12
                    )

                with c2:
                    link_f12 = st.text_area(
                        f"Link/Evidência (F12 - Situação de Entrega AUDESP) ({ano_sel}):", 
                        value=evidencia_f12_salva, 
                        key=chave_link_f12, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f12 = st.empty()
                    links_f12_visuais = re.findall(REGEX_PURE_URL, link_f12 or "")
                    if links_f12_visuais:
                        placeholder_links_f12.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f12_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real conforme regra do indicador
                if status_selecionado == "Encaminhou no prazo":
                    pts_f12_exib = 50.0
                    texto_resultado_exib = "✅ REGULAR: Documentação enviada tempestivamente"
                    estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    texto_pontuacao_exib = "50,00 pontos"
                elif status_selecionado == "Encaminhou fora do prazo":
                    pts_f12_exib = 25.0
                    texto_resultado_exib = "⚠️ ALERTA: Remessa em atraso apurada no relatório"
                    estilo_status_exib = "color: #d97706; font-weight: bold;"
                    texto_pontuacao_exib = "25,00 pontos"
                elif status_selecionado == "Não encaminhou":
                    pts_f12_exib = 0.0
                    texto_resultado_exib = "🚨 CRÍTICO: Ausência de prestação de contas obrigatória"
                    estilo_status_exib = "color: #dc2626; font-weight: bold;"
                    texto_pontuacao_exib = "0,00 pontos"
                else:
                    pts_f12_exib = 0.0
                    texto_resultado_exib = "Aguardando seleção do status..."
                    estilo_status_exib = "color: #64748b;"
                    texto_pontuacao_exib = "⏳ 0,00 pontos"

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Critério Avaliado:</b> Atas, Pareceres, Balancetes, Precatórios, Conciliações e Questionário IEG-M<br>
                    ⚖️ <b>Status da Prestação:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F12", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F12", key=f"btn_salvar_f12_{ano_sel}", type="primary"):
                    status_final = st.session_state.get(chave_sb_f12, status_selecionado)

                    if status_final == "Encaminhou no prazo":
                        pts_f12 = 50.0
                    elif status_final == "Encaminhou fora do prazo":
                        pts_f12 = 25.0
                    else:
                        pts_f12 = 0.0

                    lnk_val_f12 = link_f12.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f12, dF12.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F12",
                        valor=status_final,
                        pontos=pts_f12,
                        link=lnk_val_f12,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F12"] = {
                        "valor": status_final,
                        "pontos": pts_f12,
                        "link": lnk_val_f12,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f12 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f12_salva or "")]

                    if lnk_val_f12 != evidencia_f12_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f12_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f12_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Status e pontuação do Indicador F12 salvos com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f12_salvos = float(dF12.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F12 Registrado: {pts_f12_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F12 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f12_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F12", st.session_state.get(f"links_pendentes_f12_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f12_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F13 • DÍVIDA ATIVA: PERCENTUAL DE RECEBIMENTO (AL)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f13_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F13 - Dívida Ativa: Percentual de Recebimento ({ano_sel})", expanded=True):
                st.subheader("F13 • Dívida Ativa: Percentual de Recebimento (AL)")
                st.write("**Nível de recebimento da dívida em relação ao estoque inicial**")

                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Resultado do Índice $AL$ | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Igual a 0 ($AL = 0$) | 🚨 0,00 ponto (Sem arrecadação) |
                | Entre 0,0 e 0,1 ($> 0,0$ e $< 0,1$) | ⚠️ Graduação entre 0 e 50 pontos |
                | Maior ou igual a 0,10 ($\ge 0,10$) | ✅ 50,00 pontos (Arrecadação Excelente) |
                """)
                st.caption("ℹ️ *Dados extraídos do Relatório de Análises Anuais Eletrônicas do Sistema AUDESP.*")

                # Regra Proporcional Intermediária
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo Intermediário:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 0,00 e menores que 0,10:</b> A graduação será distribuída igualitariamente no intervalo através da fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">(AL / 0,10) * 50</code> <br><i>Exemplo: se AL = 0,0500 (5% de recebimento), a nota do indicador será exatamente 25,00 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (formato salvo no banco: "REC/EST")
                dF13 = res_data.get("F13") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_rec, val_salvo_est = str(dF13.get("valor", "0.00/1.00")).split("/")
                    float_rec = float(val_salvo_rec)
                    float_est = float(val_salvo_est)
                except Exception:
                    float_rec, float_est = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_rec = f"R$ {float_rec:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_est = f"R$ {float_est:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f13_salva = dF13.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_rec = f"txt_f13_rec_{ano_sel}_fiscal"
                chave_input_est = f"txt_f13_est_{ano_sel}_fiscal"
                chave_link_f13 = f"txt_f13_link_{ano_sel}_fiscal"
                chave_coment_f13 = f"coment_F13_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    input_rec_str = st.text_input(
                        "Valor Arrecadado de Dívida Ativa - R$:",
                        value=str_inicial_rec,
                        placeholder="Ex: 50.000,00",
                        key=chave_input_rec
                    )

                    input_est_str = st.text_input(
                        "Estoque Inicial da Dívida Ativa - R$:",
                        value=str_inicial_est,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_est
                    )

                with c2:
                    link_f13 = st.text_area(
                        f"Link/Evidência (F13 - Dívida Ativa AUDESP) ({ano_sel}):", 
                        value=evidencia_f13_salva, 
                        key=chave_link_f13, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f13 = st.empty()
                    links_f13_visuais = re.findall(REGEX_PURE_URL, link_f13 or "")
                    if links_f13_visuais:
                        placeholder_links_f13.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f13_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                v_rec_exib = converte_moeda_br_para_float(input_rec_str)
                v_est_exib = max(converte_moeda_br_para_float(input_est_str), 0.01) # Evita divisão por zero

                al_exib = round(v_rec_exib / v_est_exib, 4)

                if v_rec_exib == 0.0 and (link_f13.strip() == ""):
                    pts_f13_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ 0,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if al_exib == 0.0000:
                        pts_f13_exib = 0.0
                        texto_resultado_exib = "🚨 CRÍTICO: Nenhuma arrecadação apurada (= 0,00)"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"
                    elif 0.0000 < al_exib < 0.1000:
                        pts_f13_exib = (al_exib / 0.1000) * 50.0
                        texto_resultado_exib = "⚠️ ALERTA DE GRADUAÇÃO (Recuperação Intermediária)"
                        estilo_status_exib = "color: #d97706; font-weight: bold;"
                    else:
                        pts_f13_exib = 50.0
                        texto_resultado_exib = "✅ REGULAR: Índice de recebimento adequado (≥ 10%)"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"

                    texto_pontuacao_exib = f"{pts_f13_exib:.2f} pontos"

                str_rec_fmt = f"R$ {v_rec_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_est_fmt = f"R$ {v_est_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_al_fmt = f"{al_exib:.4f}".replace(".", ",")
                str_perc_fmt = f"{al_exib * 100:.2f}%".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Razão:</b> {str_rec_fmt} / {str_est_fmt}<br>
                    📊 <b>Resultado do Indicador (AL):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_al_fmt}</code> ({str_perc_fmt} de recebimento)<br>
                    ⚖️ <b>Situação da Arrecadação:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F13", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F13", key=f"btn_salvar_f13_{ano_sel}", type="primary"):
                    v_rec = converte_moeda_br_para_float(st.session_state.get(chave_input_rec, input_rec_str))
                    v_est = max(converte_moeda_br_para_float(st.session_state.get(chave_input_est, input_est_str)), 0.01)

                    al_calculado = round(v_rec / v_est, 4)

                    if al_calculado == 0.0000:
                        pts_f13 = 0.0
                    elif 0.0000 < al_calculado < 0.1000:
                        pts_f13 = (al_calculado / 0.1000) * 50.0
                    else:
                        pts_f13 = 50.0

                    str_banco = f"{v_rec:.2f}/{v_est:.2f}"
                    lnk_val_f13 = link_f13.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f13, dF13.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F13",
                        valor=str_banco,
                        pontos=pts_f13,
                        link=lnk_val_f13,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F13"] = {
                        "valor": str_banco,
                        "pontos": pts_f13,
                        "link": lnk_val_f13,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f13 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f13_salva or "")]

                    if lnk_val_f13 != evidencia_f13_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f13_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f13_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F13 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f13_salvos = float(dF13.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F13 Registrado: {pts_f13_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F13 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f13_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F13", st.session_state.get(f"links_pendentes_f13_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f13_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F14 • DÍVIDA ATIVA: PERCENTUAL DE CANCELAMENTO (AM)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f14_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F14 - Dívida Ativa: Percentual de Cancelamento ({ano_sel})", expanded=True):
                st.subheader("F14 • Dívida Ativa: Percentual de Cancelamento (AM)")
                st.write("**Nível de cancelamento da dívida em relação ao estoque inicial**")

                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Resultado do Índice $AM$ | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Igual a 0 ($AM = 0$) | ✅ 50,00 pontos (Pontuação Máxima) |
                | Entre 0,0 e 0,1 ($> 0,0$ e $< 0,1$) | ⚠️ Graduação entre 50 e 0 pontos |
                | Maior ou igual a 0,10 ($\ge 0,10$) | 🚨 0,00 ponto (Cancelamento Excessivo) |
                """)
                st.caption("ℹ️ *Dados extraídos do Relatório de Análises Anuais Eletrônicas do Sistema AUDESP.*")

                # Regra Proporcional Regressiva Intermediária
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional Regressiva no Intervalo:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 0,00 e menores que 0,10:</b> A graduação decrescerá igualitariamente no intervalo através da fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AM – 0,10) * (-1) / 0,10) * 50</code> <br><i>Exemplo: se AM = 0,0500 (5% de cancelamento), a nota do indicador será exatamente 25,00 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (formato salvo no banco: "CAN/EST")
                dF14 = res_data.get("F14") or {"valor": "0.00/1.00", "pontos": 50.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_can, val_salvo_est = str(dF14.get("valor", "0.00/1.00")).split("/")
                    float_can = float(val_salvo_can)
                    float_est = float(val_salvo_est)
                except Exception:
                    float_can, float_est = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_can = f"R$ {float_can:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_est = f"R$ {float_est:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f14_salva = dF14.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_can = f"txt_f14_can_{ano_sel}_fiscal"
                chave_input_est = f"txt_f14_est_{ano_sel}_fiscal"
                chave_link_f14 = f"txt_f14_link_{ano_sel}_fiscal"
                chave_coment_f14 = f"coment_F14_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    input_can_str = st.text_input(
                        "Valor Cancelado de Dívida Ativa - R$:",
                        value=str_inicial_can,
                        placeholder="Ex: 10.000,00",
                        key=chave_input_can
                    )

                    input_est_str = st.text_input(
                        "Estoque Inicial da Dívida Ativa - R$ (F14):",
                        value=str_inicial_est,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_est
                    )

                with c2:
                    link_f14 = st.text_area(
                        f"Link/Evidência (F14 - Cancelamento Dívida Ativa) ({ano_sel}):", 
                        value=evidencia_f14_salva, 
                        key=chave_link_f14, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f14 = st.empty()
                    links_f14_visuais = re.findall(REGEX_PURE_URL, link_f14 or "")
                    if links_f14_visuais:
                        placeholder_links_f14.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f14_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                v_can_exib = converte_moeda_br_para_float(input_can_str)
                v_est_exib = max(converte_moeda_br_para_float(input_est_str), 0.01) # Evita divisão por zero

                am_exib = round(v_can_exib / v_est_exib, 4)

                if v_can_exib == 0.0 and (link_f14.strip() == ""):
                    pts_f14_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ 0,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if am_exib == 0.0000:
                        pts_f14_exib = 50.0
                        texto_resultado_exib = "✅ EXCELENTE: Nenhum cancelamento efetuado (= 0,00)"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    elif 0.0000 < am_exib < 0.1000:
                        pts_f14_exib = ((am_exib - 0.1000) * (-1.0) / 0.1000) * 50.0
                        texto_resultado_exib = "⚠️ ALERTA DE GRADUAÇÃO (Baixa Parcial do Estoque)"
                        estilo_status_exib = "color: #d97706; font-weight: bold;"
                    else:
                        pts_f14_exib = 0.0
                        texto_resultado_exib = "🚨 CRÍTICO: Índice de cancelamento muito elevado (≥ 10%)"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"

                    texto_pontuacao_exib = f"{pts_f14_exib:.2f} pontos"

                str_can_fmt = f"R$ {v_can_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_est_fmt = f"R$ {v_est_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_am_fmt = f"{am_exib:.4f}".replace(".", ",")
                str_perc_fmt = f"{am_exib * 100:.2f}%".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Razão:</b> {str_can_fmt} / {str_est_fmt}<br>
                    📊 <b>Resultado do Indicador (AM):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_am_fmt}</code> ({str_perc_fmt} de cancelamento)<br>
                    ⚖️ <b>Situação do Estoque:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F14", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F14", key=f"btn_salvar_f14_{ano_sel}", type="primary"):
                    v_can = converte_moeda_br_para_float(st.session_state.get(chave_input_can, input_can_str))
                    v_est = max(converte_moeda_br_para_float(st.session_state.get(chave_input_est, input_est_str)), 0.01)

                    am_calculado = round(v_can / v_est, 4)

                    if am_calculado == 0.0000:
                        pts_f14 = 50.0
                    elif 0.0000 < am_calculado < 0.1000:
                        pts_f14 = ((am_calculado - 0.1000) * (-1.0) / 0.1000) * 50.0
                    else:
                        pts_f14 = 0.0

                    str_banco = f"{v_can:.2f}/{v_est:.2f}"
                    lnk_val_f14 = link_f14.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f14, dF14.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F14",
                        valor=str_banco,
                        pontos=pts_f14,
                        link=lnk_val_f14,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F14"] = {
                        "valor": str_banco,
                        "pontos": pts_f14,
                        "link": lnk_val_f14,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f14 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f14_salva or "")]

                    if lnk_val_f14 != evidencia_f14_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f14_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f14_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F14 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f14_salvos = float(dF14.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F14 Registrado: {pts_f14_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F14 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f14_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F14", st.session_state.get(f"links_pendentes_f14_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f14_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F15 • ALERTAS DO SISTEMA AUDESP
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f15_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F15 - Alertas do Sistema AUDESP ({ano_sel})", expanded=True):
                st.subheader("F15 • Alertas do Sistema AUDESP")
                st.write("**Quantidade total de alertas gerados pelo sistema eletrônico no exercício**")

                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Quantidade de Alertas | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Menor ou igual a 20 ($\le 20$) | ✅ 25,00 pontos (Pontuação Máxima) |
                | Entre 21 e 40 ($> 20$ e $\le 40$) | ⚠️ 10,00 pontos (Atenção / Nota Parcial) |
                | Maior ou igual a 41 ($\ge 41$) | 🚨 0,00 ponto (Volume Crítico de Alertas) |
                """)
                st.caption("ℹ️ *Informações extraídas do módulo de controle do Sistema AUDESP.*")

                # Estado inicial / persistente do banco
                dF15 = res_data.get("F15") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_alertas = int(float(dF15.get("valor", 0)))
                except Exception:
                    val_salvo_alertas = 0

                evidencia_f15_salva = dF15.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_f15 = f"num_f15_alertas_{ano_sel}_fiscal"
                chave_link_f15 = f"txt_f15_link_{ano_sel}_fiscal"
                chave_coment_f15 = f"coment_F15_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    qtd_alertas = st.number_input(
                        "Quantidade total de alertas gerados no ano:",
                        min_value=0,
                        max_value=9999,
                        value=val_salvo_alertas,
                        step=1,
                        format="%d",
                        key=chave_input_f15
                    )

                with c2:
                    link_f15 = st.text_area(
                        f"Link/Evidência (F15 - Painel de Alertas AUDESP) ({ano_sel}):", 
                        value=evidencia_f15_salva, 
                        key=chave_link_f15, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f15 = st.empty()
                    links_f15_visuais = re.findall(REGEX_PURE_URL, link_f15 or "")
                    if links_f15_visuais:
                        placeholder_links_f15.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f15_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                if qtd_alertas <= 20:
                    pts_f15_exib = 25.0
                    texto_resultado_exib = f"✅ ADEQUADO: Baixo volume de alertas ({qtd_alertas})"
                    estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    texto_pontuacao_exib = "25,00 pontos"
                elif 20 < qtd_alertas <= 40:
                    pts_f15_exib = 10.0
                    texto_resultado_exib = f"⚠️ ATENÇÃO: Volume moderado de inconformidades ({qtd_alertas})"
                    estilo_status_exib = "color: #d97706; font-weight: bold;"
                    texto_pontuacao_exib = "10,00 pontos"
                else:
                    pts_f15_exib = 0.0
                    texto_resultado_exib = f"🚨 EXCESSO: Alto índice de ocorrências sistêmicas ({qtd_alertas})"
                    estilo_status_exib = "color: #dc2626; font-weight: bold;"
                    texto_pontuacao_exib = "0,00 pontos"

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Métrica Avaliada:</b> Concentração de inconformidades contábeis e de gestão<br>
                    📊 <b>Quantidade Registrada:</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{qtd_alertas} alertas</code><br>
                    ⚖️ <b>Situação Institucional:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F15", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F15", key=f"btn_salvar_f15_{ano_sel}", type="primary"):
                    v_alertas = st.session_state.get(chave_input_f15, qtd_alertas)

                    if v_alertas <= 20:
                        pts_f15 = 25.0
                    elif 20 < v_alertas <= 40:
                        pts_f15 = 10.0
                    else:
                        pts_f15 = 0.0

                    lnk_val_f15 = link_f15.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f15, dF15.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F15",
                        valor=str(v_alertas),
                        pontos=pts_f15,
                        link=lnk_val_f15,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F15"] = {
                        "valor": str(v_alertas),
                        "pontos": pts_f15,
                        "link": lnk_val_f15,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f15 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f15_salva or "")]

                    if lnk_val_f15 != evidencia_f15_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f15_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f15_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F15 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f15_salvos = float(dF15.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F15 Registrado: {pts_f15_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F15 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f15_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F15", st.session_state.get(f"links_pendentes_f15_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f15_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F16 • BALANCETES REJEITADOS
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f16_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F16 - Balancetes Rejeitados ({ano_sel})", expanded=True):
                st.subheader("F16 • Balancetes Rejeitados")
                st.write("**Quantidade total de balancetes mensais rejeitados no exercício**")

                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Balancetes Rejeitados | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Menor ou igual a 1 ($\le 1$) | ✅ 25,00 pontos (Pontuação Máxima) |
                | Entre 2 e 17 ($> 1$ e $< 18$) | ⚠️ 10,00 pontos (Atenção / Nota Parcial) |
                | Maior ou igual a 18 ($\ge 18$) | 🚨 0,00 ponto (Volume Crítico de Rejeições) |
                """)
                st.caption("ℹ️ *Informações apuradas com base nas notificações de rejeição do Sistema AUDESP.*")

                # Estado inicial / persistente do banco
                dF16 = res_data.get("F16") or {"valor": "0", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_rejeitados = int(float(dF16.get("valor", 0)))
                except Exception:
                    val_salvo_rejeitados = 0

                evidencia_f16_salva = dF16.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_f16 = f"num_f16_rejeitados_{ano_sel}_fiscal"
                chave_link_f16 = f"txt_f16_link_{ano_sel}_fiscal"
                chave_coment_f16 = f"coment_F16_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    qtd_rejeitados = st.number_input(
                        "Quantidade de balancetes rejeitados no ano:",
                        min_value=0,
                        max_value=120,
                        value=val_salvo_rejeitados,
                        step=1,
                        format="%d",
                        key=chave_input_f16
                    )

                with c2:
                    link_f16 = st.text_area(
                        f"Link/Evidência (F16 - Histórico de Balancetes AUDESP) ({ano_sel}):", 
                        value=evidencia_f16_salva, 
                        key=chave_link_f16, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f16 = st.empty()
                    links_f16_visuais = re.findall(REGEX_PURE_URL, link_f16 or "")
                    if links_f16_visuais:
                        placeholder_links_f16.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f16_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                if qtd_rejeitados <= 1:
                    pts_f16_exib = 25.0
                    texto_resultado_exib = f"✅ ADEQUADO: Índice de rejeição mínimo ({qtd_rejeitados})"
                    estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    texto_pontuacao_exib = "25,00 pontos"
                elif 1 < qtd_rejeitados < 18:
                    pts_f16_exib = 10.0
                    texto_resultado_exib = f"⚠️ ATENÇÃO: Rejeições recorrentes identificadas ({qtd_rejeitados})"
                    estilo_status_exib = "color: #d97706; font-weight: bold;"
                    texto_pontuacao_exib = "10,00 pontos"
                else:
                    pts_f16_exib = 0.0
                    texto_resultado_exib = f"🚨 EXCESSO: Volume crítico de inconsistências contábeis ({qtd_rejeitados})"
                    estilo_status_exib = "color: #dc2626; font-weight: bold;"
                    texto_pontuacao_exib = "0,00 pontos"

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Métrica Avaliada:</b> Qualidade e consistência das remessas contábeis mensais<br>
                    📊 <b>Quantidade Registrada:</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{qtd_rejeitados} balancetes</code><br>
                    ⚖️ <b>Situação Institucional:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F16", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F16", key=f"btn_salvar_f16_{ano_sel}", type="primary"):
                    v_rejeitados = st.session_state.get(chave_input_f16, qtd_rejeitados)

                    if v_rejeitados <= 1:
                        pts_f16 = 25.0
                    elif 1 < v_rejeitados < 18:
                        pts_f16 = 10.0
                    else:
                        pts_f16 = 0.0

                    lnk_val_f16 = link_f16.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f16, dF16.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F16",
                        valor=str(v_rejeitados),
                        pontos=pts_f16,
                        link=lnk_val_f16,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F16"] = {
                        "valor": str(v_rejeitados),
                        "pontos": pts_f16,
                        "link": lnk_val_f16,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f16 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f16_salva or "")]

                    if lnk_val_f16 != evidencia_f16_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f16_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f16_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F16 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f16_salvos = float(dF16.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F16 Registrado: {pts_f16_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F16 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f16_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F16", st.session_state.get(f"links_pendentes_f16_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f16_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F17 • RESULTADO PRIMÁRIO (OPERACIONAL)
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f17_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F17 - Resultado Primário (Operacional) ({ano_sel})", expanded=True):
                st.subheader("F17 • Resultado Primário (Operacional) [RP = RR - DL]")
                st.write("**Mede a capacidade do município de reduzir seu endividamento estrutural**")

                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Resultado Primário ($RP$) | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Acima de ZERO ($RP > 0$) | ✅ 75,00 pontos (Superávit Primário) |
                | Igual a ZERO ($RP = 0$) | ⚠️ 40,00 pontos (Equilíbrio Limite) |
                | Abaixo de ZERO ($RP < 0$) | 🚨 0,00 ponto (Déficit Primário) |
                """)
                st.caption("ℹ️ *Dados extraídos da linha 'RESULTADO PRIMÁRIO (VIII-XVII)' do Demonstrativo do Resultado Primário do 6º bimestre (Item GF20 - AUDESP).*")

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (formato salvo no banco: "RR/DL")
                dF17 = res_data.get("F17") or {"valor": "0.00/0.00", "pontos": 40.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_rr, val_salvo_dl = str(dF17.get("valor", "0.00/0.00")).split("/")
                    float_rr = float(val_salvo_rr)
                    float_dl = float(val_salvo_dl)
                except Exception:
                    float_rr, float_dl = 0.0, 0.0

                # Formatação monetária inicial para exibição
                str_inicial_rr = f"R$ {float_rr:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_dl = f"R$ {float_dl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f17_salva = dF17.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_rr = f"txt_f17_rr_{ano_sel}_fiscal"
                chave_input_dl = f"txt_f17_dl_{ano_sel}_fiscal"
                chave_link_f17 = f"txt_f17_link_{ano_sel}_fiscal"
                chave_coment_f17 = f"coment_F17_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    input_rr_str = st.text_input(
                        "Receitas Realizadas (RR) - R$:",
                        value=str_inicial_rr,
                        placeholder="Ex: 1.500.000,00",
                        key=chave_input_rr
                    )

                    input_dl_str = st.text_input(
                        "Despesas Liquidadas (DL) - R$:",
                        value=str_inicial_dl,
                        placeholder="Ex: 1.400.000,00",
                        key=chave_input_dl
                    )

                with c2:
                    link_f17 = st.text_area(
                        f"Link/Evidência (F17 - Demonstrativo Primário AUDESP) ({ano_sel}):", 
                        value=evidencia_f17_salva, 
                        key=chave_link_f17, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f17 = st.empty()
                    links_f17_visuais = re.findall(REGEX_PURE_URL, link_f17 or "")
                    if links_f17_visuais:
                        placeholder_links_f17.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f17_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                v_rr_exib = converte_moeda_br_para_float(input_rr_str)
                v_dl_exib = converte_moeda_br_para_float(input_dl_str)
                v_rp_exib = round(v_rr_exib - v_dl_exib, 2)

                if v_rr_exib == 0.0 and v_dl_exib == 0.0 and (link_f17.strip() == ""):
                    pts_f17_exib = 40.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "40,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if v_rp_exib > 0.00:
                        pts_f17_exib = 75.0
                        texto_resultado_exib = "✅ SUPERÁVIT: Capacidade de redução do endividamento"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    elif v_rp_exib == 0.00:
                        pts_f17_exib = 40.0
                        texto_resultado_exib = "⚠️ EQUILÍBRIO: Receitas equivalentes às despesas liquidadas"
                        estilo_status_exib = "color: #d97706; font-weight: bold;"
                    else:
                        pts_f17_exib = 0.0
                        texto_resultado_exib = "🚨 DÉFICIT: Tendência de aumento do endividamento municipal"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"

                    texto_pontuacao_exib = f"{pts_f17_exib:.2f} pontos"

                str_rr_fmt = f"R$ {v_rr_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_dl_fmt = f"R$ {v_dl_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                
                sinal_exib = "-" if v_rp_exib < 0 else ""
                str_rp_fmt = f"{sinal_exib}R$ {abs(v_rp_exib):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Fórmula (RP = RR - DL):</b> {str_rr_fmt} - {str_dl_fmt}<br>
                    📊 <b>Resultado Primário Apurado (RP):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_rp_fmt}</code><br>
                    ⚖️ <b>Situação Fiscal:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F17", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F17", key=f"btn_salvar_f17_{ano_sel}", type="primary"):
                    v_rr = converte_moeda_br_para_float(st.session_state.get(chave_input_rr, input_rr_str))
                    v_dl = converte_moeda_br_para_float(st.session_state.get(chave_input_dl, input_dl_str))
                    v_rp = round(v_rr - v_dl, 2)

                    if v_rp > 0.00:
                        pts_f17 = 75.0
                    elif v_rp == 0.00:
                        pts_f17 = 40.0
                    else:
                        pts_f17 = 0.0

                    str_banco = f"{v_rr:.2f}/{v_dl:.2f}"
                    lnk_val_f17 = link_f17.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f17, dF17.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F17",
                        valor=str_banco,
                        pontos=pts_f17,
                        link=lnk_val_f17,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F17"] = {
                        "valor": str_banco,
                        "pontos": pts_f17,
                        "link": lnk_val_f17,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f17 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f17_salva or "")]

                    if lnk_val_f17 != evidencia_f17_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f17_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f17_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F17 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f17_salvos = float(dF17.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F17 Registrado: {pts_f17_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F17 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f17_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F17", st.session_state.get(f"links_pendentes_f17_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f17_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F18 • ÍNDICE DE LIQUIDEZ IMEDIATA
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f18_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F18 - Índice de Liquidez Imediata ({ano_sel})", expanded=True):
                st.subheader("F18 • Índice de Liquidez Imediata [IL = D / PC]")
                st.write("**Verifica a capacidade de pagamento com recursos do ativo disponível**")

                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Resultado do Índice $IL$ | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Maior ou igual a 1 ($IL \ge 1,0$) | ✅ 75,00 pontos (Pontuação Máxima) |
                | Entre 0,8 e 1 ($> 0,8$ e $< 1,0$) | ⚠️ Graduação proporcional entre 0 e 75 pontos |
                | Menor ou igual a 0,8 ($IL \le 0,8$) | 🚨 0,00 ponto (Capacidade Crítica) |
                """)
                st.caption("ℹ️ *Dados extraídos do Relatório de Análises Anuais Eletrônicas – RAAE, item 4.1 (Capacidade de Pagamento com Recursos do Ativo Disponível).*")

                # 📝 Memória de cálculo oficial fornecida
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 0,80 e menores que 1,00:</b> A graduação será distribuída utilizando a fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">P = ((IL - 0,80) * 75) / 0,20</code> <br><i>Exemplo: se IL = 0,8100, a nota do indicador será exatamente 3,75 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Estado inicial / persistente (formato salvo no banco: "D/PC")
                dF18 = res_data.get("F18") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_disp, val_salvo_pc = str(dF18.get("valor", "0.00/1.00")).split("/")
                    float_disp = float(val_salvo_disp)
                    float_pc = float(val_salvo_pc)
                except Exception:
                    float_disp, float_pc = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_disp = f"R$ {float_disp:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_inicial_pc = f"R$ {float_pc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                evidencia_f18_salva = dF18.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_disp = f"txt_f18_disp_{ano_sel}_fiscal"
                chave_input_pc = f"txt_f18_pc_{ano_sel}_fiscal"
                chave_link_f18 = f"txt_f18_link_{ano_sel}_fiscal"
                chave_coment_f18 = f"coment_F18_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    input_disp_str = st.text_input(
                        "Recursos do Ativo Disponível (D) - R$:",
                        value=str_inicial_disp,
                        placeholder="Ex: 81.000,00",
                        key=chave_input_disp
                    )

                    input_pc_str = st.text_input(
                        "Passivo Circulante (PC) - R$ (F18):",
                        value=str_inicial_pc,
                        placeholder="Ex: 100.000,00",
                        key=chave_input_pc
                    )

                with c2:
                    link_f18 = st.text_area(
                        f"Link/Evidência (F18 - Liquidez Imediata RAAE) ({ano_sel}):", 
                        value=evidencia_f18_salva, 
                        key=chave_link_f18, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f18 = st.empty()
                    links_f18_visuais = re.findall(REGEX_PURE_URL, link_f18 or "")
                    if links_f18_visuais:
                        placeholder_links_f18.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f18_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real
                v_disp_exib = converte_moeda_br_para_float(input_disp_str)
                v_pc_exib = max(converte_moeda_br_para_float(input_pc_str), 0.01) # Trava contra divisão por zero
                
                il_exib = round(v_disp_exib / v_pc_exib, 4)

                if v_disp_exib == 0.0 and (link_f18.strip() == ""):
                    pts_f18_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ 0,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if il_exib >= 1.0000:
                        pts_f18_exib = 75.0
                        texto_resultado_exib = "✅ ADEQUADO: Disponível cobre totalmente o Passivo Circulante"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    elif 0.8000 < il_exib < 1.0000:
                        calc_pts = ((il_exib - 0.8000) * 75.0) / 0.2000
                        pts_f18_exib = min(max(calc_pts, 0.0), 75.0)
                        texto_resultado_exib = "⚠️ GRADUAÇÃO PROPORCIONAL: Cobertura parcial do passivo"
                        estilo_status_exib = "color: #d97706; font-weight: bold;"
                    else:
                        pts_f18_exib = 0.0
                        texto_resultado_exib = "🚨 CRÍTICO: Índice de liquidez imediata muito baixo (≤ 0,80)"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"

                    texto_pontuacao_exib = f"{pts_f18_exib:.2f}".replace(".", ",") + " pontos"

                str_disp_fmt = f"R$ {v_disp_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_pc_fmt = f"R$ {v_pc_exib:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                str_il_fmt = f"{il_exib:.4f}".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Razão:</b> {str_disp_fmt} / {str_pc_fmt}<br>
                    📊 <b>Resultado do Indicador (IL):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_il_fmt}</code><br>
                    ⚖️ <b>Situação de Liquidez:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F18", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F18", key=f"btn_salvar_f18_{ano_sel}", type="primary"):
                    v_disp = converte_moeda_br_para_float(st.session_state.get(chave_input_disp, input_disp_str))
                    v_pc = max(converte_moeda_br_para_float(st.session_state.get(chave_input_pc, input_pc_str)), 0.01)
                    
                    il = round(v_disp / v_pc, 4)

                    if il >= 1.0000:
                        pts_f18 = 75.0
                    elif 0.8000 < il < 1.0000:
                        calc_pts = ((il - 0.8000) * 75.0) / 0.2000
                        pts_f18 = min(max(calc_pts, 0.0), 75.0)
                    else:
                        pts_f18 = 0.0

                    str_banco = f"{v_disp:.2f}/{v_pc:.2f}"
                    lnk_val_f18 = link_f18.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f18, dF18.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F18",
                        valor=str_banco,
                        pontos=pts_f18,
                        link=lnk_val_f18,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F18"] = {
                        "valor": str_banco,
                        "pontos": pts_f18,
                        "link": lnk_val_f18,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f18 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f18_salva or "")]

                    if lnk_val_f18 != evidencia_f18_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f18_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f18_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F18 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f18_salvos = float(dF18.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F18 Registrado: {pts_f18_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F18 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f18_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F18", st.session_state.get(f"links_pendentes_f18_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f18_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F19 • LIMITE DE ENDIVIDAMENTO – REGRA DE OURO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f19_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F19 - Limite de Endividamento – Regra de Ouro ({ano_sel})", expanded=True):
                st.subheader("F19 • Limite de Endividamento – Regra de Ouro [RO = OC - DC - AL]")
                st.write("**Verifica se as operações de crédito ultrapassaram o volume de despesas de capital**")

                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Resultado da Regra de Ouro ($RO$) | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Menor ou igual a ZERO ($RO \le 0$) | ✅ 0,00 ponto (Regra Cumprida / Sem Penalidade) |
                | Maior que ZERO ($RO > 0$) | 🚨 **REBAIXA 1 FAIXA DO I-FISCAL** (Descumprimento Crítico) |
                """)
                st.caption("ℹ️ *Variáveis extraídas dos demonstrativos fiscais e balanços anuais consolidados do município.*")

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Helper de formatação monetária BRL segura
                def fmt_brl(valor: float) -> str:
                    sinal = "-" if valor < 0 else ""
                    return f"{sinal}R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                # Estado inicial / persistente (formato salvo no banco: "OC/DC/AL")
                dF19 = res_data.get("F19") or {"valor": "0.00/0.00/0.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_oc, val_salvo_dc, val_salvo_al = str(dF19.get("valor", "0.00/0.00/0.00")).split("/")
                    float_oc = float(val_salvo_oc)
                    float_dc = float(val_salvo_dc)
                    float_al = float(val_salvo_al)
                except Exception:
                    float_oc, float_dc, float_al = 0.0, 0.0, 0.0

                # Formatação monetária inicial para exibição
                str_inicial_oc = fmt_brl(float_oc)
                str_inicial_dc = fmt_brl(float_dc)
                str_inicial_al = fmt_brl(float_al)
                evidencia_f19_salva = dF19.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_oc = f"txt_f19_oc_{ano_sel}_fiscal"
                chave_input_dc = f"txt_f19_dc_{ano_sel}_fiscal"
                chave_input_al = f"txt_f19_al_{ano_sel}_fiscal"
                chave_link_f19 = f"txt_f19_link_{ano_sel}_fiscal"
                chave_coment_f19 = f"coment_F19_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    input_oc_str = st.text_input(
                        "Operações de Crédito Realizadas (OC) - R$:",
                        value=str_inicial_oc,
                        placeholder="Ex: 500.000,00",
                        key=chave_input_oc
                    )

                    input_dc_str = st.text_input(
                        "Despesas de Capital Liquidadas (DC) - R$:",
                        value=str_inicial_dc,
                        placeholder="Ex: 600.000,00",
                        key=chave_input_dc
                    )

                    input_al_str = st.text_input(
                        "Autorizações por Maioria Absoluta (AL) - R$:",
                        value=str_inicial_al,
                        placeholder="Ex: 50.000,00",
                        key=chave_input_al
                    )

                with c2:
                    link_f19 = st.text_area(
                        f"Link/Evidência (F19 - Regra de Ouro Balanços) ({ano_sel}):", 
                        value=evidencia_f19_salva, 
                        key=chave_link_f19, 
                        placeholder="Insira os links e evidências...",
                        height=210
                    )
                    
                    placeholder_links_f19 = st.empty()
                    links_f19_visuais = re.findall(REGEX_PURE_URL, link_f19 or "")
                    if links_f19_visuais:
                        placeholder_links_f19.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f19_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real (Sem salvar até o clique do botão)
                v_oc_exib = converte_moeda_br_para_float(input_oc_str)
                v_dc_exib = converte_moeda_br_para_float(input_dc_str)
                v_al_exib = converte_moeda_br_para_float(input_al_str)
                
                v_ro_exib = round(v_oc_exib - v_dc_exib - v_al_exib, 2)

                if v_oc_exib == 0.0 and v_dc_exib == 0.0 and v_al_exib == 0.0 and (link_f19.strip() == ""):
                    pts_f19_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ Verificar Regra"
                    estilo_status_exib = "color: #64748b;"
                else:
                    pts_f19_exib = 0.0
                    if v_ro_exib > 0.00:
                        texto_resultado_exib = "🚨 CRÍTICO: Regra de Ouro Descumprida! Rebaixar 1 faixa do i-Fiscal"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"
                    else:
                        texto_resultado_exib = "✅ REGULAR: Operações de crédito compatíveis com os investimentos"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"

                    texto_pontuacao_exib = "0,00 pontos"

                str_oc_fmt = fmt_brl(v_oc_exib)
                str_dc_fmt = fmt_brl(v_dc_exib)
                str_al_fmt = fmt_brl(v_al_exib)
                str_ro_fmt = fmt_brl(v_ro_exib)

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Fórmula (RO = OC - DC - AL):</b> {str_oc_fmt} - {str_dc_fmt} - {str_al_fmt}<br>
                    📊 <b>Resultado da Regra (RO):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_ro_fmt}</code><br>
                    ⚖️ <b>Situação Constitucional:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F19", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F19", key=f"btn_salvar_f19_{ano_sel}", type="primary"):
                    v_oc = converte_moeda_br_para_float(st.session_state.get(chave_input_oc, input_oc_str))
                    v_dc = converte_moeda_br_para_float(st.session_state.get(chave_input_dc, input_dc_str))
                    v_al = converte_moeda_br_para_float(st.session_state.get(chave_input_al, input_al_str))
                    
                    v_ro = round(v_oc - v_dc - v_al, 2)
                    pts_f19 = 0.0

                    str_banco = f"{v_oc:.2f}/{v_dc:.2f}/{v_al:.2f}"
                    lnk_val_f19 = link_f19.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f19, dF19.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F19",
                        valor=str_banco,
                        pontos=pts_f19,
                        link=lnk_val_f19,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F19"] = {
                        "valor": str_banco,
                        "pontos": pts_f19,
                        "link": lnk_val_f19,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f19 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f19_salva or "")]

                    if lnk_val_f19 != evidencia_f19_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f19_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f19_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F19 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f19_salvos = float(dF19.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F19 Registrado: {pts_f19_salvos:.2f} pontos registrados no sistema</span>",
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F19 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f19_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F19", st.session_state.get(f"links_pendentes_f19_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f19_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F20 • PERCENTUAL DA TAXA DE INVESTIMENTO
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f20_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F20 - Percentual da Taxa de Investimento ({ano_sel})", expanded=True):
                st.subheader("F20 • Percentual da Taxa de Investimento [(L + F) / M = N]")
                st.write("**Mede a taxa de investimento real líquida em relação à receita total arrecadada**")

                # Tabela Oficial de Regras de Pontuação
                st.markdown(r"""
                | Resultado do Índice $N$ | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Maior ou igual a 0,15 ($N \ge 0,15$) | ✅ 50,00 pontos (Pontuação Máxima) |
                | Entre 0,02 e 0,15 ($> 0,02$ e $< 0,15$) | ⚠️ Graduação proporcional entre 0 e 50 pontos |
                | Menor ou igual a 0,02 ($N \le 0,02$) | 🚨 0,00 ponto (Baixo Índice de Investimento) |
                """)
                st.caption("ℹ️ *Despesa classificada no elemento '44 - Investimentos' (Portaria MPOG nº 163/2001) via Sistema AUDESP.*")

                # Memória de cálculo oficial fornecida
                st.markdown("""
                <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
                        <li><b>Para resultados maiores que 0,02 e menores que 0,15:</b> A graduação será distribuída utilizando a fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">P = ((N – 0,02) / 0,13) * 50</code> <br><i>Exemplo: se N = 0,1000 (10% de taxa), a nota do indicador será exatamente 30,77 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Helper de formatação monetária BRL segura
                def fmt_brl(valor: float) -> str:
                    sinal = "-" if valor < 0 else ""
                    return f"{sinal}R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                # Estado inicial / persistente (formato salvo no banco: "L/F/M")
                dF20 = res_data.get("F20") or {"valor": "0.00/0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_l, val_salvo_f, val_salvo_m = str(dF20.get("valor", "0.00/0.00/1.00")).split("/")
                    float_l = float(val_salvo_l)
                    float_f = float(val_salvo_f)
                    float_m = float(val_salvo_m)
                except Exception:
                    float_l, float_f, float_m = 0.0, 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_l = fmt_brl(float_l)
                str_inicial_f = fmt_brl(float_f)
                str_inicial_m = fmt_brl(float_m)
                evidencia_f20_salva = dF20.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_l = f"txt_f20_l_{ano_sel}_fiscal"
                chave_input_f = f"txt_f20_f_{ano_sel}_fiscal"
                chave_input_m = f"txt_f20_m_{ano_sel}_fiscal"
                chave_link_f20 = f"txt_f20_link_{ano_sel}_fiscal"
                chave_coment_f20 = f"coment_F20_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    input_l_str = st.text_input(
                        "Despesa Liquidada Total - Cat. 44 (L) - R$:",
                        value=str_inicial_l,
                        placeholder="Ex: 90.000,00",
                        key=chave_input_l
                    )

                    input_f_str = st.text_input(
                        "Liq. Restos a Pagar Não Processados (F) - R$:",
                        value=str_inicial_f,
                        placeholder="Ex: 10.000,00",
                        key=chave_input_f
                    )

                    input_m_str = st.text_input(
                        "Receita Total Arrecadada no Período (M) - R$:",
                        value=str_inicial_m,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_m
                    )

                with c2:
                    link_f20 = st.text_area(
                        f"Link/Evidência (F20 - Taxa de Investimento AUDESP) ({ano_sel}):", 
                        value=evidencia_f20_salva, 
                        key=chave_link_f20, 
                        placeholder="Insira os links e evidências...",
                        height=210
                    )
                    
                    placeholder_links_f20 = st.empty()
                    links_f20_visuais = re.findall(REGEX_PURE_URL, link_f20 or "")
                    if links_f20_visuais:
                        placeholder_links_f20.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f20_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real (Sem salvar até o clique do botão)
                v_l_exib = converte_moeda_br_para_float(input_l_str)
                v_f_exib = converte_moeda_br_para_float(input_f_str)
                v_m_exib = max(converte_moeda_br_para_float(input_m_str), 0.01)  # Proteção contra divisão por zero
                
                N_exib = round((v_l_exib + v_f_exib) / v_m_exib, 4)

                if v_l_exib == 0.0 and v_f_exib == 0.0 and (link_f20.strip() == ""):
                    pts_f20_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ 0,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if N_exib >= 0.1500:
                        pts_f20_exib = 50.0
                        texto_resultado_exib = "✅ EXCELENTE: Alto percentual de aplicação em investimentos"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    elif 0.0200 < N_exib < 0.1500:
                        pts_f20_exib = ((N_exib - 0.0200) / 0.1300) * 50.0
                        texto_resultado_exib = "⚠️ GRADUAÇÃO PROPORCIONAL: Nível intermediário de investimentos"
                        estilo_status_exib = "color: #d97706; font-weight: bold;"
                    else:  # N_exib <= 0.0200
                        pts_f20_exib = 0.0
                        texto_resultado_exib = "🚨 CRÍTICO: Índice de investimento igual ou abaixo do limite de tolerância (≤ 2%)"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"

                    texto_pontuacao_exib = f"{pts_f20_exib:.2f} pontos".replace(".", ",")

                str_l_fmt = fmt_brl(v_l_exib)
                str_f_fmt = fmt_brl(v_f_exib)
                str_m_fmt = fmt_brl(v_m_exib)
                str_n_fmt = f"{N_exib:.4f}".replace(".", ",")
                str_n_pct = f"{N_exib * 100:.2f}".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Equação [(L + F) / M]:</b> ({str_l_fmt} + {str_f_fmt}) / {str_m_fmt}<br>
                    📊 <b>Resultado da Taxa (N):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_n_fmt}</code> ({str_n_pct}% de aplicação)<br>
                    ⚖️ <b>Situação de Alocação:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F20", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F20", key=f"btn_salvar_f20_{ano_sel}", type="primary"):
                    v_l = converte_moeda_br_para_float(st.session_state.get(chave_input_l, input_l_str))
                    v_f = converte_moeda_br_para_float(st.session_state.get(chave_input_f, input_f_str))
                    v_m = max(converte_moeda_br_para_float(st.session_state.get(chave_input_m, input_m_str)), 0.01)

                    N = round((v_l + v_f) / v_m, 4)

                    if v_l == 0.0 and v_f == 0.0 and (link_f20.strip() == ""):
                        pts_f20 = 0.0
                    else:
                        if N >= 0.1500:
                            pts_f20 = 50.0
                        elif 0.0200 < N < 0.1500:
                            pts_f20 = ((N - 0.0200) / 0.1300) * 50.0
                        else:
                            pts_f20 = 0.0

                    str_banco = f"{v_l:.2f}/{v_f:.2f}/{v_m:.2f}"
                    lnk_val_f20 = link_f20.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f20, dF20.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F20",
                        valor=str_banco,
                        pontos=pts_f20,
                        link=lnk_val_f20,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F20"] = {
                        "valor": str_banco,
                        "pontos": pts_f20,
                        "link": lnk_val_f20,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f20 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f20_salva or "")]

                    if lnk_val_f20 != evidencia_f20_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f20_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f20_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F20 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f20_salvos = float(dF20.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F20 Registrado: {pts_f20_salvos:.2f} pontos registrados no sistema</span>".replace(".", ","),
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F20 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f20_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F20", st.session_state.get(f"links_pendentes_f20_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f20_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F21 • RELAÇÃO DESPESAS / RECEITAS CORRENTES
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f21_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F21 - Relação Despesas Correntes / Receitas Correntes ({ano_sel})", expanded=True):
                st.subheader("F21 • Relação Despesas Correntes / Receitas Correntes [LDC = DC / RC]")
                st.write("**Verifica o cumprimento do limite constitucional de gastos (Art. 167-A da CF)**")

                # Tabela Oficial de Regras de Pontuação (Penalidades)
                st.markdown(r"""
                | Resultado do Índice $LDC$ | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Menor ou igual a 0,85 ($LDC \le 0,85$) | ✅ 0,00 ponto (Situação Confortável / Sem Penalidade) |
                | Entre 0,85 e 0,95 ($> 0,85$ e $\le 0,95$) | ⚠️ Graduação proporcional entre 0 e -50 pontos (Perda) |
                | Maior que 0,95 ($LDC > 0,95$) | 🚨 -50,00 pontos (Penalidade Máxima por Estouro de Teto) |
                """)
                st.caption("ℹ️ *Dados consolidados (Prefeitura, Câmara e Autarquias) com base no Relatório de Instrução AUDESP, item GF56.*")

                # Memória de cálculo oficial fornecida
                st.markdown("""
                <div style="background-color: #fff5f5; padding: 12px; border-radius: 4px; border-left: 3px solid #e53e3e; margin-bottom: 15px;">
                    <p style="margin-bottom: 8px; font-size: 13px; color: #9b2c2c;">📊 <b>Regra de Penalização Proporcional no Intervalo:</b></p>
                    <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px; color: #9b2c2c;">
                        <li><b>Para resultados maiores que 0,85 e menores ou iguais a 0,95:</b> A perda de pontos será distribuída utilizando a fórmula: <br><code style="background-color: #fed7d7; padding: 2px 5px; color: #9b2c2c;">P = ((LDC – 0,85) / 0,10) * (-50)</code> <br><i>Exemplo: se LDC = 0,9300 (93% de comprometimento), a nota do indicador será exatamente de -40,00 pontos.</i></li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Helper de formatação monetária BRL segura
                def fmt_brl(valor: float) -> str:
                    sinal = "-" if valor < 0 else ""
                    return f"{sinal}R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                # Estado inicial / persistente (formato salvo no banco: "DC/RC")
                dF21 = res_data.get("F21") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_dc, val_salvo_rc = str(dF21.get("valor", "0.00/1.00")).split("/")
                    float_dc = float(val_salvo_dc)
                    float_rc = float(val_salvo_rc)
                except Exception:
                    float_dc, float_rc = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_dc = fmt_brl(float_dc)
                str_inicial_rc = fmt_brl(float_rc)
                evidencia_f21_salva = dF21.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_dc = f"txt_f21_dc_{ano_sel}_fiscal"
                chave_input_rc = f"txt_f21_rc_{ano_sel}_fiscal"
                chave_link_f21 = f"txt_f21_link_{ano_sel}_fiscal"
                chave_coment_f21 = f"coment_F21_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    input_dc_str = st.text_input(
                        "Despesa Corrente Liquidada (DC) - R$:",
                        value=str_inicial_dc,
                        placeholder="Ex: 850.000,00",
                        key=chave_input_dc
                    )

                    input_rc_str = st.text_input(
                        "Receita Corrente Total (RC) - R$ (F21):",
                        value=str_inicial_rc,
                        placeholder="Ex: 1.000.000,00",
                        key=chave_input_rc
                    )

                with c2:
                    link_f21 = st.text_area(
                        f"Link/Evidência (F21 - Relação Corrente AUDESP) ({ano_sel}):", 
                        value=evidencia_f21_salva, 
                        key=chave_link_f21, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f21 = st.empty()
                    links_f21_visuais = re.findall(REGEX_PURE_URL, link_f21 or "")
                    if links_f21_visuais:
                        placeholder_links_f21.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f21_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real (Sem salvar até o clique do botão)
                v_dc_exib = converte_moeda_br_para_float(input_dc_str)
                v_rc_exib = max(converte_moeda_br_para_float(input_rc_str), 0.01)  # Proteção contra divisão por zero
                
                LDC_exib = round(v_dc_exib / v_rc_exib, 4)

                if v_dc_exib == 0.0 and (link_f21.strip() == ""):
                    pts_f21_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ 0,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if LDC_exib <= 0.8500:
                        pts_f21_exib = 0.0
                        texto_resultado_exib = "✅ ADEQUADO: Gastos correntes equilibrados e sob controle"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    elif 0.8500 < LDC_exib <= 0.9500:
                        pts_f21_exib = round(((LDC_exib - 0.8500) / 0.1000) * (-50.0), 2)
                        texto_resultado_exib = "⚠️ ALERTA: Próximo ao limite prudencial (Incidência de Penalidade)"
                        estilo_status_exib = "color: #d97706; font-weight: bold;"
                    else:  # LDC_exib > 0.9500
                        pts_f21_exib = -50.0
                        texto_resultado_exib = "🚨 CRÍTICO: Violação do teto do Art. 167-A da CF (> 95%)"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"

                    sinal_pontos = "" if pts_f21_exib >= 0 else " "
                    texto_pontuacao_exib = f"{sinal_pontos}{pts_f21_exib:.2f} pontos".replace(".", ",")

                str_dc_fmt = fmt_brl(v_dc_exib)
                str_rc_fmt = fmt_brl(v_rc_exib)
                str_ldc_fmt = f"{LDC_exib:.4f}".replace(".", ",")
                str_ldc_pct = f"{LDC_exib * 100:.2f}".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Razão (DC / RC):</b> {str_dc_fmt} / {str_rc_fmt}<br>
                    📊 <b>Resultado do Indicador (LDC):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_ldc_fmt}</code> ({str_ldc_pct}% de comprometimento)<br>
                    ⚖️ <b>Enquadramento Legal:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Glosa/Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #dc2626;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F21", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F21", key=f"btn_salvar_f21_{ano_sel}", type="primary"):
                    v_dc = converte_moeda_br_para_float(st.session_state.get(chave_input_dc, input_dc_str))
                    v_rc = max(converte_moeda_br_para_float(st.session_state.get(chave_input_rc, input_rc_str)), 0.01)

                    LDC = round(v_dc / v_rc, 4)

                    if v_dc == 0.0 and (link_f21.strip() == ""):
                        pts_f21 = 0.0
                    else:
                        if LDC <= 0.8500:
                            pts_f21 = 0.0
                        elif 0.8500 < LDC <= 0.9500:
                            pts_f21 = round(((LDC - 0.8500) / 0.1000) * (-50.0), 2)
                        else:
                            pts_f21 = -50.0

                    str_banco = f"{v_dc:.2f}/{v_rc:.2f}"
                    lnk_val_f21 = link_f21.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f21, dF21.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F21",
                        valor=str_banco,
                        pontos=pts_f21,
                        link=lnk_val_f21,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F21"] = {
                        "valor": str_banco,
                        "pontos": pts_f21,
                        "link": lnk_val_f21,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f21 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f21_salva or "")]

                    if lnk_val_f21 != evidencia_f21_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f21_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f21_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F21 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f21_salvos = float(dF21.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F21 Registrado: {pts_f21_salvos:.2f} pontos registrados no sistema</span>".replace(".", ","),
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F21 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f21_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F21", st.session_state.get(f"links_pendentes_f21_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f21_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: INDICADOR F22 • LIQUIDEZ DOS RESTOS A PAGAR
        # =============================================================================
        with st.container(key=f"container_bloco_ifiscal_f22_{ano_sel}", border=True):
            with st.expander(f"📌 Indicador F22 - Liquidez dos Restos a Pagar ({ano_sel})", expanded=True):
                st.subheader("F22 • Liquidez dos Restos a Pagar [LRP = RPA / D]")
                st.write("**Mede a capacidade de pagamento do estoque de restos a pagar com base na disponibilidade de caixa**")

                # Tabela Oficial de Regras de Pontuação (Penalidades)
                st.markdown(r"""
                | Resultado do Índice $LRP$ | Impacto / Pontuação do Indicador |
                | :--- | :--- |
                | Menor ou igual a 1 ($LRP \le 1$) | ✅ 0,00 ponto (Cobertura de Caixa Suficiente / Sem Penalidade) |
                | Maior que 1 ($LRP > 1$) | 🚨 -5,00 pontos (Caixa Insuficiente para Cobrir Restos a Pagar) |
                """)
                st.caption("ℹ️ *Variáveis extraídas do Relatório de Análises Anuais Eletrônicas (RAAE) e do Relatório de Instrução (RI).*")

                # Função para higienizar e converter strings monetárias brasileiras para float
                def converte_moeda_br_para_float(texto: str) -> float:
                    if not texto:
                        return 0.0
                    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
                    if "." in limpo and "," in limpo:
                        limpo = limpo.replace(".", "").replace(",", ".")
                    elif "," in limpo:
                        limpo = limpo.replace(",", ".")
                    try:
                        return float(limpo)
                    except ValueError:
                        return 0.0

                # Helper de formatação monetária BRL segura
                def fmt_brl(valor: float) -> str:
                    sinal = "-" if valor < 0 else ""
                    return f"{sinal}R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                # Estado inicial / persistente (formato salvo no banco: "RPA/D")
                dF22 = res_data.get("F22") or {"valor": "0.00/1.00", "pontos": 0.0, "link": "", "comentarios": ""}
                
                try:
                    val_salvo_rpa, val_salvo_d = str(dF22.get("valor", "0.00/1.00")).split("/")
                    float_rpa = float(val_salvo_rpa)
                    float_d = float(val_salvo_d)
                except Exception:
                    float_rpa, float_d = 0.0, 1.0

                # Formatação monetária inicial para exibição
                str_inicial_rpa = fmt_brl(float_rpa)
                str_inicial_d = fmt_brl(float_d)
                evidencia_f22_salva = dF22.get("link", "")

                # Chaves padronizadas para o session_state do iFiscal
                chave_input_rpa = f"txt_f22_rpa_{ano_sel}_fiscal"
                chave_input_d = f"txt_f22_d_{ano_sel}_fiscal"
                chave_link_f22 = f"txt_f22_link_{ano_sel}_fiscal"
                chave_coment_f22 = f"coment_F22_{ano_sel}_fiscal"

                c1, c2 = st.columns([1, 2])

                with c1:
                    input_rpa_str = st.text_input(
                        "Estoque de Restos a Pagar - Proc. e Não Proc. (RPA) - R$:",
                        value=str_inicial_rpa,
                        placeholder="Ex: 150.000,00",
                        key=chave_input_rpa
                    )

                    input_d_str = st.text_input(
                        "Disponibilidade de Caixa / Disponível (D) - R$:",
                        value=str_inicial_d,
                        placeholder="Ex: 200.000,00",
                        key=chave_input_d
                    )

                with c2:
                    link_f22 = st.text_area(
                        f"Link/Evidência (F22 - Liquidez Restos a Pagar RAAE/RI) ({ano_sel}):", 
                        value=evidencia_f22_salva, 
                        key=chave_link_f22, 
                        placeholder="Insira os links e evidências...",
                        height=150
                    )
                    
                    placeholder_links_f22 = st.empty()
                    links_f22_visuais = re.findall(REGEX_PURE_URL, link_f22 or "")
                    if links_f22_visuais:
                        placeholder_links_f22.markdown(
                            "**🔗 Ativos:** " 
                            + " | ".join(
                                [
                                    f"[{u[0] if isinstance(u, tuple) else u}]({u[0] if isinstance(u, tuple) else u})" 
                                    for u in links_f22_visuais
                                ]
                            )
                        )

                # Cálculo projetado em tempo real (Sem salvar até o clique do botão)
                v_rpa_exib = converte_moeda_br_para_float(input_rpa_str)
                v_d_exib = max(converte_moeda_br_para_float(input_d_str), 0.01)  # Proteção contra divisão por zero
                
                LRP_exib = round(v_rpa_exib / v_d_exib, 4)

                if v_rpa_exib == 0.0 and (link_f22.strip() == ""):
                    pts_f22_exib = 0.0
                    texto_resultado_exib = "Aguardando preenchimento..."
                    texto_pontuacao_exib = "⏳ 0,00 pontos"
                    estilo_status_exib = "color: #64748b;"
                else:
                    if LRP_exib <= 1.0000:
                        pts_f22_exib = 0.0
                        texto_resultado_exib = "✅ ADEQUADO: O saldo em caixa cobre integralmente as obrigações de restos a pagar"
                        estilo_status_exib = "color: #16a34a; font-weight: bold;"
                    else:  # LRP_exib > 1.0000
                        pts_f22_exib = -5.0
                        texto_resultado_exib = "🚨 CRÍTICO: Despesas postergadas sem suficiência de caixa financeira"
                        estilo_status_exib = "color: #dc2626; font-weight: bold;"

                    sinal_pontos = "" if pts_f22_exib >= 0 else " "
                    texto_pontuacao_exib = f"{sinal_pontos}{pts_f22_exib:.2f} pontos".replace(".", ",")

                str_rpa_fmt = fmt_brl(v_rpa_exib)
                str_d_fmt = fmt_brl(v_d_exib)
                str_lrp_fmt = f"{LRP_exib:.4f}".replace(".", ",")

                st.markdown(f"""
                <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
                    📌 <b>Cálculo da Razão (RPA / D):</b> {str_rpa_fmt} / {str_d_fmt}<br>
                    📊 <b>Resultado do Indicador (LRP):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_lrp_fmt}</code><br>
                    ⚖️ <b>Suficiência de Caixa:</b> <span style="{estilo_status_exib}">{texto_resultado_exib}</span><br>
                    🎯 <b>Glosa/Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #dc2626;">{texto_pontuacao_exib}</code>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")

                # Bloco de comentários padronizado do iFiscal
                bloco_comentarios_ifiscal("F22", res_data, sufixo="fiscal")

                # -----------------------------------------------------------------
                # BOTÃO DE SALVAMENTO MANUAL ATÔMICO
                # -----------------------------------------------------------------
                if st.button("💾 Salvar Indicador F22", key=f"btn_salvar_f22_{ano_sel}", type="primary"):
                    v_rpa = converte_moeda_br_para_float(st.session_state.get(chave_input_rpa, input_rpa_str))
                    v_d = max(converte_moeda_br_para_float(st.session_state.get(chave_input_d, input_d_str)), 0.01)

                    LRP = round(v_rpa / v_d, 4)

                    if v_rpa == 0.0 and (link_f22.strip() == ""):
                        pts_f22 = 0.0
                    else:
                        if LRP <= 1.0000:
                            pts_f22 = 0.0
                        else:
                            pts_f22 = -5.0

                    str_banco = f"{v_rpa:.2f}/{v_d:.2f}"
                    lnk_val_f22 = link_f22.strip()
                    comentario_para_salvar = st.session_state.get(chave_coment_f22, dF22.get("comentarios", ""))

                    # Salva no banco de dados via infraestrutura do iFiscal
                    save_resp_ifiscal(
                        qid="F22",
                        valor=str_banco,
                        pontos=pts_f22,
                        link=lnk_val_f22,
                        comentarios=comentario_para_salvar
                    )

                    # Atualiza estrutura res_data em memória
                    res_data["F22"] = {
                        "valor": str_banco,
                        "pontos": pts_f22,
                        "link": lnk_val_f22,
                        "comentarios": comentario_para_salvar
                    }

                    # Verificação de alteração de links para modal de auditoria
                    links_atuais = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, lnk_val_f22 or "")]
                    links_antigos = [u[0] if isinstance(u, tuple) else u for u in re.findall(REGEX_PURE_URL, evidencia_f22_salva or "")]

                    if lnk_val_f22 != evidencia_f22_salva and links_atuais and links_atuais != links_antigos:
                        st.session_state[f"links_pendentes_f22_{ano_sel}"] = links_atuais
                        st.session_state[f"gatilho_modal_f22_{ano_sel}"] = True

                    st.cache_data.clear()
                    st.toast("Métricas do Indicador F22 salvas com sucesso!", icon="✅")
                    st.rerun()

                # Exibição do status de salvamento
                pts_f22_salvos = float(dF22.get("pontos", 0.0))
                st.markdown(
                    f"<span style='color:#28a745; font-weight:bold;'>"
                    f"📊 Status F22 Registrado: {pts_f22_salvos:.2f} pontos registrados no sistema</span>".replace(".", ","),
                    unsafe_allow_html=True
                )

        # GATILHO DO MODAL F22 (Executado fora do container)
        if st.session_state.get(f"gatilho_modal_f22_{ano_sel}", False):
            if "modal_aviso_link" in globals():
                modal_aviso_link("F22", st.session_state.get(f"links_pendentes_f22_{ano_sel}", []))
            st.session_state[f"gatilho_modal_f22_{ano_sel}"] = False

        with aba_graf:
            st.subheader("📈 Série Histórica de Pontuação")
            st.caption("Acompanhamento da evolução da pontuação fiscal do município ao longo dos anos")

            # -------------------------------------------------------------------------
            # 1. INICIALIZAÇÃO E RECUPERAÇÃO DOS DADOS HISTÓRICOS
            # -------------------------------------------------------------------------
            historico_anos = st.session_state.get("lista_anos_disponiveis", [ano_sel])
            
            # Inicialização explícita da variável para evitar UnboundLocalError / NameError
            dados_serie_historica = []
            
            for ano_h in sorted(historico_anos):
                # Obtém a estrutura de dados salva para o ano específico
                res_ano = st.session_state.get(f"res_data_{ano_h}", res_data if str(ano_h) == str(ano_sel) else {})
                
                # Soma dos pontos do questionário i-Fiscal (F01 a F19)
                pts_quest = sum(
                    float((res_ano.get(f"F{i:02d}") or {}).get("pontos", 0.0))
                    for i in range(1, 20)
                )
                
                # Soma das glosas/penalidades dos indicadores externos (F20, F21, F22)
                pts_ext = sum(
                    float((res_ano.get(f"F{q}") or {}).get("pontos", 0.0))
                    for q in ["20", "21", "22"]
                )
                
                total_ano = pts_quest + pts_ext
                dados_serie_historica.append({
                    "Ano": str(ano_h),
                    "Pontuação Total": round(total_ano, 2),
                    "Questionário": round(pts_quest, 2),
                    "Indicadores Externos": round(pts_ext, 2)
                })

            # -------------------------------------------------------------------------
            # 2. CARTÕES DE MÉTRICA DE APOIO
            # -------------------------------------------------------------------------
            pts_atual = next((d["Pontuação Total"] for d in dados_serie_historica if d["Ano"] == str(ano_sel)), 0.0)
            
            c_kpi1, c_kpi2 = st.columns(2)
            with c_kpi1:
                st.metric(
                    label=f"Pontuação Total - {ano_sel}",
                    value=f"{pts_atual:.2f} pts".replace(".", ",")
                )
            with c_kpi2:
                st.metric(
                    label="Anos Mapeados no Sistema",
                    value=len(dados_serie_historica)
                )

            st.markdown("---")

            # -------------------------------------------------------------------------
            # 3. RENDERIZAÇÃO DO GRÁFICO DE BARRAS
            # -------------------------------------------------------------------------
            try:
                import plotly.express as px
                import pandas as pd

                df_historico = pd.DataFrame(dados_serie_historica)

                fig_barras = px.bar(
                    df_historico,
                    x="Ano",
                    y="Pontuação Total",
                    text="Pontuação Total",
                    title="Evolução da Pontuação i-Fiscal por Ano",
                    color_discrete_sequence=["#1e3a8a"]
                )

                fig_barras.update_traces(
                    texttemplate="%{text:.2f}",
                    textposition="outside"
                )

                fig_barras.update_layout(
                    xaxis_title="Exercício Fiscal",
                    yaxis_title="Pontuação Total",
                    height=420,
                    margin=dict(l=20, r=20, t=50, b=20),
                    yaxis=dict(zeroline=True, zerolinewidth=1, zerolinecolor="#cbd5e1")
                )

                st.plotly_chart(fig_barras, use_container_width=True)

                with st.expander("📋 Ver Tabela de Dados Históricos Consolidados"):
                    st.dataframe(df_historico, use_container_width=True, hide_index=True)

            except ImportError:
                st.markdown("### 📊 Pontuação Total por Ano")
                chart_data = {d["Ano"]: d["Pontuação Total"] for d in dados_serie_historica}
                st.bar_chart(chart_data)
