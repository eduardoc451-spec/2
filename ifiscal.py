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
# BANCO DE DADOS NEON (UNIFICADO)
# =============================================================================
def get_connection():
    """Conecta ao banco Neon PostgreSQL usando st.secrets."""
    return psycopg2.connect(st.secrets["DATABASE_URL"], sslmode="require")


def init_db():
    """Inicializa a tabela unificada no PostgreSQL."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS respostas (
                        id VARCHAR(100) NOT NULL,
                        ano INT NOT NULL,
                        valor TEXT,
                        pontos NUMERIC DEFAULT 0,
                        link TEXT,
                        comentarios TEXT,
                        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id, ano)
                    );
                """)
            conn.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar banco Neon: {e}")

# Executa criação ao importar o módulo
try:
    init_db()
except Exception as e:
    logging.error(f"Erro na inicialização automática do BD: {e}")


def load_respostas(ano):
    dados_ano = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, valor, pontos, link, comentarios FROM respostas WHERE ano = %s",
                    (int(ano),),
                )
                rows = cursor.fetchall()
                for row in rows:
                    qid, valor, pontos, link, comentarios_raw = row
                    try:
                        comentarios_lista = json.loads(comentarios_raw) if comentarios_raw else []
                    except Exception:
                        comentarios_lista = []

                    dados_ano[qid] = {
                        "valor": valor,
                        "pontos": float(pontos) if pontos is not None else 0.0,
                        "link": link,
                        "comentarios": comentarios_lista,
                    }
    except Exception as e:
        logging.error(f"Erro ao carregar respostas do Neon: {e}")
    return dados_ano


def save_resp(qid, valor, pontos, link, comentarios=None):
    ano_sel = st.session_state.get("ano_referencia_global")
    if not ano_sel:
        return

    comentarios_json = json.dumps(comentarios, ensure_ascii=False) if comentarios is not None else "[]"
    timestamp_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO respostas (id, ano, valor, pontos, link, comentarios, atualizado_em)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id, ano) DO UPDATE SET
                        valor = EXCLUDED.valor,
                        pontos = EXCLUDED.pontos,
                        link = EXCLUDED.link,
                        comentarios = COALESCE(EXCLUDED.comentarios, respostas.comentarios),
                        atualizado_em = EXCLUDED.atualizado_em;
                    """,
                    (qid, int(ano_sel), str(valor), float(pontos), str(link), comentarios_json, timestamp_atual),
                )
            conn.commit()
    except Exception as e:
        st.error(f"Erro ao salvar {qid} no Neon: {e}")


def bloco_comentarios(questao_id, res_data, sufixo="fiscal"):
    """Gera o diálogo interno com histórico e gerenciamento de comentários."""
    ano_sel = st.session_state.get("ano_referencia_global", datetime.now().year)
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))

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

    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"

    with st.expander(
        f"💬 Diálogo Interno {id_chave} | Status: {badge_status}",
        expanded=(status_global == "Pendente"),
    ):
        st.markdown("<b style='font-size: 13px;'>Status Atual do Quesito:</b>", unsafe_allow_html=True)
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global)

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
            save_resp(
                qid=questao_id,
                valor=dados_questao.get("valor", ""),
                pontos=dados_questao.get("pontos", 0.0),
                link=dados_questao.get("link", ""),
                comentarios=historico,
            )
            st.rerun()

        st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

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
                    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                    if st.button("🗑️", key=f"btn_del_com_{id_chave}_{idx}_{ano_sel}", help="Excluir este comentário"):
                        historico.pop(idx)
                        save_resp(
                            qid=questao_id,
                            valor=dados_questao.get("valor", ""),
                            pontos=dados_questao.get("pontos", 0.0),
                            link=dados_questao.get("link", ""),
                            comentarios=historico,
                        )
                        st.rerun()
        else:
            st.markdown("<p style='font-size: 12px; color: #999; font-style: italic;'>Nenhum comentário enviado ainda.</p>", unsafe_allow_html=True)

        st.markdown("<b style='font-size: 13px;'>Adicionar Novo Comentário:</b>", unsafe_allow_html=True)

        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False

        novo_texto = st.text_area("Digite sua mensagem:", key=key_texto, height=80, label_visibility="collapsed")

        if st.button("Postar Comentário", key=f"btn_com_{id_chave}_{ano_sel}", type="primary"):
            if novo_texto.strip():
                nova_mensagem = {
                    "autor": usuario_atual,
                    "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "texto": novo_texto.strip(),
                    "status_definido": status_global,
                }
                historico.append(nova_mensagem)
                save_resp(
                    qid=questao_id,
                    valor=dados_questao.get("valor", ""),
                    pontos=dados_questao.get("pontos", 0.0),
                    link=dados_questao.get("link", ""),
                    comentarios=historico,
                )
                st.session_state[key_estado_limpar] = True
                st.rerun()


def get_all_years_data():
    all_data = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, ano, valor, pontos, link, comentarios FROM respostas ORDER BY ano DESC")
                rows = cursor.fetchall()
                for row in rows:
                    qid, ano, valor, pontos, link, comentarios_raw = row
                    try:
                        comentarios_lista = json.loads(comentarios_raw) if comentarios_raw else []
                    except Exception:
                        comentarios_lista = []

                    if ano not in all_data:
                        all_data[ano] = {}
                    all_data[ano][qid] = {
                        "valor": valor,
                        "pontos": float(pontos) if pontos is not None else 0.0,
                        "link": link,
                        "comentarios": comentarios_lista,
                    }
    except Exception as e:
        logging.error(f"Erro ao buscar histórico no Neon: {e}")
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
# 2. SIDEBAR E PAINEL - iFiscal
# =============================================================================


def render_sidebar():
    st.sidebar.title("🏛️ Painel de Controle - i-Fiscal")
    anos = [2024, 2025, 2026, 2027, 2028, 2029, 2030]

    # Seleção do ano no session_state
    ano_sel = st.sidebar.selectbox(
        "Ano de Referência:", anos, key="ano_referencia_ifiscal"
    )

    # Função de carregamento das respostas
    res_data = (
        load_respostas_ifiscal(ano_sel)
        if "load_respostas_ifiscal" in globals()
        else load_respostas(ano_sel)
    )

    total_pts = sum(
        item.get("pontos", 0.0)
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
            pdf_bytes = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa)

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
# 3. GRÁFICOS E HISTÓRICO - iFiscal
# =============================================================================


def get_all_years_data_ifiscal() -> dict:
    """Busca o histórico de dados de todos os anos salvos no banco e session_state."""
    all_data = {}

    # 1. Carrega via Banco PostgreSQL (Neon)
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        "SELECT DISTINCT ano FROM respostas_ifiscal ORDER BY ano"
                    )
                except Exception:
                    conn.rollback()
                    cursor.execute(
                        "SELECT DISTINCT ano FROM respostas ORDER BY ano"
                    )

                anos_banco = [row[0] for row in cursor.fetchall()]
                for a in anos_banco:
                    all_data[a] = (
                        load_respostas_ifiscal(a)
                        if "load_respostas_ifiscal" in globals()
                        else load_respostas(a)
                    )
    except Exception as e:
        logging.error(
            f"Erro ao buscar histórico de anos i-Fiscal no banco: {e}"
        )

    # 2. Carrega via Session State (captura dados dinâmicos em memória)
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
            v.get("pontos", 0.0)
            for k, v in res.items()
            if isinstance(v, dict) and not k.startswith("COM_")
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
        # Elementos do formulário do questionário aqui

    with aba_ext:
        st.subheader("🌐 Indicadores e Dados Externos")
        st.write(
            "Visualização de dados importados de fontes governamentais externas (Siconfi, Finbra, etc.)."
        )

    with aba_graf:
        render_graficos(res_data, ano_sel)
