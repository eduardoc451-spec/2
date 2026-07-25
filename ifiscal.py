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




