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
import json
import logging
import warnings
from datetime import datetime

import psycopg2
import streamlit as st

# =============================================================================
# IMPORTS DO REPORTLAB (CORRIGIDOS COM ALINHAMENTOS ENUMS)
# =============================================================================
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
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
# CONFIGURAÇÃO DE ESTILOS PADRÃO PARA RELATÓRIOS PDF (iSaúde)
# =============================================================================
styles = getSampleStyleSheet()

# Estilo Padrão para Tabelas
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

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES INICIAIS E SUPRESSÃO DE WARNINGS
# -----------------------------------------------------------------------------
warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)

PONTUACOES_MAX_ISAUDE = {
    "1": 5, "2": 10, "3": 10, "3.1": 4, "3.2": 4, "4": 6, "5": 4, "6": 5, "7": 3, "8": 2,
    "9": 18, "9.2": 5, "10": 100, "11": 10, "11.2": 2, "12.0": 10, "12.1": 50, "12.2": 40,
    "13": 5, "13.1": 15, "14": 1, "14.1": 10, "14.2": 2, "14.2.1": 10, "15": 2, "15.1": 7,
    "16": 10, "16.1": 5, "21": 10, "22": 30, "23.1": 30, "24.1": 10, "25": 5, "26": 10,
    "27": 5, "28": 5, "28.1": 5, "29": 15, "30.1.1": 9, "32.1": 45, "33.1": 10, "34.0": 5,
    "35.1": 15, "35.2": 10, "36": 40, "36.1": 40, "37": 90, "S2": 20, "S3": 25, "S4": 10,
    "S5": 10, "S6": 100, "S7": 20, "S17": 25, "S18": 25, "S19": 25, "S20": 25
}

CATEGORIAS_MAP_ISAUDE = {
    "atencao_basica": {
        "label": "1.0 Atenção Básica",
        "qids": ["1", "2", "3", "3.1", "3.2", "4", "5", "6", "7", "8", "9", "9.2"]
    },
    "vigilancia_saude": {
        "label": "2.0 Vigilância em Saúde",
        "qids": ["10", "11", "11.2", "12.0", "12.1", "12.2", "13", "13.1"]
    },
    "assistencia_farmaceutica": {
        "label": "3.0 Assistência Farmacêutica",
        "qids": ["14", "14.1", "14.2", "14.2.1", "15", "15.1", "16", "16.1"]
    },
    "infraestrutura_ubs": {
        "label": "4.0 Infraestrutura de UBS",
        "qids": ["21", "22", "23.1", "24.1", "25", "26", "27", "28", "28.1", "29"]
    },
    "gestao_recursos": {
        "label": "5.0 Gestão e Recursos Humanos",
        "qids": ["30.1.1", "32.1", "33.1", "34.0", "35.1", "35.2", "36", "36.1", "37"]
    },
    "financiamento_minimo": {
        "label": "6.0 Limite Constitucional (SIOPS)",
        "qids": ["S2", "S3", "S4", "S5", "S6", "S7", "S17", "S18", "S19", "S20"] 
    }
}

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO - iSaúde
# =============================================================================
@st.dialog("⚠️ Atenção! Evidência em Link Externo (iSaúde)")
def modal_aviso_link_isaude(qid, links_encontrados):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    for lk in links_encontrados:
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")

    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**

    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}_saude"):
        st.rerun()

# =============================================================================
# BANCO DE DADOS NEON (ISOLADO PARA O iSAÚDE)
# =============================================================================
def get_connection():
    """Conecta ao banco Neon PostgreSQL usando st.secrets."""
    return psycopg2.connect(st.secrets["DATABASE_URL"], sslmode="require")


def init_db_isaude():
    """Inicializa a tabela EXCLUSIVA do i-Saúde no PostgreSQL."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS respostas_isaude (
                        id SERIAL PRIMARY KEY,
                        ano INT NOT NULL,
                        quesito VARCHAR(50) NOT NULL,
                        resposta TEXT,
                        pontos DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                        detalhes JSONB DEFAULT '{}'::jsonb,
                        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT unq_ano_quesito_isaude UNIQUE(ano, quesito)
                    );
                    """
                )
            conn.commit()
    except Exception as e:
        logging.error(f"Erro ao inicializar tabela respostas_isaude: {e}")


# Inicializa a tabela do iSaúde ao importar
try:
    init_db_isaude()
except Exception as e:
    logging.error(f"Erro na inicialização da tabela respostas_isaude: {e}")


def load_respostas_isaude(ano):
    """Carrega EXCLUSIVAMENTE as respostas do i-Saúde do banco."""
    dados_ano = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT quesito, resposta, pontos, detalhes FROM respostas_isaude WHERE ano = %s",
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
        logging.error(f"Erro ao carregar respostas_isaude do Neon: {e}")
    return dados_ano


def save_resp_isaude(qid, valor, pontos, link, comentarios=None):
    """Salva a resposta do i-Saúde isolada na tabela respostas_isaude."""
    ano_sel = st.session_state.get(
        "ano_referencia_isaude",
        st.session_state.get("ano_referencia_global", datetime.now().year),
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
                    INSERT INTO respostas_isaude (ano, quesito, resposta, pontos, detalhes, atualizado_em)
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
        st.error(f"Erro ao salvar {qid} na tabela respostas_isaude: {e}")


def bloco_comentarios_isaude(questao_id, res_data, sufixo="saude"):
    """Gera o diálogo interno com histórico e gerenciamento de comentários do iSaúde."""
    ano_sel = st.session_state.get(
        "ano_referencia_isaude", datetime.now().year
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
            save_resp_isaude(
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
                            <div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #0d9488;">
                                <span style="font-size: 11px; color: #0d9488; font-weight: bold;">{com['autor']}</span>
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
                        save_resp_isaude(
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
                save_resp_isaude(
                    qid=questao_id,
                    valor=dados_questao.get("valor", ""),
                    pontos=dados_questao.get("pontos", 0.0),
                    link=dados_questao.get("link", ""),
                    comentarios=historico,
                )
                st.session_state[key_estado_limpar] = True
                st.rerun()


def get_all_years_data_isaude():
    """Busca histórico EXCLUSIVO do i-Saúde no Neon."""
    all_data = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT quesito, ano, resposta, pontos, detalhes FROM respostas_isaude ORDER BY ano DESC"
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
        logging.error(f"Erro ao buscar histórico do iSaúde no Neon: {e}")
    return all_data

# =============================================================================
# CONFIGURAÇÃO DE ESTILOS PADRÃO PARA RELATÓRIOS PDF (iSaúde)
# =============================================================================
styles = getSampleStyleSheet()

# --- ESTILOS DE CAPA (ADICIONE ESTE BLOCO) ---
style_titulo_capa = ParagraphStyle(
    "TituloCapaISaude",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=24,
    leading=28,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#0D9488"),  # Cor customizada (ex: Teal)
    spaceAfter=15,
)

style_subtitulo_capa = ParagraphStyle(
    "SubtituloCapaISaude",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=14,
    leading=18,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#4B5563"),
    spaceAfter=30,
)

# =============================================================================
# MÉTODOS DE EXIBIÇÃO DA INTERFACE (RESOLVENDO O ATTRIBUTEERROR)
# =============================================================================

def mostrar_formulario_saude():
    """Renderiza o Formulário da Dimensão i-Saúde no Streamlit."""
    st.title("🏥 i-Saúde - Avaliação de Saúde Pública")
    st.markdown("Preencha as informações dos quesitos da dimensão i-Saúde.")

    ano_sel = st.selectbox(
        "Selecione o Ano de Referência:",
        options=[datetime.now().year, datetime.now().year - 1, datetime.now().year - 2],
        key="ano_referencia_isaude",
    )

    dados_salvos = load_respostas_isaude(ano_sel)

    total_obtido = sum(d.get("pontos", 0.0) for d in dados_salvos.values())
    total_maximo = sum(PONTUACOES_MAX_ISAUDE.values())
    perc_atingido = (total_obtido / total_maximo * 100) if total_maximo > 0 else 0.0

    st.metric(
        label="Pontuação Acumulada no i-Saúde",
        value=f"{total_obtido:.1f} / {total_maximo} pts",
        delta=f"{perc_atingido:.1f}% do total",
    )

    st.markdown("---")

    for cat_key, cat_data in CATEGORIAS_MAP_ISAUDE.items():
        with st.expander(f"📁 {cat_data['label']}", expanded=False):
            for qid in cat_data["qids"]:
                max_pts = PONTUACOES_MAX_ISAUDE.get(qid, 0)
                info_q = dados_salvos.get(qid, {})

                st.subheader(f"Quesito {qid} (Máx: {max_pts} pts)")

                v_opcoes = ["Não Atende", "Atende Parcialmente", "Atende Integralmente"]
                v_resposta_atual = info_q.get("valor", "Não Atende")
                idx_sel = v_opcoes.index(v_resposta_atual) if v_resposta_atual in v_opcoes else 0

                resp_selecionada = st.radio(
                    f"Situação do Quesito {qid}:",
                    options=v_opcoes,
                    index=idx_sel,
                    key=f"rad_isaude_{qid}_{ano_sel}",
                )

                pts_calculados = 0.0
                if resp_selecionada == "Atende Integralmente":
                    pts_calculados = float(max_pts)
                elif resp_selecionada == "Atende Parcialmente":
                    pts_calculados = float(max_pts) / 2.0

                link_evidencia = st.text_input(
                    f"Link/Evidência para o Quesito {qid}:",
                    value=info_q.get("link", ""),
                    key=f"link_isaude_{qid}_{ano_sel}",
                )

                if link_evidencia:
                    urls = re.findall(r"https?://[^\s]+", link_evidencia)
                    if urls and st.button(f"Verificar Acesso Externo ao Link ({qid})", key=f"btn_link_chk_{qid}"):
                        modal_aviso_link_isaude(qid, urls)

                if st.button(f"💾 Salvar Quesito {qid}", key=f"btn_save_isaude_{qid}_{ano_sel}"):
                    save_resp_isaude(
                        qid=qid,
                        valor=resp_selecionada,
                        pontos=pts_calculados,
                        link=link_evidencia,
                        comentarios=info_q.get("comentarios", []),
                    )
                    st.success(f"Quesito {qid} salvo com sucesso! ({pts_calculados} pts)")
                    st.rerun()

                bloco_comentarios_isaude(qid, dados_salvos)


def mostrar_dashboard_isaude():
    """Gera o painel visual e estatístico das respostas do i-Saúde."""
    st.title("📊 Dashboard - i-Saúde")
    all_data = get_all_years_data_isaude()

    if not all_data:
        st.info("Nenhum dado registrado até o momento.")
        return

    anos_disponiveis = sorted(list(all_data.keys()), reverse=True)
    ano_sel = st.selectbox("Ano de Análise:", anos_disponiveis, key="dash_ano_isaude")

    dados_ano = all_data.get(ano_sel, {})
    
    categorias = []
    pontos_obtidos = []
    pontos_possiveis = []

    for c_key, c_info in CATEGORIAS_MAP_ISAUDE.items():
        categorias.append(c_info["label"])
        pts_obt = sum(dados_ano.get(q, {}).get("pontos", 0.0) for q in c_info["qids"])
        pts_max = sum(PONTUACOES_MAX_ISAUDE.get(q, 0) for q in c_info["qids"])
        pontos_obtidos.append(pts_obt)
        pontos_possiveis.append(pts_max)

    fig = go.Figure(data=[
        go.Bar(name='Pontuação Atingida', x=categorias, y=pontos_obtidos, marker_color='#0d9488'),
        go.Bar(name='Pontuação Máxima Possível', x=categorias, y=pontos_possiveis, marker_color='#cbd5e1')
    ])
    fig.update_layout(barmode='group', title=f"Desempenho por Categoria - {ano_sel}")
    st.plotly_chart(fig, use_container_width=True)


def mostrar_relatorio_isaude():
    """Exibe resumos e permite download de relatório."""
    st.title("📄 Relatórios do i-Saúde")
    st.info("Utilize este espaço para exportar o diagnóstico consolidado da Saúde.")

# =============================================================================
# 2. GERADOR DO RELATÓRIO PDF (i-Saúde)
# =============================================================================

def gerar_relatorio_pdf_isaude(dados, ano, total, faixa, all_data=None):
    """Gera o documento PDF consolidado para o i-Saúde."""
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

    # Título do Relatório
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0d9488"),
    )

    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#4b5563"),
    )

    elements.append(Paragraph("Relatório de Avaliação - i-Saúde", title_style))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(f"Ano de Referência: <b>{ano}</b> | Pontuação Total: <b>{total:.2f} pts</b> ({faixa})", subtitle_style))
    elements.append(Spacer(1, 15))

    # Tabela com resumo por Categoria
    tabela_resumo_dados = [
        [
            Paragraph("Categoria / Eixo", style_tabela_cabecalho),
            Paragraph("Pontuação Obtida", style_tabela_cabecalho),
        ]
    ]

    for cat_key, cat_info in CATEGORIAS_MAP_ISAUDE.items():
        pts_cat = sum(dados.get(qid, {}).get("pontos", 0.0) for qid in cat_info["qids"])
        tabela_resumo_dados.append([
            Paragraph(cat_info["label"], style_tabela_esquerda),
            Paragraph(f"{pts_cat:.2f}", style_tabela_centro),
        ])

    t_resumo = Table(tabela_resumo_dados, colWidths=[350, 185])
    t_resumo.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d9488")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    elements.append(t_resumo)
    elements.append(Spacer(1, 15))

    # Detalhamento de Respostas
    elements.append(Paragraph("Detalhamento por Quesito", ParagraphStyle("SectionHeader", fontName="Helvetica-Bold", fontSize=14, leading=16, textColor=colors.HexColor("#0f172a"))))
    elements.append(Spacer(1, 10))

    tabela_detalhes_dados = [
        [
            Paragraph("Quesito", style_tabela_cabecalho),
            Paragraph("Resposta", style_tabela_cabecalho),
            Paragraph("Pontos", style_tabela_cabecalho),
            Paragraph("Evidência / Link", style_tabela_cabecalho),
        ]
    ]

    for qid, info in dados.items():
        val = info.get("valor", "-")
        pts = info.get("pontos", 0.0)
        link = info.get("link", "-")
        tabela_detalhes_dados.append([
            Paragraph(str(qid), style_tabela_centro),
            Paragraph(str(val), style_tabela_esquerda),
            Paragraph(f"{pts:.2f}", style_tabela_centro),
            Paragraph(str(link), style_tabela_esquerda),
        ])

    t_detalhes = Table(tabela_detalhes_dados, colWidths=[60, 200, 60, 215])
    t_detalhes.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    elements.append(t_detalhes)

    # -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 100))
    try:
        logo = Image("ifiscal.png", width=380, height=180)
        logo.hAlign = 'CENTER'
        elements.append(logo)
    except Exception:
        elements.append(Paragraph("[Logo: ifiscal.png]", styles["Title"]))
        
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("Relatório i-Fiscal", style_titulo_capa))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("Índice de Fiscalização e Gestão da Saúde Municipal", ParagraphStyle('SubCapa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=14, leading=18, textColor=colors.HexColor("#718096"), alignment=1)))
    elements.append(Spacer(1, 15))
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#00897b"), alignment=2)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa de Gestão da Saúde)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito i-Fiscal", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades (Eficiência Preventiva)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências (Gargalos Persistentes)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030 (Metas ODS / ONU)", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
        [Paragraph("6. Análise Comparativa de Prazos e Indicadores Históricos", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
        [Paragraph("7. Série Histórica do i-Fiscal (Consolidado Final)", style_item_esquerda), Paragraph("Pág. 6", style_pag_direita)],
    ]

    tabela_sumario = Table(dados_sumario, colWidths=[400, 90])
    tabela_sumario.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7"), 1, (2, 4)), 
    ]))
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-FISCAL (GESTÃO EM SAÚDE) - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA DE GESTÃO DA SAÚDE)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))

    nota_atual = float(total)

    def converter_pontos_em_faixa_ifiscal(pontos):
        pts = float(pontos)
        if pts <= 500.0: return "C"
        elif pts <= 599.0: return "C+"
        elif pts <= 749.0: return "B"
        elif pts <= 899.0: return "B+"
        else: return "A"

    nota_anterior = 0.0
    if ano_ant in all_data:
        nota_anterior = float(sum(info_ant.get("pontos", 0) for qid_ant, info_ant in dados_ano_anterior.items() if isinstance(info_ant, dict) and not qid_ant.startswith("COM_") and not ("_" in qid_ant and not qid_ant.startswith("S"))))

    faixa_anterior = converter_pontos_em_faixa_ifiscal(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_ifiscal(nota_atual)
    variacao_pontos = nota_atual - nota_anterior

    texto_percentual = f"{(variacao_pontos / nota_anterior) * 100:+.2f}%" if nota_anterior > 0 else "0.00%"

    if variacao_pontos > 0:
        cor_variacao = colors.HexColor("#28a745")
        seta_tendencia = "▲"
    elif variacao_pontos < 0:
        cor_variacao = colors.HexColor("#dc3545")
        seta_tendencia = "▼"
    else:
        cor_variacao = colors.HexColor("#6c757d")
        seta_tendencia = "■"

    style_th = ParagraphStyle('Th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAno', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_td_pts = ParagraphStyle('TdPts', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor("#00897b"), alignment=1)
    style_td_var = ParagraphStyle('TdVar', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_variacao, alignment=1)

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
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global da gestão em saúde comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores assistenciais e orçamentários da saúde em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade i-Fiscal."
    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # =========================================================================
    # 2. ANÁLISE DE DESEMPENHO POR QUESITO i-FISCAL
    # =========================================================================
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO i-FISCAL</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []
    dados_consolidados = {}

    def normalizar_chave(c):
        s = str(c).strip()
        if s.endswith('.0'):
            s = s[:-2]
        return s

    pontuacoes_max_norm = {normalizar_chave(k): v for k, v in PONTUACOES_MAX_IFISCAL.items()}

    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")
        qid_limpo = normalizar_chave(qid)
        
        if qid_limpo not in pontuacoes_max_norm:
            continue
        if qid_limpo not in dados_consolidados:
            dados_consolidados[qid_limpo] = {"pts_obtidos": 0.0, "valores": [], "links": []}
            
        dados_consolidados[qid_limpo]["pts_obtidos"] += pts_obtidos
        if valor_resposta:
            dados_consolidados[qid_limpo]["valores"].append(limpar_xml(valor_resposta))
        if link_evidencia:
            link_limpo = limpar_xml(link_evidencia)
            if link_limpo not in dados_consolidados[qid_limpo]["links"]:
                dados_consolidados[qid_limpo]["links"].append(link_limpo)
                
    for qid_norm, info in dados_consolidados.items():
        pts_maximo = float(pontuacoes_max_norm.get(qid_norm, 10.0))
        if pts_maximo <= 0: pts_maximo = 10.0
        pts_obtidos = max(0.0, min(info["pts_obtidos"], pts_maximo))
        eficiencia = (pts_obtidos / pts_maximo) * 100
        respostas_unificadas = " | ".join(info["valores"]) if info["valores"] else "-"
        evidencias_unificadas = ", ".join(info["links"]) if info["links"] else ""
        
        item_data = {
            "qid": qid_norm, 
            "pts_obtidos": pts_obtidos, 
            "pts_maximo": pts_maximo, 
            "eficiencia": eficiencia, 
            "valor": respostas_unificadas, 
            "link": evidencias_unificadas
        }
        if eficiencia < 80.0: 
            lista_pontos_fracos.append(item_data)
        else:
            lista_pontos_fortes.append(item_data)
            
    if lista_pontos_fortes:
        elements.append(Paragraph("<b>✅ Pontos Fortes da Gestão da Saúde:</b>", styles["h3"]))
        data_fortes = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Nota / Teto", style_th), 
            Paragraph("Eficiência", style_th), 
            Paragraph("Resposta / Evidência", style_th)
        ]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["eficiencia"], reverse=True):
            texto_celula = f"<b>{item['valor']}</b>"
            if item['link']:
                texto_celula += f"<br/><font size=8 color='gray'>{item['link']}</font>"
            data_fortes.append([
                Paragraph(item['qid'], style_tabela_centro), 
                Paragraph(f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", style_tabela_centro), 
                Paragraph(f"{item['eficiencia']:.1f}%", style_tabela_centro), 
                Paragraph(texto_celula, style_tabela_padrao)
            ])
        tabela_fortes = Table(data_fortes, colWidths=[65, 75, 65, 285])
        tabela_fortes.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00897b")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#00897b")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))
        
    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Pontos Oportunidades de Melhoria / Fragilidades (< 80% de Eficiência):</b>", styles["h3"]))
        data_fracos = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Nota / Teto", style_th), 
            Paragraph("Eficiência", style_th), 
            Paragraph("Resposta / Evidência", style_th)
        ]]
        for item in sorted(lista_pontos_fracos, key=lambda x: x["eficiencia"]):
            texto_celula = f"<b>{item['valor']}</b>"
            if item['link']:
                texto_celula += f"<br/><font size=8 color='gray'>{item['link']}</font>"
            data_fracos.append([
                Paragraph(item['qid'], style_tabela_centro), 
                Paragraph(f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", style_tabela_centro), 
                Paragraph(f"{item['eficiencia']:.1f}%", style_tabela_centro), 
                Paragraph(texto_celula, style_tabela_padrao)
            ])
        tabela_fracos = Table(data_fracos, colWidths=[65, 75, 65, 285])
        tabela_fracos.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e67e22")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fracos)
        elements.append(Spacer(1, 15))

    # =========================================================================
    # 3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)
    # =========================================================================
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    PENALIDADES_MAX = {
        "14.2.2": -2.0, "15.2": -2.0, "17.1.2": -5.0, "17.2": -0.5, "17.3": -3.0,
        "17.3.1": -3.0, "17.3.2": -2.0, "17.4": -3.0, "17.4.1": -2.0, "17.4.2": -2.0,
        "17.5": -5.0, "17.5.2": -5.0, "17.5.2.1": -5.0, "17.6": -5.0, "17.6.1": -2.5,
        "17.7.1": -5.0, "17.8.1": -5.0, "17.9.1": -5.0, "17.9.2": -5.0, "18.1": -10.0,
        "18.2": -5.0, "18.4": -5.0, "18.5.3": -10.0, "18.5.4": -10.0, "19.3": -10.0,
        "19.4": -5.0, "19.5": -15.0, "20.1": -5.0, "20.2": -5.0, "31.2": -10.0,
        "31.3": -20.0, "S8": -5.0, "S9": -5.0, "S10": -2.0, "S11": -2.0,
        "S12": -2.0, "S13": -2.0, "S14": -2.0, "S15": -2.0, "S16": -2.0
    }
    penalidades_max_norm = {normalizar_chave(k): v for k, v in PENALIDADES_MAX.items()}
    dados_penalidades = {}

    for k, v in dados.items():
        if isinstance(v, dict):
            dados_penalidades[normalizar_chave(k)] = v
            
    for qid_pen, val_max in penalidades_max_norm.items():
        if qid_pen not in dados_penalidades:
            dados_penalidades[qid_pen] = {"pontos": val_max, "valor": "Não preenchido / Ocultado por condicional", "link": ""}
            
    lista_penalidades = []
    reincidencias_detectadas = []

    for qid_norm, pen_max in penalidades_max_norm.items():
        if qid_norm in dados_penalidades:
            info = dados_penalidades[qid_norm]
            nota_real = float(info.get("pontos", 0.0))
            nota_risco = nota_real if nota_real <= 0.0 else 0.0
            
            if pen_max != 0:
                eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            else:
                eficiencia_preventiva = 100.0
                
            eficiencia_preventiva = max(0.0, min(eficiencia_preventiva, 100.0))
            lista_penalidades.append({
                "qid": qid_norm, "nota_real": nota_real, "pen_max": pen_max, "eficiencia": eficiencia_preventiva, 
                "valor": info.get("valor", ""), "link": info.get("link", "")
            })
            
            if eficiencia_preventiva < 100.0 and isinstance(all_data, dict) and (ano_ant in all_data):
                dados_ant_norm = {normalizar_chave(ka): va for ka, va in dados_ano_anterior.items() if isinstance(va, dict)}
                if qid_norm in dados_ant_norm:
                    info_ant = dados_ant_norm[qid_norm]
                    nota_real_ant = float(info_ant.get("pontos", 0.0))
                    if nota_real == nota_real_ant:
                        reincidencias_detectadas.append({
                            "qid": qid_norm, "tipo": "Penalidade Aplicada", 
                            "detalhe": f"Impacto Recorrente de Penalidade de {nota_real:.1f} pts", 
                            "ant": f"{nota_real_ant:.1f} pts", "atual": f"{nota_real:.1f} pts"
                        })
                        
    if lista_penalidades:
        data_penalidades = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Penalidade Aplicada", style_th), 
            Paragraph("Pior Cenário", style_th), 
            Paragraph("Eficiência Preventiva", style_th), 
            Paragraph("Status de Risco", style_th)
        ]]
        
        def ordenar_quesitos(x):
            limpo = ''.join(c for c in x["qid"] if c.isdigit() or c == '.')
            partes = [int(i) for i in limpo.split('.') if i.isdigit()]
            return partes if partes else [999]
            
        for item in sorted(lista_penalidades, key=ordenar_quesitos):
            nota_txt = f"{item['nota_real']:.1f} pts"
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
                Paragraph(status, style_tabela_padrao)
            ])
            
        tabela_pen = Table(data_penalidades, colWidths=[70, 110, 80, 115, 125])
        tabela_pen.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4f72")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#1b4f72")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_pen)
        elements.append(Spacer(1, 15))

    # =========================================================================
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES)
    # =========================================================================
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    TETOS_VALIDOS = {
        "14.2.2": 10.0, "15.2": 10.0, "17.1": 15.0, "17.2": 5.0, "17.3": 10.0,
        "17.4": 10.0, "17.5": 20.0, "17.6": 15.0, "17.7": 10.0, "17.8": 10.0, 
        "17.9": 10.0, "18.1": 30.0, "18.2": 20.0, "18.4": 15.0, "18.5": 25.0, 
        "19.3": 20.0, "19.4": 15.0, "19.5": 40.0, "20.1": 10.0, "20.2": 10.0, 
        "31.2": 20.0, "31.3": 50.0, "S8": 15.0, "S9": 15.0, "S10": 10.0
    }

    dados_analise_reinc = dados.copy()

    if subquestoes_saude_local and resposta_condicional_na_local:
        for sub_id in subquestoes_saude_local:
            if sub_id not in dados_analise_reinc:
                dados_analise_reinc[sub_id] = {"pontos": 0.0, "valor": "Não se aplica / Zerado por Condicional", "link": ""}

    for qid, info_atual in dados_analise_reinc.items():
        if qid.startswith("COM_") or not isinstance(info_atual, dict): 
            continue
            
        qid_str = str(qid).strip()
        qid_limpo = normalizar_chave(qid_str)
        
        valor_atual = str(info_atual.get("valor", "")).strip().lower()
        pts_obtidos_atual = float(info_atual.get("pontos", 0.0))
        
        if not valor_atual or "selecione" in valor_atual or pts_obtidos_atual == 0.0:
            continue
        
        if "_" in qid_limpo:
            chave_mae = qid_limpo.split("_")[0]
        else:
            partes_chave = qid_limpo.split('.')
            if len(partes_chave) > 2:
                chave_mae = f"{partes_chave[0]}.{partes_chave[1]}"
            else:
                chave_mae = qid_limpo
            
        if chave_mae not in TETOS_VALIDOS:
            continue

import logging
import re
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 4. SIDEBAR - iSaúde
# =============================================================================

def zerar_questionario_isaude(ano: int):
    """Deleta todas as respostas do ano selecionado da tabela do iSaúde."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM respostas_isaude WHERE ano = %s",
                    (int(ano),)
                )
            conn.commit()
        st.cache_data.clear()  # Limpa o cache após deletar
    except Exception as e:
        st.error(f"Erro ao zerar questionário iSaúde: {e}")


@st.dialog("⚠️ Zerar Respostas do iSaúde")
def confirmar_zerar_dialog_isaude(ano):
    st.warning(f"Tem certeza que deseja apagar TODAS as respostas do iSaúde para o ano {ano}?")
    st.write("Esta ação é irreversível e excluirá os dados salvos no banco Neon.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔴 Sim, Zerar Tudo", type="primary", use_container_width=True):
            try:
                zerar_questionario_isaude(ano)
                st.session_state[f"respostas_isaude_{ano}"] = {}
                st.toast("Respostas do iSaúde zeradas com sucesso!", icon="🗑️")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao zerar banco: {e}")

    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def calcular_faixa_isaude(total_pts: float, total_max: float = 688.1):
    """Calcula o percentual atingido e classifica em faixas iSaúde."""
    perc = (total_pts / total_max * 100) if total_max > 0 else 0.0
    
    if perc <= 30.0:
        faixa, cor = "Crítico", "#ef4444"
    elif perc <= 55.0:
        faixa, cor = "Básico", "#f97316"
    elif perc <= 75.0:
        faixa, cor = "Intermediário", "#eab308"
    elif perc <= 90.0:
        faixa, cor = "Aprimorado", "#22c55e"
    else:
        faixa, cor = "Excelência", "#16a34a"
        
    return faixa, cor, perc


def render_sidebar_isaude():
    st.sidebar.title("🛠️ Painel de Controle - iSaúde")
    anos = [2024, 2025, 2026, 2027, 2028, 2029, 2030]
    
    # Define o ano selecionado na session_state para sincronização
    ano_sel = st.sidebar.selectbox(
        "Ano de Referência:", 
        anos, 
        key="ano_referencia_isaude"
    )

    res_data = load_respostas_isaude(ano_sel)
    total_pts = sum(item.get("pontos", 0.0) for item in res_data.values())
    total_max = sum(PONTUACOES_MAX_ISAUDE.values())

    faixa, cor, perc = calcular_faixa_isaude(total_pts, total_max)

    st.sidebar.metric(
        label="Pontuação iSaúde", 
        value=f"{total_pts:.1f} / {total_max:.0f} pts",
        delta=f"{perc:.1f}% Atingido"
    )
    st.sidebar.markdown(
        f"**Desempenho:** <span style='color:{cor}; font-size:18px; font-weight:bold;'>{faixa}</span>",
        unsafe_allow_html=True
    )

    st.sidebar.divider()
    
    col1, col2 = st.sidebar.columns(2)
    
    # Botão de Download do Relatório em PDF do iSaúde
    with col1:
        # Nota: Certifique-se de ter a função `gerar_relatorio_pdf_isaude` definida em seu arquivo de relatórios
        pdf_bytes = gerar_relatorio_pdf_isaude(res_data, ano_sel, total_pts, faixa) if 'gerar_relatorio_pdf_isaude' in globals() else b""
        st.download_button(
            label="📄 Baixar PDF",
            data=pdf_bytes,
            file_name=f"Relatorio_iSaude_{ano_sel}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    # Botão para abrir o Modal de confirmação de exclusão
    with col2:
        if st.button("🔄 Zerar", help="Limpar todas as respostas do iSaúde para o ano selecionado", use_container_width=True):
            confirmar_zerar_dialog_isaude(ano_sel)

    return total_pts, res_data, ano_sel


# =============================================================================
# 5. GRÁFICOS E HISTÓRICO - iSaúde
# =============================================================================

def get_faixa_isaude(total: float, total_max: float = 688.1):
    faixa, _, _ = calcular_faixa_isaude(total, total_max)
    return faixa


def grafico_pontos_por_ano_isaude(all_data):
    """Gráfico de barras vertical com pontos totais por ano para a dimensão iSaúde."""
    anos = sorted(all_data.keys())
    totais = []
    cores = []
    total_max = sum(PONTUACOES_MAX_ISAUDE.values())
    
    for ano in anos:
        res = all_data[ano]
        total = sum(v.get("pontos", 0.0) for k, v in res.items() if not str(k).startswith("COM_"))
        totais.append(total)
        
        _, cor, _ = calcular_faixa_isaude(total, total_max)
        cores.append(cor)
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[str(a) for a in anos],
        y=totais,
        marker_color=cores,
        text=[f"{t:.1f} pts" for t in totais],
        textposition="outside",
        hovertemplate="<b>Ano: %{x}</b><br>iSaúde Total: %{y:.1f} pts<extra></extra>",
    ))
    
    fig.update_layout(
        title="Índice Histórico iSaúde por Exercício",
        xaxis_title="Ano",
        yaxis_title="Pontuação iSaúde",
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        height=400,
    )
    
    return fig


def render_graficos_isaude(res_data_atual, ano_sel):
    st.header("📊 Painel de Análise do iSaúde")
    
    all_data = get_all_years_data_isaude()
    
    if not all_data:
        st.info("Nenhum dado do iSaúde registrado ainda. Preencha os itens para visualizar os gráficos.")
        return

    st.plotly_chart(grafico_pontos_por_ano_isaude(all_data), use_container_width=True)


# =============================================================================
# 6. FORMULÁRIO PRINCIPAL - iSaúde
# =============================================================================

def mostrar_formulario_saude():
    dados_sidebar = render_sidebar_isaude()
    
    if dados_sidebar and len(dados_sidebar) == 3:
        total_pts, res_data, ano_sel = dados_sidebar
    else:
        total_pts, res_data, ano_sel = 0.0, {}, 2026

    st.title(f"🏥 Saúde Pública (iSaúde) - Exercício {ano_sel}")

    aba_quest, aba_graf = st.tabs(["📋 Questionário iSaúde", "📊 Gráficos & Desempenho"])
    
    with aba_quest:
        # Código de renderização das categorias e quesitos do iSaúde
        pass
        
    with aba_graf:
        render_graficos_isaude(res_data, ano_sel)
