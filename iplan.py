import warnings
# Filtra qualquer aviso que mencione o parâmetro antigo do Streamlit
warnings.filterwarnings("ignore", message=".*use_container_width.*")
warnings.filterwarnings("ignore", category=UserWarning)

import streamlit as st
import re
import sqlite3
import json
import ast
from io import BytesIO
from datetime import datetime, date

# Bibliotecas para o PDF (Requer: pip install reportlab)
from reportlab.lib import colors as rl_colors  # Ajustado para casar com o rl_colors do seu código
from reportlab.lib import colors  # Mantido caso use 'colors.white' em outro ponto
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.lib.pagesizes import A4

# Bibliotecas para os Gráficos (Requer: pip install plotly)
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# =============================================================================
# CONSTANTES GLOBAIS
# =============================================================================

CATEGORIAS_MAP = {
    "planejamento": {"label": "Planejamento e Orçamento", "qids": ["1.0", "1.1", "1.2", "1.3", "1.3.1", "1.4", "2.0", "2.1", "3.0", "3.1", "3.1.1", "3.2", "4.0", "4.1", "4.1.1", "4.1.1.1", "4.1.1.1.1", "4.1.1.2", "4.1.1.2.1", "4.2", "4.3"]},
    "receita":       {"label": "Receita e LDO", "qids": ["5.0", "5.1", "5.1.1", "5.2", "6.0", "7.0", "7.1", "8.0", "8.1", "8.2", "9.0", "9.1", "9.2"]},
    "compatibilidade": {"label": "Compatibilidade e Créditos", "qids": ["10.0", "11.0", "11.1"]},
    "estrutura":     {"label": "Estrutura e Acompanhamento", "qids": ["12.0", "12.1", "12.1.1", "12.1.2", "13.0", "13.1", "13.1.1", "13.1.1.1", "13.2", "13.3"]},
    "controle":      {"label": "Controle Interno", "qids": ["14.0", "14.1", "14.2", "14.3", "14.4", "14.4.1", "14.4.2", "14.4.3", "14.4.4", "14.4.4.1", "14.4.4.2", "14.4.4.2.1", "14.4.5", "14.4.5.1", "14.4.5.1.1", "14.5", "14.5.1"]},
    "ouvidoria":     {"label": "Ouvidoria e Transparência", "qids": ["15.0", "15.1", "15.2", "15.3", "15.4", "15.4.1", "15.4.2", "15.5", "16.0", "16.1", "16.2", "16.3", "16.3.1", "16.3.2", "17.0", "17.1", "17.2"]},
    "plano_diretor": {"label": "Plano Diretor", "qids": ["18.0", "18.1", "19.0"]},
}

PONTUACOES_MAX = {
    "1.1": 3, "1.2": 2, "1.3.1": 3, "1.4": 4, "2.0": 6, "2.1": 2, "3.1": 14, "3.2": 10, "4.0": 10, "4.1": 15, "4.1.1": 10, "4.1.1.1": 7, "4.1.1.1.1": 60, "4.1.1.2": 4, "4.2": 25, "4.3": 15,
    "5.0": 6, "5.1": 4, "5.1.1": 2, "5.2": 6, "6.0": 3, "8.2": 3.5, "9.2": 3.5, "10.0": 17, "11.1": 6, "13.1": 6, "13.1.1": 3, "13.1.1.1": 2, "13.2": 4, "13.3": 20,
    "14.3": 15, "14.4": 0.5, "14.4.1": 5, "14.4.2": 6, "14.4.3": 5, "14.4.4": 6, "14.4.5": 5, "14.4.5.1": 6, "14.5.1": 5,
    "16.0": 4, "16.1": 2, "16.2": 2, "16.3": 4, "17.0": 4
}

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO (CORRIGIDO PARA LINKS CLICÁVEIS)
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
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}"):
        st.rerun()

# =============================================================================
# 1. FUNÇÕES DE APOIO E BANCO DE DADOS (IEGM - I-PLAN)
# =============================================================================

def get_connection():
    # Conecta no banco de dados isolado e específico do I-PLAN
    return sqlite3.connect("dados_iplan.db", check_same_thread=False)

def init_db():
    """Cria as tabelas do banco de dados com migração automática e suporte a comentários estruturados em JSON."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Cria a tabela base estruturada
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS respostas (
                id TEXT NOT NULL,
                ano INTEGER NOT NULL,
                valor TEXT,
                pontos REAL DEFAULT 0,
                link TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id, ano)
            )
        """)
        
        # 2. PRAGMA para checar quais colunas realmente existem no arquivo físico do banco do I-PLAN
        cursor.execute("PRAGMA table_info(respostas)")
        colunas_existentes = [row[1] for row in cursor.fetchall()]
        
        # 3. Força a migração da coluna de comentários em JSON se não existir
        if "comentarios" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN comentarios TEXT")
            except sqlite3.OperationalError:
                pass
                
        # 4. Garante que a coluna 'atualizado_em' esteja com o nome perfeito
        if "atualizado_em" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            except sqlite3.OperationalError:
                pass
                
        # 5. Garante a coluna criado_em
        if "criado_em" not in colunas_existentes:
            try:
                cursor.execute("ALTER TABLE respostas ADD COLUMN criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            except sqlite3.OperationalError:
                pass
                
        conn.commit()

def load_respostas(ano):
    dados_ano = {}
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, valor, pontos, link, comentarios FROM respostas WHERE ano = ?", (ano,)
            )
            for row in cursor.fetchall():
                comentarios_lista = []
                if row[4]:
                    try:
                        comentarios_lista = json.loads(row[4])
                    except Exception:
                        comentarios_lista = []
                        
                dados_ano[row[0]] = {
                    "valor": row[1], 
                    "pontos": row[2], 
                    "link": row[3],
                    "comentarios": comentarios_lista
                }
    except Exception:
        pass
    return dados_ano

def save_resp(qid, valor, pontos, link, comentarios=None):
    ano_sel = st.session_state.get("ano_referencia_global")
    if not ano_sel:
        return
    
    comentarios_json = None
    if comentarios is not None:
        comentarios_json = json.dumps(comentarios, ensure_ascii=False)
    else:
        dados_atuais = load_respostas(ano_sel)
        if qid in dados_atuais:
            comentarios_json = json.dumps(dados_atuais[qid].get("comentarios", []), ensure_ascii=False)

    try:
        timestamp_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except AttributeError:
        import datetime as dt_modulo
        timestamp_atual = dt_modulo.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO respostas (id, ano, valor, pontos, link, comentarios, atualizado_em) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (qid, ano_sel, str(valor), float(pontos), str(link), comentarios_json, timestamp_atual))
            conn.commit()
    except sqlite3.OperationalError as e:
        if "no column named atualizado_em" in str(e):
            try:
                with get_connection() as conn:
                    conn.execute("ALTER TABLE respostas ADD COLUMN atualizado_em TEXT")
                    conn.commit()
                save_resp(qid, valor, pontos, link, comentarios)
            except Exception as ex:
                st.error(f"Erro crítico ao tentar corrigir estrutura: {ex}")
        else:
            st.error(f"Erro operacional no banco do I-PLAN: {e}")
    except Exception as e:
        st.error(f"Erro ao salvar {qid}: {e}")

def bloco_comentarios(questao_id, res_data, sufixo=None):
    """
    Gera o diálogo interno avançado com histórico retrátil, status em realtime
    e controle individual de remoção por lixeira para o módulo I-PLAN.
    """
    # Busca o ano atual de forma segura direto do construtor de data do próprio Python
    import datetime as dt_modulo
    ano_atual_padrao = dt_modulo.date.today().year

    ano_sel = st.session_state.get("ano_referencia_global", ano_atual_padrao)
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
    
    with st.expander(f"💬 Diálogo Interno {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
        
        st.markdown("<b style='font-size: 13px;'>Status Atual do Quesito:</b>", unsafe_allow_html=True)
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global)
        
        novo_status_clicado = st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=f"rad_status_{id_chave}_{ano_sel}",
            label_visibility="collapsed"
        )
        
        if novo_status_clicado != status_global:
            log_mudanca = {
                "autor": "Sistema / " + usuario_atual,
                "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "texto": f"ℹ️ Alterou o status do quesito para: **{novo_status_clicado.upper()}**.",
                "status_definido": novo_status_clicado
            }
            historico.append(log_mudanca)
            save_resp(
                qid=questao_id,
                valor=dados_questao.get("valor", ""),
                pontos=dados_questao.get("pontos", 0.0),
                link=dados_questao.get("link", ""),
                comentarios=historico
            )
            st.rerun()

        st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

        if historico:
            for idx, com in enumerate(historico):
                col_balao, col_lixeira = st.columns([11, 1])
                
                with col_balao:
                    if "Sistema /" in com['autor']:
                        st.markdown(
                            f"""
                            <div style="background-color: #f1f3f5; padding: 6px 12px; border-radius: 6px; margin-bottom: 4px; border-left: 3px solid #ced4da;">
                                <span style="font-size: 11px; color: #6c757d; font-style: italic;">{com['autor']} - {com['data']}</span>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #495057; font-style: italic;">{com['texto']}</p>
                            </div>
                            """, 
                            unsafe_allow_html=True
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
                            unsafe_allow_html=True
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
                            comentarios=historico
                        )
                        st.rerun()
                        
            st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='font-size: 12px; color: #999; font-style: italic;'>Nenhum comentário enviado ainda.</p>", unsafe_allow_html=True)
            
        st.markdown("<b style='font-size: 13px;'>Adicionar Novo Comentário:</b>", unsafe_allow_html=True)
        
        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False
            
        novo_texto = st.text_area("Digite sua mensagem:", key=key_texto, height=80, label_visibility="collapsed")
        
        col_btn1, _ = st.columns([1, 3])
        with col_btn1:
            if st.button("Postar Comentário", key=f"btn_com_{id_chave}_{ano_sel}", type="primary"):
                if novo_texto.strip():
                    nova_mensagem = {
                        "autor": usuario_atual,
                        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "texto": novo_texto.strip(),
                        "status_definido": status_global
                    }
                    historico.append(nova_mensagem)
                    save_resp(
                        qid=questao_id, 
                        valor=dados_questao.get("valor", ""), 
                        pontos=dados_questao.get("pontos", 0.0), 
                        link=dados_questao.get("link", ""),
                        comentarios=historico
                    )
                    st.session_state[key_estado_limpar] = True
                    st.rerun()

def get_all_years_data():
    all_data = {}
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, ano, valor, pontos, link, comentarios FROM respostas ORDER BY ano DESC"
        )
        for row in cursor.fetchall():
            qid, ano, valor, pontos, link, comentarios_raw = row
            
            comentarios_lista = []
            if comentarios_raw:
                try:
                    comentarios_lista = json.loads(comentarios_raw)
                except Exception:
                    comentarios_lista = []
                    
            if ano not in all_data:
                all_data[ano] = {}
            all_data[ano][qid] = {
                "valor": valor, 
                "pontos": pontos, 
                "link": link, 
                "comentarios": comentarios_lista
            }
    return all_data

# =============================================================================
# 3. GERADOR DO RELATÓRIO PDF - i-PLAN
# =============================================================================

def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    # TEXTO DE TESTE FORÇADO NO LOG:
    print("\n" + "="*50)
    print("DENTRO DO GERADOR DE PDF:")
    print("O que veio no all_data?:", all_data)
    print("="*50 + "\n")    

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    
    style_titulo_capa = ParagraphStyle(
        'TituloCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica-Bold', 
        fontSize=24, 
        leading=28, 
        textColor=colors.HexColor("#2e7d32"), 
        alignment=1
    )
    
    style_ano_capa = ParagraphStyle(
        'AnoCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica', 
        fontSize=16, 
        leading=20,
        textColor=colors.HexColor("#7f8c8d"), 
        alignment=1
    )

    style_tabela_padrao = ParagraphStyle(
        'TextoTabela',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=0
    )

    style_tabela_centro = ParagraphStyle(
        'TextoTabelaCentro',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=1
    )

    def limpar_xml(texto):
        return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    if all_data is None:
        all_data = {}

    # =========================================================================
    # CORREÇÃO CRÍTICA: Força a conversão de chaves para String e faz Fallback
    # =========================================================================
    all_data_limpo = {str(k).strip(): v for k, v in all_data.items()}
    ano_alvo = str(ano).strip()[:4]
    ano_atual = int(ano_alvo)
    
    if ano_alvo not in all_data_limpo or not all_data_limpo[ano_alvo]:
        if '2024' in all_data_limpo and all_data_limpo['2024']:
            print(f"--- [AVISO PDF] Ano {ano_alvo} veio vazio. Usando fallback dos dados de 2024! ---")
            dados_historico = all_data_limpo['2024']
        else:
            dados_historico = {}
    else:
        dados_historico = all_data_limpo[ano_alvo]
    # ========================================================================= 
        
    if 'PONTUACOES_MAX' not in globals():
        PONTUACOES_MAX = {
            "1.1.2": 20.0, "1.1.3": 5.0, "1.2": 20.0, "2.0": 10.0, "2.1": 50.0, "3.0": 10.0, "3.1": 20.0, "4.0": 20.0,
            "5.2.1": 20.0, "6.0": 20.0, "6.1": 50.0, "6.2": 25.0, "7.2": 2.0, "7.3": 10.0, "7.3.1": 20.0, "7.4": 10.0,
            "7.4.1": 20.0, "7.5": 30.0, "7.7": 30.0, "7.8": 20.0, "7.8.1": 50.0, "7.9": 3.0, "8.2": 2.0, "8.3": 10.0,
            "8.4": 20.0, "8.4.1": 10.0, "8.4.2": 30.0, "8.4.3": 50.0, "9.2": 100.0, "9.3": 5.0, "9.3.1": 5.0,
            "11.2": 2.0, "11.3": 30.0, "11.3.2": 20.0, "11.3.3": 40.0, "11.5": 10.0, "12.1": 54.0, "14.3": 30.0,
            "15": 2.0, "15.1": 3.0, "A4.1.1": 90.0, "A4.1.2": 20.0, "A4.1.3": 22.0, "A6": 5.0, "11": 10.0
        }
    else:
        PONTUACOES_MAX = globals()['PONTUACOES_MAX']

    # -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 100))
    
    try:
        logo = Image("iegm.png", width=380, height=180)
        logo.hAlign = 'CENTER'
        elements.append(logo)
    except Exception:
        elements.append(Paragraph("[Logo: iegm.png]", styles["Title"]))
        
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("Relatório i-PLAN", style_titulo_capa))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("Índice de Planejamento", ParagraphStyle('SubCapa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=14, leading=18, textColor=colors.HexColor("#718096"), alignment=1)))
    elements.append(Spacer(1, 15))
    
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#2e7d32"), alignment=2)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa Planejamento)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito i-PLAN", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030 (ODS Meio Ambiente)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("6. Série Histórica Planejamento", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
    ]
    
    tabela_sumario = Table(dados_sumario, colWidths=[400, 90])
    tabela_sumario.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7"), 1, (2, 4)), 
    ]))
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-PLAN (PLANEJAMENTO) - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA I-PLAN)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))

    nota_atual = float(total)

    def converter_pontos_em_faixa_iplan(pontos):
        pts = float(pontos)
        if pts <= 499.0:     return "C"
        elif pts <= 599.0:   return "C+"
        elif pts <= 749.0:   return "B"
        elif pts <= 899.0:   return "B+"
        else:                return "A"

    # --- DESCOBERTA DINÂMICA DO HISTÓRICO REAL ANTERIOR (BLINDAGEM CONTRA SALTO DE ANOS) ---
    anos_com_dados = sorted([int(k) for k in all_data_limpo.keys() if all_data_limpo[k]], reverse=True)
    
    ano_ant_real = None
    dados_originais_ant = {}

    for a in anos_com_dados:
        if a < ano_atual:
            ano_ant_real = a
            dados_originais_ant = all_data_limpo[str(a)]
            break

    # Fallback padrão caso o banco de dados histórico esteja completamente zerado
    if ano_ant_real is None:
        ano_ant_real = ano_atual - 1
        dados_originais_ant = {}

    ano_ant = ano_ant_real
    dados_ano_anterior = {}
    
    if isinstance(dados_originais_ant, dict):
        for k, v in dados_originais_ant.items():
            dados_ano_anterior[str(k).strip()] = v

    nota_anterior = 0.0
    for qid_ant, info_ant in dados_ano_anterior.items():
        if str(qid_ant).startswith("COM_"):
            continue
            
        if isinstance(info_ant, dict):
            nota_anterior += float(info_ant.get("pontos", 0.0))
        elif isinstance(info_ant, (int, float)):
            nota_anterior += float(info_ant)

    faixa_anterior = converter_pontos_em_faixa_iplan(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_iplan(nota_atual)

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

    style_th = ParagraphStyle('Th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAno', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_td_pts = ParagraphStyle('TdPts', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor("#2e7d32"), alignment=1)
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
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global socioambientais comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores de sustentabilidade e conservação em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade ambiental."

    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # =========================================================================
    # 2. ANÁLISE DE DESEMPENHO POR QUESITO
    # =========================================================================
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []
    dados_consolidados = {}

    subquestoes_11 = ["11.2", "11.3", "11.3.2", "11.3.3", "11.5"]
    resposta_11_nao = False
    if "11" in dados and isinstance(dados["11"], dict):
        if str(dados["11"].get("valor", "")).strip().lower() in ["não", "nao", "n"]:
            resposta_11_nao = True

    for sub_id in subquestoes_11:
        if resposta_11_nao or (sub_id not in dados):
            dados[sub_id] = {
                "pontos": 0.0,
                "valor": "Não aplicável / Não implantado (Mãe respondida como Não)",
                "link": ""
            }

    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
        
        pts_obtidos = float(info.get("pontos", 0))
        valor_resposta = info.get("valor", "")
        link_evidencia = info.get("link", "")

        qid_str = str(qid).strip()
        
        if qid_str.startswith("A4.1.1_"):   chave_mae = "A4.1.1"
        elif qid_str.startswith("A4.1.2_"): chave_mae = "A4.1.2"
        elif qid_str.startswith("A4.1.3_"): chave_mae = "A4.1.3"
        elif qid_str == "11" or qid_str.startswith("11."):
            if qid_str in PONTUACOES_MAX:
                chave_mae = qid_str
            else:
                chave_mae = "11"
        else:
            chave_mae = qid_str

        if chave_mae not in PONTUACOES_MAX:
            continue

        if chave_mae not in dados_consolidados:
            dados_consolidados[chave_mae] = {"pts_obtidos": 0.0, "valores": [], "links": []}
        
        dados_consolidados[chave_mae]["pts_obtidos"] += pts_obtidos
        
        if valor_resposta:
            sub_nome = qid_str.split('_')[-1] if '_' in qid_str else qid_str
            dados_consolidados[chave_mae]["valores"].append(f"{sub_nome}: {limpar_xml(valor_resposta)}")
            
        if link_evidencia:
            link_limpo = limpar_xml(link_evidencia)
            if link_limpo not in dados_consolidados[chave_mae]["links"]:
                dados_consolidados[chave_mae]["links"].append(link_limpo)

    for qid, info in dados_consolidados.items():
        pts_maximo = float(PONTUACOES_MAX.get(qid, 10.0))
        if pts_maximo <= 0: pts_maximo = 10.0
            
        pts_obtidos = max(0.0, min(info["pts_obtidos"], pts_maximo))
        eficiencia = (pts_obtidos / pts_maximo) * 100
        
        respostas_unificadas = " | ".join(info["valores"]) if info["valores"] else "-"
        evidencias_unificadas = ", ".join(info["links"]) if info["links"] else ""

        item_data = {
            "qid": qid, 
            "pts_obtidos": pts_obtidos, 
            "pts_maximo": pts_maximo, 
            "eficiencia": eficiencia, 
            "valor": respostas_unificadas, 
            "link": evidencias_unificadas
        }

        if eficiencia >= 100.0: 
            lista_pontos_fortes.append(item_data)
        else:
            lista_pontos_fracos.append(item_data)

    # CORREÇÃO: Estruturação limpa da montagem final do esqueleto Reportlab (Substituído o 'f' solto)
    if lista_pontos_fortes:
        elements.append(Paragraph("<b>✅ Pontos Fortes Planejamento:</b>", styles["h3"]))
        data_fortes = [[
            Paragraph("Quesito", style_th), 
            Paragraph("Nota / Teto", style_th), 
            Paragraph("Eficiência", style_th), 
            Paragraph("Resposta / Evidência", style_th)
        ]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["pts_obtidos"], reverse=True):
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e7d32")), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#2e7d32")), 
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))

    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Pontos Fracos / Oportunidades de Melhoria:</b>", styles["h3"]))
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
    # 3. ANÁLISE DE IMPACTO E PENALIDADES
    # =========================================================================
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    PENALIDADES_MAX = {
    "4.3": -10.0,
    "7.1": -30.0,
    "8.1": -10.0,
    "9.1": -10.0,
    "10.0": -10.0,
    "12.1.1": -10.0,
    "12.1.2": -10.0,
    "13.1": -10.0,
    "14.4.4.1": -6.0,
    "14.4.4.2": -3.0,
    "14.4.5.1.1": -3.0,
    "15.3": -2.5,
    "15.4.1": -10.0,
    "15.4.2": -10.0,
    "15.5": -1.0,
    "18.1": -10.0
    }
   
    dados_penalidades = dados.copy()
    reincidencias_detectadas = []

    for qid_pen, val_max in PENALIDADES_MAX.items():
        if qid_pen not in dados_penalidades:
            dados_penalidades[qid_pen] = {"pontos": val_max, "valor": "Não preenchido", "link": ""}

    lista_penalidades = []
    
    for qid, pen_max in PENALIDADES_MAX.items():
        if qid in dados_penalidades:
            info = dados_penalidades[qid]
            nota_real = float(info.get("pontos", 0.0))
            nota_risco = nota_real if nota_real <= 0.0 else 0.0
            
            if pen_max != 0:
                eficiencia_preventiva = (1.0 - (nota_risco / pen_max)) * 100.0
            else:
                eficiencia_preventiva = 100.0
                
            eficiencia_preventiva = max(0.0, min(eficiencia_preventiva, 100.0))

            lista_penalidades.append({
                "qid": qid, "nota_real": nota_real, "pen_max": pen_max, "eficiencia": eficiencia_preventiva, 
                "valor": info.get("valor", ""), "link": info.get("link", "")
            })
            
            # BUSCA DINÂMICA DE REINCIDÊNCIA EM PENALIDADES
            qid_limpo = str(qid).strip()
            if eficiencia_preventiva < 100.0 and qid_limpo in dados_ano_anterior:
                info_ant = dados_ano_anterior[qid_limpo]
                if isinstance(info_ant, dict):
                    nota_real_ant = float(info_ant.get("pontos", 0.0))
                elif isinstance(info_ant, (int, float)):
                    nota_real_ant = float(info_ant)
                else:
                    nota_real_ant = 0.0
                    
                if nota_real == nota_real_ant:
                    reincidencias_detectadas.append({
                        "qid": qid, "tipo": "Penalidade Aplicada", 
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
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES i-PLAN)
    # =========================================================================
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS (GARGALOS PERSISTENTES)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    # Nota: A lista 'reincidencias_detectadas' já foi populada dinamicamente 
    # na Seção 3 ao comparar os impactos reais das penalidades entre os dois anos.

    # Renderização da Tabela de Gargalos Baseada nas Penalidades do i-PLAN
    if reincidencias_detectadas:
        data_reinc = [[
            Paragraph("Quesito", style_th),
            Paragraph("Macro-Categoria", style_th),
            Paragraph("Descrição do Gargalo", style_th),
            Paragraph("Exercício Ant.", style_th),
            Paragraph("Exercício Atual", style_th)
        ]]
        for reinc in reincidencias_detectadas:
            data_reinc.append([
                Paragraph(reinc["qid"], style_tabela_centro),
                Paragraph(reinc["tipo"], style_tabela_padrao),
                Paragraph(reinc["detalhe"], style_tabela_padrao),
                Paragraph(reinc["ant"], style_tabela_centro),
                Paragraph(reinc["atual"], style_tabela_centro)
            ])
        tabela_reinc = Table(data_reinc, colWidths=[60, 110, 170, 80, 80])
        tabela_reinc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#78281f")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#78281f")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_reinc)
    else:
        elements.append(Paragraph("<i>Nenhuma reincidência de impacto crítico por penalidade detectada entre os dois exercícios analíticos.</i>", style_analise))

    # -------------------------------------------------------------------------
    # 5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU - PADRÃO i-PLAN)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    def calcular_percentual_checklist(resposta_bruta, total_itens):
        if not resposta_bruta: return 0.0
        # Divide as opções selecionadas por vírgula
        itens = [i.strip().lower() for i in str(resposta_bruta).split(",") if i.strip()]
        # Remove eventuais strings vazias ou nulas
        itens_validos = [i for i in itens if i and "não" not in i]
        if total_itens <= 0: return 0.0
        return min((len(itens_validos) / total_itens) * 100.0, 100.0)

    analise_ods = []
    
    for qid, info in dados.items():
        if qid.startswith("COM_") or not isinstance(info, dict): 
            continue
            
        resp = str(info.get("valor", "")).strip()
        resp_l = resp.lower()
        metas = ""
        status = ""
        
        # ---------------------------------------------------------------------
        # REGRAS DE MAPEAMENTO DOS QUESITOS E METAS ODS (i-PLAN)
        # ---------------------------------------------------------------------
        if qid == "1.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "1.2":
            metas = "16.6"
            condicoes_12 = ["dia de semana após horário comercial", "aos sábados, domingos e feriados", "sábados", "domingos", "feriados"]
            status = "Atendido" if any(c in resp_l for c in condicoes_12) else "Não Atendido"
            
        elif qid == "1.3":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "1.4": # Checklist com 8 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 8):.1f}% Atendido"
            
        elif qid in ["2", "2.0"]:
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "2.1":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "3.0":
            metas = "16.6, 17.14"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "3.1":
            metas = "16.6, 17.14"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "3.2":
            metas = "16.6"
            status = "Atendido" if "sim, para todos os programas ppa" in resp_l else "Não Atendido"
            
        elif qid == "4.0":
            metas = "16.6, 17.14"
            status = "Atendido" if "sim, com metas físicas e financeiras" in resp_l else "Não Atendido"
            
        elif qid == "4.1.1.1.1": # Checklist com 3 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 3):.1f}% Atendido"
            
        elif qid == "4.1.1.2":
            metas = "16.6, 17.14"
            status = "Atendido" if "sim, para todos os programas finalísticos avaliados do ppa" in resp_l else "Não Atendido"
            
        elif qid == "4.2":
            metas = "16.6, 17.14"
            status = "Atendido" if "todos os indicadores do ppa" in resp_l else "Não Atendido"
            
        elif qid == "4.3": # Checklist com 9 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 9):.1f}% Atendido"
            
        elif qid == "5.0":
            metas = "16.6, 17.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "5.1": # Checklist com 7 opções
            metas = "16.6, 17.1"
            status = f"{calcular_percentual_checklist(resp, 7):.1f}% Atendido"
            
        elif qid == "5.1.1":
            metas = "16.6, 17.1"
            status = "Atendido" if "sim, com reestimativa da receita prevista na loa no decorrer da execução orçamentária-financeira" in resp_l else "Não Atendido"
            
        elif qid == "5.2":
            metas = "16.6, 17.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "6.0": # Checklist com 11 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 11):.1f}% Atendido"
            
        elif qid == "7.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "8.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "8.2": # Checklist com 8 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 8):.1f}% Atendido"
            
        elif qid == "9.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "9.2": # Checklist com 6 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 6):.1f}% Atendido"
            
        elif qid == "10.0": # Checklist com 9 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 9):.1f}% Atendido"
            
        elif qid == "12.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "12.1":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "12.1.1":
            metas = "16.6"
            status = "Atendido" if "sim, todos os servidores possuem qualificação técnica" in resp_l else "Não Atendido"
            
        elif qid == "12.1.2":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid in ["13", "13.0"]:
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "13.1": # Checklist com 3 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 3):.1f}% Atendido"
            
        elif qid == "13.1.1": # Checklist com 3 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 3):.1f}% Atendido"
            
        elif qid == "13.2":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "14.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "14.3": # Checklist com 15 opções
            metas = "16.6"
            status = f"{calcular_percentual_checklist(resp, 15):.1f}% Atendido"
            
        elif qid == "14.4":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "14.4.1":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "14.4.5":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "15.0":
            metas = "16.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "15.4":
            metas = "16.1"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "16.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "16.2":
            metas = "16.6, 16.7"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "16.3":
            metas = "16.6, 16.7"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "17.0":
            metas = "16.6, 16.7"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"
            
        elif qid == "18.0":
            metas = "16.6"
            status = "Atendido" if "sim" in resp_l else "Não Atendido"

        if metas: 
            analise_ods.append({"qid": qid, "status": status, "metas": metas, "resp": resp[:50]})

    if analise_ods:
        data_ods = [["Quesito", "Resposta Informada", "Vínculo Metas ODS", "Status de Cumprimento"]]
        style_td_ods = ParagraphStyle('TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        
        # Ordenação inteligente de chaves aninhadas (ex: 4.1.1.1.1 antes de 4.1.1.2)
        def sort_key_ods(x):
            partes = [int(i) for i in ''.join(c for c in x['qid'] if c.isdigit() or c == '.').split('.') if i.isdigit()]
            return partes if partes else [999]

        for item in sorted(analise_ods, key=sort_key_ods):
            st_txt = item["status"]
            if "Não Atendido" in st_txt: 
                st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif "Atendido" in st_txt and "%" not in st_txt: 
                st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else: 
                st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)
                
            data_ods.append([item["qid"], Paragraph(item["resp"], styles["Normal"]), item["metas"], st_p])
            
        tabela_ods = Table(data_ods, colWidths=[65, 195, 115, 110])
        tabela_ods.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f9d58")), 
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), 
            ("ALIGN", (0, 0), (0, -1), "CENTER"), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#0f9d58")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(tabela_ods)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 📊 6. SÉRIE HISTÓRICA DO I-PLAN (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []
    
    for a in anos_serie:
        a_str = str(a)
        
        # Alinhado de volta para 'ano_atual' e 'nota_atual' que você usa no escopo
        if a == ano_atual: 
            valores_serie.append(nota_atual)
        elif a_str in all_data and all_data[a_str]:
            soma_ano = float(sum(
                float(info_h.get("pontos", 0.0)) 
                for qid_h, info_h in all_data[a_str].items() 
                if isinstance(info_h, dict) and not qid_h.startswith("COM_")
            ))
            valores_serie.append(soma_ano)
        else: 
            valores_serie.append(0.0)

    # Configuração do Gráfico ReportLab
    desenho_grafico = Drawing(480, 165)
    bc = VerticalBarChart()
    bc.x = 45; bc.y = 25; bc.height = 110; bc.width = 410
    bc.data = [valores_serie]
    bc.categoryAxis.categoryNames = [str(a) for a in anos_serie]
    bc.categoryAxis.labels.fontSize = 9; bc.categoryAxis.labels.fontName = 'Helvetica-Bold'; bc.categoryAxis.labels.dy = -10
    
    bc.valueAxis.valueMin = 0; bc.valueAxis.valueMax = 1000; bc.valueAxis.valueStep = 200; bc.valueAxis.labels.fontSize = 8
    
    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'
    
    bc.bars[0].fillColor = colors.HexColor("#1b4f72")
    bc.bars[0].strokeColor = colors.HexColor("#2c3e50")
    bc.bars[0].strokeWidth = 0.5

    desenho_grafico.add(String(240, 150, "Série Histórica do i-PLAN", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)

    # -------------------------------------------------------------------------
    # COMPILAÇÃO FINAL DO BUFFER DO PDF
    # -------------------------------------------------------------------------
    doc.build(elements)
    buffer.seek(0)
    return buffer
    
# =============================================================================
# 2. INTERFACE E FORMULÁRIO
# =============================================================================

def render_sidebar():
    st.sidebar.title("🛠️ Painel i-PLAN")
    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos, key="ano_referencia_global")
    res_data = load_respostas(ano_sel)
    
    total_pts = sum(float(item.get("pontos", 0)) for k, item in res_data.items() if not k.startswith("COM_"))
    
    if total_pts <= 499:   faixa, cor = "C",  "red"
    elif total_pts <= 599: faixa, cor = "C+", "orange"
    elif total_pts <= 749: faixa, cor = "B",  "#d4d400"
    elif total_pts <= 899: faixa, cor = "B+", "lightgreen"
    elif total_pts <= 1000: faixa, cor = "A",  "green"

    st.sidebar.metric("Pontuação Total", f"{total_pts:.1f} pts")
    st.sidebar.markdown(f"**Faixa:** <span style='color:{cor}; font-size:20px; font-weight:bold;'>{faixa}</span>", unsafe_allow_html=True)
    
    # =========================================================================
    # CORREÇÃO: Carrega o histórico completo de todos os anos para o PDF
    # =========================================================================
    historico_completo = {}
    for ano_h in anos:
        dados_ano_h = load_respostas(ano_h)
        if dados_ano_h: # Só adiciona se houver respostas salvas para aquele ano
            historico_completo[str(ano_h)] = dados_ano_h
    # =========================================================================

    # Geração Dinâmica do PDF na Sidebar passando o historico_completo
    try:
        pdf_buffer = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa, all_data=historico_completo)
        st.sidebar.download_button(
            label="📥Relatório PDF",
            data=pdf_buffer.getvalue(),
            file_name=f"Relatorio_iPLAN_{ano_sel}.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.sidebar.error(f"Erro ao gerar PDF para download: {e}")
    
    if st.sidebar.button("🔄 Zerar Questionário"):
        with get_connection() as conn:
            conn.execute("DELETE FROM respostas WHERE ano = ?", (ano_sel,))
            conn.commit()
        
        # Limpa o session_state para desmarcar todos os widgets (radio, checkbox, etc)
        # Filtramos as chaves que terminam com o ano de referência para não afetar configurações globais
        for key in list(st.session_state.keys()):
            if key.endswith(f"_{ano_sel}"):
                del st.session_state[key]
                
        st.rerun()
        
    return total_pts, res_data, ano_sel

def mostrar_formulario_plan():
    init_db()
    total_pts, res_data, ano_sel = render_sidebar()
    
    st.markdown("""
        <style>
        .quesito-card {
            background-color: #f8f9fa;
            padding: 20px;
            border-left: 6px solid #1e3a5f;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #ddd;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title(f"📊 Auditoria i-Plan - {ano_sel}")
    
    # 1. Criamos as abas normalmente
    aba_quest, aba_graf = st.tabs(["📋 Questionário", "📈 Gráficos"])
    
    # 2. SEPARADOS: Criamos a lógica dos gráficos isolada aqui em cima
    with aba_graf:
        st.subheader("📊 Evolução dos Resultados — Série Histórica")
        st.write("Acompanhe o desempenho da pontuação total acumulada ao longo dos anos:")
        
        # Aqui montamos o gráfico em Plotly para a tela do Streamlit (já que o ReportLab é só pro PDF)
        anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
        valores_serie = []
        
        # Carrega os dados para o gráfico da tela
        for a in anos_serie:
            dados_ano_h = load_respostas(a)
            soma_ano = sum(float(item.get("pontos", 0)) for k, item in dados_ano_h.items() if not k.startswith("COM_"))
            valores_serie.append(soma_ano)
            
        import plotly.express as px
        fig = px.bar(
            x=[str(a) for a in anos_serie], 
            y=valores_serie,
            labels={'x': 'Ano de Referência', 'y': 'Pontuação Total'},
            range_y=[0, 1000]
        )
        fig.update_traces(marker_color='#1b4f72')
        st.plotly_chart(fig, use_container_width=True)
        
    # 3. O SEGREDO: Abrimos a aba de questionário e DEIXAMOS ELA ABERTA. 
    # Todo o resto do seu arquivo gigante que vem abaixo vai cair automaticamente dentro dela!
    with aba_quest:
        # --- SEÇÃO 1: AUDIÊNCIAS PÚBLICAS ---
        st.header("1.0 Audiências Públicas")
        
        # O RESTO DO SEU ARQUIVO SEGUE AQUI PARA BAIXO NORMALMENTE...
        
        # =============================================================================
        # BLOCO DE QUESITOS - 1.0 (I-PLAN)
        # =============================================================================

      # =============================================================================
        # QUESITO 1.0 • AUDIÊNCIAS PÚBLICAS ORÇAMENTÁRIAS
        # =============================================================================
        with st.container(key=f"container_bloco_audiencias_orcamentarias_1_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.0 - Audiências Públicas Orçamentárias", expanded=True):
                st.subheader("1.0 • Audiências Públicas Orçamentárias")
                st.write("**A Prefeitura realizou audiências públicas para elaboração das peças orçamentárias?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opts_1_0 = {"Selecione...": 0.0, "Sim": 0.0, "Não": 0.0}
                d10 = res_data.get("1.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d10 is None: d10 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_10 = d10.get("valor", "Selecione...")
                chave_radio_10 = f"r_1_0_{v_salvo_10}_{ano_sel}"

                regex_pure_url = r'(https?://[^\s<>"]+?)(?=[.,;:]?(\s|$))'

                def cb_radio_1_0():
                    val = st.session_state[chave_radio_10]
                    pts = opts_1_0[val]
                    lnk = st.session_state.get(f"t_1_0_{ano_sel}", d10.get("link", ""))
                    save_resp("1.0", val, pts, lnk)
                    res_data["1.0"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_1_0():
                    lnk = st.session_state[f"t_1_0_{ano_sel}"]
                    val = st.session_state.get(chave_radio_10, d10.get("valor", "Selecione..."))
                    pts = opts_1_0.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d10.get("link", "") or "")]
                    
                    mudou_opcao_10 = val != d10.get("valor", "")
                    mudou_link_10 = lnk != d10.get("link", "")
                    
                    if mudou_opcao_10 or mudou_link_10:
                        save_resp("1.0", val, pts, lnk)
                        res_data["1.0"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if mudou_link_10 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                c10_1, c10_2 = st.columns([1, 1])
                with c10_1:
                    lista_opcoes = list(opts_1_0.keys())
                    idx_salvo = lista_opcoes.index(d10["valor"]) if d10["valor"] in opts_1_0 else 0
                    sel_1_0 = st.radio("Selecione 1.0:", options=lista_opcoes, index=idx_salvo, key=chave_radio_10, on_change=cb_radio_1_0, label_visibility="collapsed")
                    pts_1_0 = opts_1_0[sel_1_0]
                    
                with c10_2:
                    link_1_0 = st.text_area("Link/Evidência (1.0):", value=d10.get("link", ""), key=f"t_1_0_{ano_sel}", on_change=cb_text_1_0, height=130)
                    placeholder_links_10 = st.empty()
                    links_1_0_visuais = [u[0] for u in re.findall(regex_pure_url, link_1_0 or "")]
                    if links_1_0_visuais:
                        placeholder_links_10.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1_0_visuais]))
                
                txt_score_10 = f"📊 Pontuação Aplicada no Quesito 1.0: {pts_1_0:.1f} pontos"
                if sel_1_0 == "Selecione...": txt_score_10 += " (Aguardando seleção)"
                st.code(txt_score_10, language="text")
                bloco_comentarios("1.0", res_data)

        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
            modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 1.1 • PEÇAS ORÇAMENTÁRIAS COM AUDIÊNCIAS
        # =============================================================================
        with st.container(key=f"container_bloco_pecas_audiencias_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.1 - Peças Orçamentárias com Audiências Públicas", expanded=True):
                st.subheader("1.1 • Peças Orçamentárias com Audiências Públicas")
                st.write("**Assinale para quais peças orçamentárias foram realizadas as audiências públicas: Considerar as audiências públicas da LOA e LDO realizadas no exercício avaliado e o último PPA elaborado**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                pecas = {"PPA inicial 2026-2029 – 01": 1.0, "LDO 2026 – 01": 1.0, "LOA 2026 – 01": 1.0}
                d11 = res_data.get("1.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d11 is None: d11 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_11 = ast.literal_eval(d11["valor"])
                    if not isinstance(lista_salva_11, list): lista_salva_11 = []
                except Exception:
                    lista_salva_11 = []

                def cb_mudanca_1_1():
                    novos_sel = []
                    novos_pts = 0.0
                    for p, pt in pecas.items():
                        if st.session_state.get(f"chk_1_1_{p}_{ano_sel}", p in lista_salva_11):
                            novos_sel.append(p)
                            novos_pts += pt
                    lnk = st.session_state.get(f"t_1_1_{ano_sel}", d11.get("link", ""))
                    str_sel = str(novos_sel)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d11.get("link", "") or "")]
                    
                    mudou_opcao_11 = str_sel != d11.get("valor", "")
                    mudou_link_11 = lnk != d11.get("link", "")
                    
                    if mudou_opcao_11 or mudou_link_11:
                        save_resp("1.1", str_sel, novos_pts, lnk)
                        res_data["1.1"] = {"valor": str_sel, "pontos": novos_pts, "link": lnk}
                        
                        if mudou_link_11 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                c11_1, c11_2 = st.columns([1, 1])
                with c11_1:
                    pts11 = 0.0
                    for p, pt in pecas.items():
                        if st.checkbox(p, value=p in lista_salva_11, key=f"chk_1_1_{p}_{ano_sel}", on_change=cb_mudanca_1_1):
                            pts11 += pt
                            
                with c11_2:
                    link_1_1 = st.text_area("Link/Evidência (1.1):", value=d11.get("link", ""), key=f"t_1_1_{ano_sel}", on_change=cb_mudanca_1_1, height=130)
                    placeholder_links_11 = st.empty()
                    links_1_1_visuais = [u[0] for u in re.findall(regex_pure_url, link_1_1 or "")]
                    if links_1_1_visuais:
                        placeholder_links_11.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1_1_visuais]))
                
                st.code(f"📊 Pontuação Aplicada no Quesito 1.1: {pts11:.1f} pontos", language="text")
                bloco_comentarios("1.1", res_data)

        if st.session_state.get(f"gatilho_modal_1_1_{ano_sel}", False):
            modal_aviso_link("1.1", st.session_state.get(f"links_pendentes_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 1.2 • DIA E HORÁRIO DAS AUDIÊNCIAS (CORRIGIDO PARA PONTUAÇÃO SOMADA)
        # =============================================================================
        with st.container(key=f"container_bloco_horarios_audiencias_1_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.2 - Dia e Horário de Realização das Audiências Públicas", expanded=True):
                st.subheader("1.2 • Dia e Horário de Realização das Audiências Públicas")
                st.write("**Assinale o dia e horário de realização das audiências públicas:**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e soma cumulativa de pontos.*")
                
                horarios = {
                    "Dia de semana em horário comercial (ex: 8 as 18 horas) – 00": 0.0, 
                    "Dia de semana após horário comercial (ex: após às 18 hours) – 02": 2.0,
                    "Aos sábados, domingos e feriados – 02": 2.0
                }
                d12 = res_data.get("1.2", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d12 is None: d12 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_12 = ast.literal_eval(d12["valor"])
                    if not isinstance(lista_salva_12, list): lista_salva_12 = []
                except Exception:
                    lista_salva_12 = []

                def cb_mudanca_1_2():
                    novos_sel = []
                    novos_pts = 0.0
                    for h, pt in horarios.items():
                        if st.session_state.get(f"chk_1_2_{h}_{ano_sel}", h in lista_salva_12):
                            novos_sel.append(h)
                            novos_pts += pt  # Corrigido: Agora soma as opções em vez de usar max()
                            
                    # Limita a pontuação ao máximo de 4.0 pontos por segurança
                    if novos_pts > 4.0: novos_pts = 4.0
                    
                    lnk = st.session_state.get(f"t_1_2_{ano_sel}", d12.get("link", ""))
                    str_sel = str(novos_sel)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d12.get("link", "") or "")]
                    
                    mudou_opcao_12 = str_sel != d12.get("valor", "")
                    mudou_link_12 = lnk != d12.get("link", "")
                    
                    if mudou_opcao_12 or mudou_link_12:
                        save_resp("1.2", str_sel, novos_pts, lnk)
                        res_data["1.2"] = {"valor": str_sel, "pontos": novos_pts, "link": lnk}
                        
                        if mudou_link_12 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                c12_1, c12_2 = st.columns([1, 1])
                with c12_1:
                    for h, pt in horarios.items():
                        st.checkbox(h, value=h in lista_salva_12, key=f"chk_1_2_{h}_{ano_sel}", on_change=cb_mudanca_1_2)
                            
                with c12_2:
                    link_1_2 = st.text_area("Link/Evidência (1.2):", value=d12.get("link", ""), key=f"t_1_2_{ano_sel}", on_change=cb_mudanca_1_2, height=130)
                    placeholder_links_12 = st.empty()
                    links_1_2_visuais = [u[0] for u in re.findall(regex_pure_url, link_1_2 or "")]
                    if links_1_2_visuais:
                        placeholder_links_12.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1_2_visuais]))
                
                pts_atuais_12 = d12.get("pontos", 0.0)
                cor_txt_12 = "#28a745" if pts_atuais_12 > 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_12}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.2: {pts_atuais_12:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.2", res_data, ano_sel)

        # GATILHO DO MODAL 1.2
        if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
            modal_aviso_link("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.3 • TRANSCRIÇÃO DAS AUDIÊNCIAS
        # =============================================================================
        with st.container(key=f"container_bloco_transcricao_audiencias_1_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.3 - Transcrição de Audiências Públicas", expanded=True):
                st.subheader("1.3 • Transcrição de Audiências Públicas")
                st.write("**As audiências públicas são transcritas em atas ou outro documento de registro das demandas/sugestões apresentadas pela participação popular?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opc13 = {"Selecione...": 0.0, "Sim": 0.0, "Não": 0.0}
                d13 = res_data.get("1.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d13 is None: d13 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_13 = d13.get("valor", "Selecione...")
                chave_radio_13 = f"r_1_3_{v_salvo_13}_{ano_sel}"

                def cb_radio_1_3():
                    val = st.session_state[chave_radio_13]
                    lnk = st.session_state.get(f"t_1_3_{ano_sel}", d13.get("link", ""))
                    save_resp("1.3", val, 0.0, lnk)
                    res_data["1.3"] = {"valor": val, "pontos": 0.0, "link": lnk}

                def cb_text_1_3():
                    lnk = st.session_state[f"t_1_3_{ano_sel}"]
                    val = st.session_state.get(chave_radio_13, d13.get("valor", "Selecione..."))
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d13.get("link", "") or "")]
                    
                    mudou_opcao_13 = val != d13.get("valor", "")
                    mudou_link_13 = lnk != d13.get("link", "")
                    
                    if mudou_opcao_13 or mudou_link_13:
                        save_resp("1.3", val, 0.0, lnk)
                        res_data["1.3"] = {"valor": val, "pontos": 0.0, "link": lnk}
                        
                        if mudou_link_13 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_1_3_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = True

                c13_1, c13_2 = st.columns([1, 1])
                with c13_1:
                    lista_opcoes_13 = list(opc13.keys())
                    idx13 = lista_opcoes_13.index(d13["valor"]) if d13.get("valor") in opc13 else 0
                    sel_1_3 = st.radio("Selecione 1.3:", options=lista_opcoes_13, index=idx13, key=chave_radio_13, on_change=cb_radio_1_3, label_visibility="collapsed")
                    
                with c13_2:
                    link_1_3 = st.text_area("Link/Evidência (1.3):", value=d13.get("link", ""), key=f"t_1_3_{ano_sel}", on_change=cb_text_1_3, height=130)
                    placeholder_links_13 = st.empty()
                    links_1_3_visuais = [u[0] for u in re.findall(regex_pure_url, link_1_3 or "")]
                    if links_1_3_visuais:
                        placeholder_links_13.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1_3_visuais]))
                
                txt_score_13 = f"📊 Pontuação Aplicada no Quesito 1.3: 0.0 pontos"
                if sel_1_3 == "Selecione...": txt_score_13 += " (Aguardando seleção)"
                st.code(txt_score_13, language="text")
                bloco_comentarios("1.3", res_data)

        if st.session_state.get(f"gatilho_modal_1_3_{ano_sel}", False):
            modal_aviso_link("1.3", st.session_state.get(f"links_pendentes_1_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 1.3.1 • LINK DO INSTRUMENTO DE REGISTRO (VALIDAÇÃO DUPLA)
        # =============================================================================
        with st.container(key=f"container_bloco_link_registro_1_3_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.3.1 - Página Eletrônica do Instrumento de Registro", expanded=True):
                st.subheader("1.3.1 • Página Eletrônica do Instrumento de Registro")
                st.write("**Página eletrônica (link) do instrumento (Ata ou documento de registro). Digite XYZ se não estiver disponível:**")
                st.caption("ℹ *Avaliamos links tanto no input principal do link URL quanto no campo de evidência adicional.*")
                
                d131 = res_data.get("1.3.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d131 is None: d131 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_input_1_3_1():
                    v131 = st.session_state[f"i_1_3_1_{ano_sel}"]
                    v131_clean = v131.strip().upper() if v131 else ""
                    nota_calculada = 0.0 if (v131_clean == "XYZ" or not v131.strip()) else 3.0
                    lnk = st.session_state.get(f"t_1_3_1_{ano_sel}", d131.get("link", ""))
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, v131 or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d131.get("valor", "") or "")]
                    
                    mudou_opcao_131 = v131 != d131.get("valor", "")
                    mudou_link_131 = lnk != d131.get("link", "")
                    
                    if mudou_opcao_131 or mudou_link_131:
                        save_resp("1.3.1", v131, nota_calculada, lnk)
                        res_data["1.3.1"] = {"valor": v131, "pontos": nota_calculada, "link": lnk}
                        
                        if mudou_opcao_131 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_1_3_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = True

                def cb_link_evidencia_1_3_1():
                    lnk = st.session_state[f"t_1_3_1_{ano_sel}"]
                    v131 = st.session_state.get(f"i_1_3_1_{ano_sel}", d131.get("valor", ""))
                    v131_clean = v131.strip().upper() if v131 else ""
                    nota_calculada = 0.0 if (v131_clean == "XYZ" or not v131.strip()) else 3.0
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d131.get("link", "") or "")]
                    
                    mudou_opcao_131 = v131 != d131.get("valor", "")
                    mudou_link_131 = lnk != d131.get("link", "")
                    
                    if mudou_opcao_131 or mudou_link_131:
                        save_resp("1.3.1", v131, nota_calculada, lnk)
                        res_data["1.3.1"] = {"valor": v131, "pontos": nota_calculada, "link": lnk}
                        
                        if mudou_link_131 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_1_3_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = True

                c131_1, c131_2 = st.columns([1, 1])
                with c131_1:
                    v131 = st.text_input("Link URL:", value=d131.get("valor", ""), key=f"i_1_3_1_{ano_sel}", on_change=cb_input_1_3_1, label_visibility="collapsed")
                    v131_clean = v131.strip().upper() if v131 else ""
                    pts_131 = 0.0 if (v131_clean == "XYZ" or not v131.strip()) else 3.0
                    
                with c131_2:
                    link_evidencia_131 = st.text_area("Link/Evidência Adicional (1.3.1):", value=d131.get("link", ""), key=f"t_1_3_1_{ano_sel}", on_change=cb_link_evidencia_1_3_1, height=70)
                    placeholder_links_131 = st.empty()
                    links_131_visuais = [u[0] for u in re.findall(regex_pure_url, link_evidencia_131) if link_evidencia_131]
                    if links_131_visuais:
                        placeholder_links_131.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_131_visuais]))

                st.code(f"📊 Pontuação Aplicada no Quesito 1.3.1: {pts_131:.1f} / 3.0 pontos", language="text")
                bloco_comentarios("1.3.1", res_data)

        if st.session_state.get(f"gatilho_modal_1_3_1_{ano_sel}", False):
            modal_aviso_link("1.3.1", st.session_state.get(f"links_pendentes_1_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_3_1_{ano_sel}"] = False


        # =============================================================================
        # QUESITO 1.4 • ELEMENTOS DE PLANEJAMENTO DAS AUDIÊNCIAS
        # =============================================================================
        with st.container(key=f"container_bloco_elementos_audiencias_1_4_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.4 - Elementos de Planejamento e Organização", expanded=True):
                st.subheader("1.4 • Elementos de Planejamento e Organização")
                st.write("**Assinale os elementos considerados no processo de planejamento e organização das audiências públicas:**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                elementos = {
                    "Estabelecimento da Pauta – 0,5": 0.5,
                    "Disponibilização prévia de material de apoio a respeito dos temas a serem debatidos – 0,5": 0.5,
                    "Convocação contendo o dia, horário e o local através dos jornais, das rádios, do Portal da Prefeitura e outras plataformas digitais. Ex.: Instagram, Facebook etc. – 0,5 ": 0.5,
                    "Planejamento logístico. Ex.:localização do ambiente, acomodações adequadas aos participantes, regulação e testagem dos equipamentos eletrônicos (som, vídeo e iluminação), verificação dos equipamentos relacionados a transmissão das audiências etc. – 01": 1.0,
                    "Indicação de mediador qualificado – 0,5": 0.5,
                    "Estabelecimento da abordagem de interação – 0,5": 0.5,
                    "Definição de mechanisms de avaliação – 0,5": 0.5,
                    "Elaboração e divulgação do Relatório contendo a análise das demandas e sugestões coletadas – 01": 1.0
                }
                d14 = res_data.get("1.4", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d14 is None: d14 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_14 = ast.literal_eval(d14["valor"])
                    if not isinstance(lista_salva_14, list): lista_salva_14 = []
                except Exception:
                    lista_salva_14 = []

                def cb_mudanca_1_4():
                    novos_sel = []
                    novos_pts = 0.0
                    for e, pt in elementos.items():
                        if st.session_state.get(f"chk_1_4_{e}_{ano_sel}", e in lista_salva_14):
                            novos_sel.append(e)
                            novos_pts += pt
                    lnk = st.session_state.get(f"t_1_4_{ano_sel}", d14.get("link", ""))
                    str_sel = str(novos_sel)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d14.get("link", "") or "")]
                    
                    mudou_opcao_14 = str_sel != d14.get("valor", "")
                    mudou_link_14 = lnk != d14.get("link", "")
                    
                    if mudou_opcao_14 or mudou_link_14:
                        save_resp("1.4", str_sel, novos_pts, lnk)
                        res_data["1.4"] = {"valor": str_sel, "pontos": novos_pts, "link": lnk}
                        
                        if mudou_link_14 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_1_4_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = True

                c14_1, c14_2 = st.columns([1, 1])
                with c14_1:
                    pts14 = 0.0
                    for e, pt in elementos.items():
                        if st.checkbox(e, value=e in lista_salva_14, key=f"chk_1_4_{e}_{ano_sel}", on_change=cb_mudanca_1_4):
                            pts14 += pt
                            
                with c14_2:
                    link_1_4 = st.text_area("Link/Evidência (1.4):", value=d14.get("link", ""), key=f"t_1_4_{ano_sel}", on_change=cb_mudanca_1_4, height=130)
                    placeholder_links_14 = st.empty()
                    links_1_4_visuais = [u[0] for u in re.findall(regex_pure_url, link_1_4 or "")]
                    if links_1_4_visuais:
                        placeholder_links_14.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1_4_visuais]))
                
                st.code(f"📊 Pontuação Aplicada no Quesito 1.4: {pts14:.1f} pontos", language="text")
                bloco_comentarios("1.4", res_data)

        if st.session_state.get(f"gatilho_modal_1_4_{ano_sel}", False):
            modal_aviso_link("1.4", st.session_state.get(f"links_pendentes_1_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = False

        # =============================================================================
        # SEÇÃO 2: CONSULTA PÚBLICA ONLINE
        # =============================================================================
        st.header("2.0 Consulta Pública Online")

        # -----------------------------------------------------------------------------
        # QUESTÃO 2.0 - REALIZAÇÃO DA CONSULTA (PADRÃO REFINADO EXATAMENTE IGUAL AO 1.0)
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_i_plan_2_0_{ano_sel}", border=True):
                with st.expander(f"📌 Questão 2.0 • Consulta Pública Online ({ano_sel})", expanded=True):
                        st.subheader("2.0 • Consulta Pública (I-PLAN)")
                        st.write("**Houve a realização de consulta pública online para coleta de sugestões para a elaboração do PPA 2026-2029?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes20 = {"Selecione...": 0.0, "Sim": 6.0, "Não": 0.0}
                        d20 = res_data.get("2.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d20 is None: d20 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        
                        val_salvo_20 = d20.get("valor", "Selecione...")
                        if "Sim" in str(val_salvo_20): val_salvo_20 = "Sim"
                        elif "Não" in str(val_salvo_20): val_salvo_20 = "Não"
                        if val_salvo_20 not in opcoes20: val_salvo_20 = "Selecione..."

                        chave_radio_20 = f"r_2_0_{val_salvo_20}_{ano_sel}"

                        regex_pure_url = r'(https?://[^\s<>"]+?)(?=[.,;:]?(\s|$))'

                        def cb_radio_20():
                                val = st.session_state[chave_radio_20]
                                pts = opcoes20[val]
                                lnk = st.session_state.get(f"txt_i_plan_20_{ano_sel}", d20.get("link", ""))
                                save_resp("2.0", val, pts, lnk)
                                res_data["2.0"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_20():
                                lnk = st.session_state[f"txt_i_plan_20_{ano_sel}"]
                                val = st.session_state.get(chave_radio_20, d20.get("valor", "Selecione..."))
                                pts = opcoes20.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d20.get("link", "") or "")]
                                
                                mudou_opcao_20 = val != d20.get("valor", "")
                                mudou_link_20 = lnk != d20.get("link", "")
                                
                                if mudou_opcao_20 or mudou_link_20:
                                        save_resp("2.0", val, pts, lnk)
                                        res_data["2.0"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_20 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_2_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                        col1, col2 = st.columns([1, 1])
                        with col1:
                                lista_opcoes_20 = list(opcoes20.keys())
                                idx20 = lista_opcoes_20.index(val_salvo_20)
                                r20 = st.radio("Selecione 2.0:", options=lista_opcoes_20, index=idx20, key=chave_radio_20, on_change=cb_radio_20, label_visibility="collapsed")
                                pts_20 = opcoes20[r20]
                                
                        with col2:
                                l20 = st.text_area("Link/Evidência (2.0):", value=d20.get("link", ""), key=f"txt_i_plan_20_{ano_sel}", on_change=cb_text_20, height=130)
                                placeholder_links_20 = st.empty()
                                links_2_0_visuais = [u[0] for u in re.findall(regex_pure_url, l20 or "")]
                                if links_2_0_visuais:
                                        placeholder_links_20.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_2_0_visuais]))
                                
                        txt_score_20 = f"📊 Pontuação Aplicada na Questão 2.0: {pts_20:.1f} / 6.0 pontos"
                        if r20 == "Selecione...": txt_score_20 = "⚠️ Status: Aguardando preenchimento"
                        st.code(txt_score_20, language="text")
                        bloco_comentarios("2.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
                modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = False

# =============================================================================
        # QUESITO 2.1 • GLOSSÁRIO NA CONSULTA PÚBLICA DO PPA
        # =============================================================================
        with st.container(key=f"container_bloco_glossario_ppa_2_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 2.1 - Glossário Explicativo na Consulta Pública do PPA", expanded=True):
                        st.subheader("2.1 • Glossário e Linguagem Cidadã")
                        st.write("**Na consulta pública online de elaboração do Plano Plurianual (PPA) foi disponibilizado glossário explicando os objetivos, como contribuir, em linguagem clara e simples?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        # Mapeamento oficial de opções e pontuações do quesito 2.1
                        opcoes_21 = {
                                "Selecione...": 0.0,
                                "Sim – 02": 2.0,
                                "Não – 00": 0.0
                        }
                        
                        # Recupera o estado salvo usando a chave padronizada "2.1"
                        d21 = res_data.get("2.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d21 is None: d21 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        
                        v_salvo_21 = d21.get("valor", "Selecione...")
                        chave_radio_21 = f"r_21_{v_salvo_21}_{ano_sel}"

                        def cb_radio_21():
                                val = st.session_state[chave_radio_21]
                                pts = opcoes_21.get(val, 0.0)
                                lnk = st.session_state.get(f"l_21_txt_{ano_sel}", d21.get("link", ""))
                                
                                save_resp("2.1", val, pts, lnk)
                                res_data["2.1"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_21():
                                lnk = st.session_state[f"l_21_txt_{ano_sel}"]
                                val = st.session_state.get(chave_radio_21, v_salvo_21)
                                pts = opcoes_21.get(val, 0.0)
                                
                                save_resp("2.1", val, pts, lnk)
                                res_data["2.1"] = {"valor": val, "pontos": pts, "link": lnk}
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d21.get("link", "") or "")]
                                
                                if lnk != d21.get("link", "") and links_atuais:
                                        if links_atuais != links_antigos:
                                                st.session_state[f"links_pendentes_21_{ano_sel}"] = links_atuais
                                                st.session_state[f"gatilho_modal_21_{ano_sel}"] = True

                        c_21_1, c_21_2 = st.columns([1, 1])
                        with c_21_1:
                                lista_opcoes_21 = list(opcoes_21.keys())
                                idx_21 = lista_opcoes_21.index(v_salvo_21) if v_salvo_21 in lista_opcoes_21 else 0
                                
                                r21 = st.radio(
                                        "Disponibilizou glossário explicativo:",
                                        options=lista_opcoes_21,
                                        index=idx_21,
                                        key=chave_radio_21,
                                        on_change=cb_radio_21,
                                        label_visibility="collapsed"
                                )
                                pts_21 = opcoes_21[r21]
                                
                        with c_21_2:
                                # CORRIGIDO: Fechamento do text_area adicionado corretamente (height mudado para 130 para se alinhar ao 2.0)
                                l21 = st.text_area("Link de Evidência / Página da Consulta (2.1):", value=d21.get("link", ""), key=f"l_21_txt_{ano_sel}", on_change=cb_text_21, height=130)
                                placeholder_links_21 = st.empty()
                                links_2_1_visuais = [u[0] for u in re.findall(regex_pure_url, l21 or "")]
                                if links_2_1_visuais:
                                        placeholder_links_21.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_2_1_visuais]))

                        # Adicionado para manter a padronização visual da sua aplicação:
                        txt_score_21 = f"📊 Pontuação Aplicada no Quesito 2.1: {pts_21:.1f} / 2.0 pontos"
                        if r21 == "Selecione...": txt_score_21 = "⚠️ Status: Aguardando preenchimento"
                        st.code(txt_score_21, language="text")
                        bloco_comentarios("2.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_21_{ano_sel}", False):
                modal_aviso_link("2.1", st.session_state.get(f"links_pendentes_21_{ano_sel}", []))
                st.session_state[f"gatilho_modal_21_{ano_sel}"] = False

        # =============================================================================
        # SEÇÃO 3: DIAGNÓSTICO
        # =============================================================================
        st.header("3.0 Diagnóstico Prévio")

        # -----------------------------------------------------------------------------
        # QUESITO 3.0 • TOTALMENTE INDEPENDENTE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_diagnostico_3_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 3.0 - Diagnóstico Prévio ao Planejamento", expanded=True):
                        st.subheader("3.0 • Diagnóstico Prévio")
                        st.write("**Além das audiências públicas, a Prefeitura realizou diagnóstico anteriormente ao planejamento, através do levantamento formal de seus problemas, necessidades e deficiências?**")
                        st.caption("⚠️ **Obs:** *Os Planos Municipais Setoriais (Educação, Saúde, Saneamento Básico etc.) somente podem ser considerados se neles houver evidências do levantamento formal dos problemas.*")
                        
                        opcoes_30 = {"Selecione...": 0.0, "Sim": 0.0, "Não": 0.0}
                        d30 = res_data.get("3.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d30 is None: d30 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_30 = d30.get("valor", "Selecione...")
                        chave_radio_30 = f"r_3_0_{v_salvo_30}_{ano_sel}"

                        def cb_radio_3_0():
                                val = st.session_state[chave_radio_30]
                                lnk = st.session_state.get(f"t_3_0_{ano_sel}", d30.get("link", ""))
                                save_resp("3.0", val, 0.0, lnk)
                                res_data["3.0"] = {"valor": val, "pontos": 0.0, "link": lnk}

                        def cb_text_3_0():
                                lnk = st.session_state[f"t_3_0_{ano_sel}"]
                                val = st.session_state.get(chave_radio_30, d30.get("valor", "Selecione..."))
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d30.get("link", "") or "")]
                                
                                mudou_opcao_30 = val != d30.get("valor", "")
                                mudou_link_30 = lnk != d30.get("link", "")
                                
                                if mudou_opcao_30 or mudou_link_30:
                                        save_resp("3.0", val, 0.0, lnk)
                                        res_data["3.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                        
                                        if mudou_link_30 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_3_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                        c30_1, c30_2 = st.columns([1, 1])
                        with c30_1:
                                lista_opcoes_30 = list(opcoes_30.keys())
                                idx30 = lista_opcoes_30.index(v_salvo_30) if v_salvo_30 in opcoes_30 else 0
                                sel_3_0 = st.radio("Selecione 3.0:", options=lista_opcoes_30, index=idx30, key=chave_radio_30, on_change=cb_radio_3_0, label_visibility="collapsed")
                                
                        with c30_2:
                                link_3_0 = st.text_area("Link/Evidência (3.0):", value=d30.get("link", ""), key=f"t_3_0_{ano_sel}", on_change=cb_text_3_0, height=130)
                                placeholder_links_30 = st.empty()
                                links_3_0_visuais = [u[0] for u in re.findall(regex_pure_url, link_3_0 or "")]
                                if links_3_0_visuais:
                                        placeholder_links_30.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_3_0_visuais]))
                        
                        txt_score_30 = f"📊 Pontuação Aplicada no Quesito 3.0: 0.0 pontos"
                        if sel_3_0 == "Selecione...": txt_score_30 += " (Aguardando seleção)"
                        st.code(txt_score_30, language="text")
                        bloco_comentarios("3.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
                modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = False


        # -----------------------------------------------------------------------------
        # QUESITO 3.1 • TOTALMENTE INDEPENDENTE
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_abordagem_diagnostico_3_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 3.1 - Alinhamento com Planos Federais/Estaduais", expanded=True):
                        st.subheader("3.1 • Alinhamento com Planos Federais/Estaduais")
                        st.write("**3.1 A abordagem do diagnóstico levou em conta algum plano do governo federal e/ou estadual?**")
                        
                        opcoes_31 = {"Selecione...": 0.0, "Sim – 14": 14.0, "Não – 00": 0.0}
                        d31 = res_data.get("3.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d31 is None: d31 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_31 = d31.get("valor", "Selecione...")
                        if "Sim" in str(v_salvo_31): v_salvo_31 = "Sim – 14"
                        elif "Não" in str(v_salvo_31): v_salvo_31 = "Não – 00"
                        if v_salvo_31 not in opcoes_31: v_salvo_31 = "Selecione..."

                        chave_radio_31 = f"r_3_1_{v_salvo_31}_{ano_sel}"

                        def cb_radio_3_1():
                                val = st.session_state[chave_radio_31]
                                pts = opcoes_31[val]
                                lnk = st.session_state.get(f"t_3_1_{ano_sel}", d31.get("link", ""))
                                save_resp("3.1", val, pts, lnk)
                                res_data["3.1"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_3_1():
                                lnk = st.session_state[f"t_3_1_{ano_sel}"]
                                val = st.session_state.get(chave_radio_31, d31.get("valor", "Selecione..."))
                                pts = opcoes_31.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d31.get("link", "") or "")]
                                
                                mudou_opcao_31 = val != d31.get("valor", "")
                                mudou_link_31 = lnk != d31.get("link", "")
                                
                                if mudou_opcao_31 or mudou_link_31:
                                        save_resp("3.1", val, pts, lnk)
                                        res_data["3.1"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_31 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_3_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                        c31_1, c31_2 = st.columns([1, 1])
                        with c31_1:
                                lista_opcoes_31 = list(opcoes_31.keys())
                                idx31 = lista_opcoes_31.index(v_salvo_31)
                                sel_3_1 = st.radio("Selecione 3.1:", options=lista_opcoes_31, index=idx31, key=chave_radio_31, on_change=cb_radio_3_1, label_visibility="collapsed")
                                pts_3_1 = opcoes_31[sel_3_1]
                                
                        with c31_2:
                                link_3_1 = st.text_area("Link/Evidência (3.1):", value=d31.get("link", ""), key=f"t_3_1_{ano_sel}", on_change=cb_text_3_1, height=130)
                                placeholder_links_31 = st.empty()
                                links_3_1_visuais = [u[0] for u in re.findall(regex_pure_url, link_3_1 or "")]
                                if links_3_1_visuais:
                                        placeholder_links_31.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_3_1_visuais]))
                        
                        txt_score_31 = f"📊 Pontuação Aplicada no Quesito 3.1: {pts_3_1:.1f} pontos"
                        if sel_3_1 == "Selecione...": txt_score_31 += " (Aguardando seleção)"
                        st.code(txt_score_31, language="text")
                        bloco_comentarios("3.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
                modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = False

        # -----------------------------------------------------------------------------
        # LEITURA PRÉVIA DO QUESITO 3.1 (Necessário para não dar NameError)
        # -----------------------------------------------------------------------------
        d31 = res_data.get("3.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
        if d31 is None: d31 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
        
        # Recupera o valor que está atualmente no session_state ou o que veio do banco/JSON
        val_salvo_31 = d31.get("valor", "Selecione...")
        chave_radio_31 = f"r_3_1_{val_salvo_31}_{ano_sel}"
        
        # Define r31 com base no estado atual para evitar o NameError
        r31 = st.session_state.get(chave_radio_31, val_salvo_31)

        # -----------------------------------------------------------------------------
        # QUESITO 3.1.1 • DESCRIÇÃO DOS PROGRAMAS UTILIZADOS
        # -----------------------------------------------------------------------------
        if r31 and "Sim" in r31:
            with st.container(key=f"container_bloco_i_plan_3_1_1_{ano_sel}", border=True):
                with st.expander(f"📝 Quesito 3.1.1 • Descrição dos Programas Utilizados ({ano_sel})", expanded=True):
                    st.subheader("3.1.1 • Detalhamento dos Programas")
                    st.write("**Descreva os programas utilizados:**")
                    st.caption("ℹ *Salvamento automático por callbacks nativos de estado.*")
                    
                    d311 = res_data.get("3.1.1", {"valor": "", "pontos": 0.0, "link": ""})
                    if d311 is None: d311 = {"valor": "", "pontos": 0.0, "link": ""}
                    
                    def cb_text_311():
                        val = st.session_state[f"q311_txt_{ano_sel}"]
                        save_resp("3.1.1", val, 0.0, "")
                        res_data["3.1.1"] = {"valor": val, "pontos": 0.0, "link": ""}

                    v311 = st.text_area(
                        "Descrição dos programas:", 
                        value=d311.get("valor", ""), 
                        key=f"q311_txt_{ano_sel}", 
                        on_change=cb_text_311, 
                        height=100,
                        label_visibility="collapsed"
                    )
                    bloco_comentarios("3.1.1", res_data, ano_sel)

        # -----------------------------------------------------------------------------
        # QUESITO 3.2 • DIAGNÓSTICO PRÉVIO DOS PROGRAMAS DO PPA
        # -----------------------------------------------------------------------------
        with st.container(key=f"container_bloco_i_plan_3_2_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 3.2 • Diagnóstico Prévio do PPA ({ano_sel})", expanded=True):
                st.subheader("3.2 • Diagnóstico Prévio")
                st.write("**Os programas do PPA 2026-2029 tiveram diagnóstico prévio?**")
                st.caption("ℹ *Obs: Os Planos Municipais Setoriais (Educação, Saúde, Saneamento Básico etc.) somente podem ser considerados se neles houver evidências do levantamento formal dos problemas.*")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opc32 = {
                    "Selecione...": 0.0,
                    "Sim, para todos os programas PPA – 10": 10.0, 
                    "Sim, para a maior parte dos programas do PPA – 05": 5.0, 
                    "Sim, para a menor parte dos programas do PPA  – 03": 3.0, 
                    "Não – 00": 0.0
                }
                
                d32 = res_data.get("3.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d32 is None: d32 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                val_salvo_32 = d32.get("valor", "Selecione...")
                if val_salvo_32 not in opc32: val_salvo_32 = "Selecione..."
                
                chave_radio_32 = f"r_3_2_{val_salvo_32}_{ano_sel}"
                regex_pure_url = r'(https?://[^\s<>"]+?)(?=[.,;:]?(\s|$))'

                def cb_radio_32():
                    val = st.session_state[chave_radio_32]
                    pts = opc32[val]
                    lnk = st.session_state.get(f"txt_i_plan_32_{ano_sel}", d32.get("link", ""))
                    save_resp("3.2", val, pts, lnk)
                    res_data["3.2"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_32():
                    lnk = st.session_state[f"txt_i_plan_32_{ano_sel}"]
                    val = st.session_state.get(chave_radio_32, d32.get("valor", "Selecione..."))
                    pts = opc32.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d32.get("link", "") or "")]
                    
                    mudou_opcao_32 = val != d32.get("valor", "")
                    mudou_link_32 = lnk != d32.get("link", "")
                    
                    if mudou_opcao_32 or mudou_link_32:
                        save_resp("3.2", val, pts, lnk)
                        res_data["3.2"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if mudou_link_32 and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_3_2_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    lista_opcoes_32 = list(opc32.keys())
                    idx32 = lista_opcoes_32.index(val_salvo_32)
                    r32 = st.radio("Selecione 3.2:", options=lista_opcoes_32, index=idx32, key=chave_radio_32, on_change=cb_radio_32, label_visibility="collapsed")
                    pts_32 = opc32[r32]
                    
                with col2:
                    l32 = st.text_area("Link/Evidência (3.2):", value=d32.get("link", ""), key=f"txt_i_plan_32_{ano_sel}", on_change=cb_text_32, height=140)
                    placeholder_links_32 = st.empty()
                    links_3_2_visuais = [u[0] for u in re.findall(regex_pure_url, l32 or "")]
                    if links_3_2_visuais:
                        placeholder_links_32.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_3_2_visuais]))
                        
                txt_score_32 = f"📊 Pontuação Aplicada na Questão 3.2: {pts_32:.1f} / 10.0 pontos"
                if r32 == "Selecione...": txt_score_32 = "⚠️ Status: Aguardando preenchimento"
                st.code(txt_score_32, language="text")
                bloco_comentarios("3.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_3_2_{ano_sel}", False):
            modal_aviso_link("3.2", st.session_state.get(f"links_pendentes_3_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_2_{ano_sel}"] = False

        # =============================================================================
        # SEÇÃO 4: METAS E INDICADORES
        # =============================================================================
        st.header("4.0 Metas e Indicadores")

        # --- QUESITO 4.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_metas_indicadores_4_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.0 - Metas Físicas e Financeiras no PPA", expanded=True):
                        st.subheader("4.0 • Metas e Indicadores")
                        st.write("**Há o estabelecimento de metas físicas e financeiras de forma anual nas ações previstas no PPA?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_40 = {
                                "Selecione...": 0.0, 
                                "Sim, com metas físicas e financeiras – 10": 10.0, 
                                "Sim, apenas financeiras – 05": 5.0, 
                                "Sim, apenas físicas – 05": 5.0, 
                                "Não houve o estabelecimento de metas anuais – 00": 0.0
                        }
                        
                        d40 = res_data.get("4.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d40 is None: d40 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_40 = d40.get("valor", "Selecione...")
                        chave_radio_40 = f"r_4_0_{v_salvo_40}_{ano_sel}"

                        regex_pure_url = r'(https?://[^\s<>"]+?)(?=[.,;:]?(\s|$))'

                        def cb_radio_4_0():
                                val = st.session_state[chave_radio_40]
                                pts = opcoes_40[val]
                                lnk = st.session_state.get(f"t_4_0_{ano_sel}", d40.get("link", ""))
                                save_resp("4.0", val, pts, lnk)
                                res_data["4.0"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_4_0():
                                lnk = st.session_state[f"t_4_0_{ano_sel}"]
                                val = st.session_state.get(chave_radio_40, d40.get("valor", "Selecione..."))
                                pts = opcoes_40.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d40.get("link", "") or "")]
                                
                                mudou_opcao_40 = val != d40.get("valor", "")
                                mudou_link_40 = lnk != d40.get("link", "")
                                
                                if mudou_opcao_40 or mudou_link_40:
                                        save_resp("4.0", val, pts, lnk)
                                        res_data["4.0"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_40 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_4_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                        c40_1, c40_2 = st.columns([1, 1])
                        with c40_1:
                                lista_opcoes_40 = list(opcoes_40.keys())
                                idx40 = 0
                                if d40.get("valor") in opcoes_40:
                                        idx40 = lista_opcoes_40.index(d40["valor"])
                                elif d40.get("valor"):
                                        if "metas físicas e financeiras" in d40["valor"]: idx40 = lista_opcoes_40.index("Sim, com metas físicas e financeiras – 10")
                                        elif "apenas financeiras" in d40["valor"]: idx40 = lista_opcoes_40.index("Sim, apenas financeiras – 05")
                                        elif "apenas físicas" in d40["valor"]: idx40 = lista_opcoes_40.index("Sim, apenas físicas – 05")
                                        elif "Não houve" in d40["valor"]: idx40 = lista_opcoes_40.index("Não houve o estabelecimento de metas anuais – 00")
                                        
                                sel_4_0 = st.radio("Selecione 4.0:", options=lista_opcoes_40, index=idx40, key=chave_radio_40, on_change=cb_radio_4_0, label_visibility="collapsed")
                                pts_4_0 = opcoes_40[sel_4_0]
                                
                        with c40_2:
                                link_4_0 = st.text_area("Link/Evidência (4.0):", value=d40.get("link", ""), key=f"t_4_0_{ano_sel}", on_change=cb_text_4_0, height=130)
                                placeholder_links_40 = st.empty()
                                links_40_visuais = [u[0] for u in re.findall(regex_pure_url, link_4_0 or "")]
                                if links_40_visuais:
                                        placeholder_links_40.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_40_visuais]))
                                
                        txt_score_40 = f"📊 Pontuação Aplicada no Quesito 4.0: {pts_4_0:.1f} pontos"
                        if sel_4_0 == "Selecione...": txt_score_40 += " (Aguardando seleção)"
                        st.code(txt_score_40, language="text")
                        bloco_comentarios("4.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
                modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = False


        # --- QUESITO 4.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_articulacao_programas_4_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.1 - Articulação de Programas Finalísticos", expanded=True):
                        st.subheader("4.1 • Articulação de Programas Finalísticos")
                        st.write("**4.1 Os programas finalísticos articulam um conjunto de ações que concorrem para um objective comum preestabelecido, visando à solução de um problema ou necessidade da sociedade?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_41 = {
                                "Selecione...": 0.0, 
                                "Todos os programas finalísticos – 15": 15.0, 
                                "A maior parte dos programas finalísticos – 10": 10.0, 
                                "A menor parte dos programas finalísticos – 05": 5.0, 
                                "Nenhum programa finalístico – 00": 0.0
                        }
                        
                        d41 = res_data.get("4.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d41 is None: d41 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_41 = d41.get("valor", "Selecione...")
                        chave_radio_41 = f"r_4_1_{v_salvo_41}_{ano_sel}"

                        def cb_radio_4_1():
                                val = st.session_state[chave_radio_41]
                                pts = opcoes_41[val]
                                lnk = st.session_state.get(f"t_4_1_{ano_sel}", d41.get("link", ""))
                                save_resp("4.1", val, pts, lnk)
                                res_data["4.1"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_4_1():
                                lnk = st.session_state[f"t_4_1_{ano_sel}"]
                                val = st.session_state.get(chave_radio_41, d41.get("valor", "Selecione..."))
                                pts = opcoes_41.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d41.get("link", "") or "")]
                                
                                mudou_opcao_41 = val != d41.get("valor", "")
                                mudou_link_41 = lnk != d41.get("link", "")
                                
                                if mudou_opcao_41 or mudou_link_41:
                                        save_resp("4.1", val, pts, lnk)
                                        res_data["4.1"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_41 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_4_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = True

                        c41_1, c41_2 = st.columns([1, 1])
                        with c41_1:
                                lista_opcoes_41 = list(opcoes_41.keys())
                                idx41 = 0
                                if d41.get("valor") in opcoes_41:
                                        idx41 = lista_opcoes_41.index(d41["valor"])
                                elif d41.get("valor"):
                                        if "Todos os" in d41["valor"]: idx41 = lista_opcoes_41.index("Todos os programas finalísticos – 15")
                                        elif "maior parte" in d41["valor"]: idx41 = lista_opcoes_41.index("A maior parte dos programas finalísticos – 10")
                                        elif "menor parte" in d41["valor"]: idx41 = lista_opcoes_41.index("A menor parte dos programas finalísticos – 05")
                                        elif "Nenhum" in d41["valor"]: idx41 = lista_opcoes_41.index("Nenhum programa finalístico – 00")
                                        
                                sel_4_1 = st.radio("Selecione 4.1:", options=lista_opcoes_41, index=idx41, key=chave_radio_41, on_change=cb_radio_4_1, label_visibility="collapsed")
                                pts_4_1 = opcoes_41[sel_4_1]
                                
                        with c41_2:
                                link_4_1 = st.text_area("Link/Evidência (4.1):", value=d41.get("link", ""), key=f"t_4_1_{ano_sel}", on_change=cb_text_4_1, height=130)
                                placeholder_links_41 = st.empty()
                                links_41_visuais = [u[0] for u in re.findall(regex_pure_url, link_4_1 or "")]
                                if links_41_visuais:
                                        placeholder_links_41.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_41_visuais]))
                                
                        txt_score_41 = f"📊 Pontuação Aplicada no Quesito 4.1: {pts_4_1:.1f} pontos"
                        if sel_4_1 == "Selecione...": txt_score_41 += " (Aguardando seleção)"
                        st.code(txt_score_41, language="text")
                        bloco_comentarios("4.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_1_{ano_sel}", False):
                modal_aviso_link("4.1", st.session_state.get(f"links_pendentes_4_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = False


        # --- QUESITO 4.1.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_avaliacao_programas_4_1_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.1.1 - Avaliação da Implementação dos Programas Finalísticos", expanded=True):
                        st.subheader("4.1.1 • Avaliação de Programas Finalísticos")
                        st.write("**4.1.1 Houve avaliação da implementação dos programas finalísticos em relação a seus indicadores, objetivos e metas?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_411 = {
                                "Selecione...": 0.0, 
                                "Sim, para todos os programas finalísticos monitorados – 10": 10.0, 
                                "Sim, para a maior parte dos programas finalísticos monitorados – 07": 7.0, 
                                "Sim, para a menor parte dos programas finalísticos monitorados – 03": 3.0, 
                                "Não houve avaliação – 00": 0.0
                        }
                        
                        d411 = res_data.get("4.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d411 is None: d411 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_411 = d411.get("valor", "Selecione...")
                        chave_radio_411 = f"r_4_1_1_{v_salvo_411}_{ano_sel}"

                        def cb_radio_4_1_1():
                                val = st.session_state[chave_radio_411]
                                pts = opcoes_411[val]
                                lnk = st.session_state.get(f"t_4_1_1_{ano_sel}", d411.get("link", ""))
                                save_resp("4.1.1", val, pts, lnk)
                                res_data["4.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_4_1_1():
                                lnk = st.session_state[f"t_4_1_1_{ano_sel}"]
                                val = st.session_state.get(chave_radio_411, d411.get("valor", "Selecione..."))
                                pts = opcoes_411.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d411.get("link", "") or "")]
                                
                                mudou_opcao_411 = val != d411.get("valor", "")
                                mudou_link_411 = lnk != d411.get("link", "")
                                
                                if mudou_opcao_411 or mudou_link_411:
                                        save_resp("4.1.1", val, pts, lnk)
                                        res_data["4.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_411 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_4_1_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_4_1_1_{ano_sel}"] = True

                        c411_1, c411_2 = st.columns([1, 1])
                        with c411_1:
                                lista_opcoes_411 = list(opcoes_411.keys())
                                idx411 = 0
                                if d411.get("valor") in opcoes_411:
                                        idx411 = lista_opcoes_411.index(d411["valor"])
                                elif d411.get("valor"):
                                        if "todos os programas" in d411["valor"]: idx411 = lista_opcoes_411.index("Sim, para todos os programas finalísticos monitorados – 10")
                                        elif "maior parte" in d411["valor"]: idx411 = lista_opcoes_411.index("Sim, para a maior parte dos programas finalísticos monitorados – 07")
                                        elif "menor parte" in d411["valor"]: idx411 = lista_opcoes_411.index("Sim, para a menor parte dos programas finalísticos monitorados – 03")
                                        elif "Não houve" in d411["valor"]: idx411 = lista_opcoes_411.index("Não houve avaliação – 00")
                                        
                                sel_4_1_1 = st.radio("Selecione 4.1.1:", options=lista_opcoes_411, index=idx411, key=chave_radio_411, on_change=cb_radio_4_1_1, label_visibility="collapsed")
                                pts_4_1_1 = opcoes_411[sel_4_1_1]
                                
                        with c411_2:
                                link_4_1_1 = st.text_area("Link/Evidência (4.1.1):", value=d411.get("link", ""), key=f"t_4_1_1_{ano_sel}", on_change=cb_text_4_1_1, height=130)
                                placeholder_links_411 = st.empty()
                                links_411_visuais = [u[0] for u in re.findall(regex_pure_url, link_4_1_1 or "")]
                                if links_411_visuais:
                                        placeholder_links_411.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_411_visuais]))
                                
                        txt_score_411 = f"📊 Pontuação Aplicada no Quesito 4.1.1: {pts_4_1_1:.1f} pontos"
                        if sel_4_1_1 == "Selecione...": txt_score_411 += " (Aguardando seleção)"
                        st.code(txt_score_411, language="text")
                        bloco_comentarios("4.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_1_1_{ano_sel}", False):
                modal_aviso_link("4.1.1", st.session_state.get(f"links_pendentes_4_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_1_1_{ano_sel}"] = False

       # --- QUESITO 4.1.1.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_relatorio_avaliacao_4_1_1_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.1.1.1 - Relatório Anual de Avaliação do PPA", expanded=True):
                        st.subheader("4.1.1.1 • Relatório Anual de Avaliação")
                        st.write("**4.1.1.1 Houve a elaboração de Relatório Anual de Avaliação dos programas finalísticos do PPA?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_4111 = {
                                "Selecione...": 0.0, 
                                "Sim, para todos os programas finalísticos do PPA – 07": 7.0, 
                                "Sim, para a maior parte dos programas finalísticos do PPA – 04": 4.0, 
                                "Sim, para a menor parte dos programas finalísticos do PPA – 01": 1.0, 
                                "Não houve execução do Relatório Anual de Avaliação do PPA – 00": 0.0
                        }
                        
                        d4111 = res_data.get("4.1.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d4111 is None: d4111 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_4111 = d4111.get("valor", "Selecione...")
                        chave_radio_4111 = f"r_4_1_1_1_{v_salvo_4111}_{ano_sel}"

                        def cb_radio_4_1_1_1():
                                val = st.session_state[chave_radio_4111]
                                pts = opcoes_4111[val]
                                lnk = st.session_state.get(f"t_4_1_1_1_{ano_sel}", d4111.get("link", ""))
                                save_resp("4.1.1.1", val, pts, lnk)
                                res_data["4.1.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_4_1_1_1():
                                lnk = st.session_state[f"t_4_1_1_1_{ano_sel}"]
                                val = st.session_state.get(chave_radio_4111, d4111.get("valor", "Selecione..."))
                                pts = opcoes_4111.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d4111.get("link", "") or "")]
                                
                                mudou_opcao_4111 = val != d4111.get("valor", "")
                                mudou_link_4111 = lnk != d4111.get("link", "")
                                
                                if mudou_opcao_4111 or mudou_link_4111:
                                        save_resp("4.1.1.1", val, pts, lnk)
                                        res_data["4.1.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_4111 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_4_1_1_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_4_1_1_1_{ano_sel}"] = True

                        c4111_1, c4111_2 = st.columns([1, 1])
                        with c4111_1:
                                lista_opcoes_4111 = list(opcoes_4111.keys())
                                idx4111 = 0
                                if d4111.get("valor") in opcoes_4111:
                                        idx4111 = lista_opcoes_4111.index(d4111["valor"])
                                elif d4111.get("valor"):
                                        if "todos os programas" in d4111["valor"]: idx4111 = lista_opcoes_4111.index("Sim, para todos os programas finalísticos do PPA – 07")
                                        elif "maior parte" in d4111["valor"]: idx4111 = lista_opcoes_4111.index("Sim, para a maior parte dos programas finalísticos do PPA – 04")
                                        elif "menor parte" in d4111["valor"]: idx4111 = lista_opcoes_4111.index("Sim, para a menor parte dos programas finalísticos do PPA – 01")
                                        elif "Não houve" in d4111["valor"]: idx4111 = lista_opcoes_4111.index("Não houve execução do Relatório Anual de Avaliação do PPA – 00")
                                        
                                sel_4_1_1_1 = st.radio("Selecione 4.1.1.1:", options=lista_opcoes_4111, index=idx4111, key=chave_radio_4111, on_change=cb_radio_4_1_1_1, label_visibility="collapsed")
                                pts_4_1_1_1 = opcoes_4111[sel_4_1_1_1]
                                
                        with c4111_2:
                                link_4_1_1_1 = st.text_area("Link/Evidência (4.1.1.1):", value=d4111.get("link", ""), key=f"t_4_1_1_1_{ano_sel}", on_change=cb_text_4_1_1_1, height=130)
                                placeholder_links_4111 = st.empty()
                                links_4111_visuais = [u[0] for u in re.findall(regex_pure_url, link_4_1_1_1 or "")]
                                if links_4111_visuais:
                                        placeholder_links_4111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_4111_visuais]))
                        
                        txt_score_4111 = f"📊 Pontuação Aplicada no Quesito 4.1.1.1: {pts_4_1_1_1:.1f} pontos"
                        if sel_4_1_1_1 == "Selecione...": txt_score_4111 += " (Aguardando selection)"
                        st.code(txt_score_4111, language="text")
                        bloco_comentarios("4.1.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_1_1_1_{ano_sel}", False):
                modal_aviso_link("4.1.1.1", st.session_state.get(f"links_pendentes_4_1_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_1_1_1_{ano_sel}"] = False


        # --- QUESITO 4.1.1.1.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_aspectos_ppa_4_1_1_1_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.1.1.1.1 - Aspectos Analisados na Avaliação do PPA", expanded=True):
                        st.subheader("4.1.1.1.1 • Aspectos Analisados no Acompanhamento")
                        st.write("**4.1.1.1.1 Assinale os aspectos analisados no processo de acompanhamento e avaliação do PPA:**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        aspectos_41111 = {
                                "Percepção de coerência, em todos os programas, do necessário encadeamento lógicocausal entre os insumos que mobiliza, os produtos/ações que gera, os resultados que provoca e os impactos esperados pela sociedade – 20": 20, 
                                "Análise quanto a se Programas, Metas e Ações são mensurados por um ou mais indicadores próprios e adequados, e que permitam aferir a situação atual (aquela que se pretende modificar) e os avanços obtidos ao longo da execução do programa (em direção àquela mudança pretendida) – 20": 20, 
                                "Avaliação entre os produtos ofertados à população e as reais demandas da sociedade, coletadas, principalmente, nas audiências públicas realizadas e nos demais instrumentos de diagnóstico dos problemas, necessidades e deficiências do município– 20": 20, 
                                "Outros – 00": 0
                        }
                        
                        d41111 = res_data.get("4.1.1.1.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d41111 is None: d41111 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_41111 = ast.literal_eval(d41111.get("valor", "[]"))
                                if not isinstance(lista_salva_41111, list): lista_salva_41111 = []
                        except Exception:
                                lista_salva_41111 = []

                        def cb_check_4_1_1_1_1():
                                sel = []
                                pts = 0
                                for idx, (asp, pt) in enumerate(aspectos_41111.items()):
                                        key_chk = f"chk_41111_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(asp)
                                                pts += pt
                                lnk = st.session_state.get(f"t_4_1_1_1_1_{ano_sel}", d41111.get("link", ""))
                                save_resp("4.1.1.1.1", str(sel), float(pts), lnk)
                                res_data["4.1.1.1.1"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}

                        def cb_text_4_1_1_1_1():
                                lnk = st.session_state[f"t_4_1_1_1_1_{ano_sel}"]
                                sel = []
                                pts = 0
                                for idx, (asp, pt) in enumerate(aspectos_41111.items()):
                                        key_chk = f"chk_41111_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(asp)
                                                pts += pt
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d41111.get("link", "") or "")]
                                
                                mudou_opcao_41111 = str(sel) != d41111.get("valor", "[]")
                                mudou_link_41111 = lnk != d41111.get("link", "")
                                
                                if mudou_opcao_41111 or mudou_link_41111:
                                        save_resp("4.1.1.1.1", str(sel), float(pts), lnk)
                                        res_data["4.1.1.1.1"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_41111 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_4_1_1_1_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_4_1_1_1_1_{ano_sel}"] = True

                        c41111_1, c41111_2 = st.columns([1, 1])
                        with c41111_1:
                                pts_calculados_41111 = 0.0
                                for idx, (asp, pt) in enumerate(aspectos_41111.items()):
                                        isChecked = st.checkbox(
                                                asp, 
                                                value=asp in lista_salva_41111, 
                                                key=f"chk_41111_{idx}_{ano_sel}",
                                                on_change=cb_check_4_1_1_1_1
                                        )
                                        if isChecked: pts_calculados_41111 += pt
                                
                        with c41111_2:
                                link_4_1_1_1_1 = st.text_area("Link/Evidência (4.1.1.1.1):", value=d41111.get("link", ""), key=f"t_4_1_1_1_1_{ano_sel}", on_change=cb_text_4_1_1_1_1, height=160)
                                placeholder_links_41111 = st.empty()
                                links_41111_visuais = [u[0] for u in re.findall(regex_pure_url, link_4_1_1_1_1 or "")]
                                if links_41111_visuais:
                                        placeholder_links_41111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_41111_visuais]))
                        
                        txt_score_41111 = f"📊 Pontuação Aplicada no Quesito 4.1.1.1.1: {pts_calculados_41111:.1f} pontos"
                        if not lista_salva_41111: txt_score_41111 += " (Aguardando seleção)"
                                
                        st.code(txt_score_41111, language="text")
                        st.write("") # Pequeno espaçador visual complementar opcional
                        bloco_comentarios("4.1.1.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_1_1_1_1_{ano_sel}", False):
                modal_aviso_link("4.1.1.1.1", st.session_state.get(f"links_pendentes_4_1_1_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_1_1_1_1_{ano_sel}"] = False


        # --- QUESITO 4.1.1.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_publicacao_resultados_4_1_1_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.1.1.2 - Publicação dos Resultados da Avaliação do PPA", expanded=True):
                        st.subheader("4.1.1.2 • Publicação dos Resultados")
                        st.write("**4.1.1.2 Houve publicação dos resultados da avaliação dos programas finalísticos do PPA?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_4112 = {
                                "Selecione...": 0.0, 
                                "Sim, para todos os programas finalísticos avaliados do PPA – 04": 4.0, 
                                "Sim, para a maior parte dos programas finalísticos avaliados – 03": 3.0, 
                                "Sim, para a menor parte dos programas finalísticos avaliados – 01": 1.0, 
                                "Não – 00": 0.0
                        }
                        
                        d4112 = res_data.get("4.1.1.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d4112 is None: d4112 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_4112 = d4112.get("valor", "Selecione...")
                        chave_radio_4112 = f"r_4_1_1_2_{v_salvo_4112}_{ano_sel}"

                        def cb_radio_4_1_1_2():
                                val = st.session_state[chave_radio_4112]
                                pts = opcoes_4112[val]
                                lnk = st.session_state.get(f"t_4_1_1_2_{ano_sel}", d4112.get("link", ""))
                                save_resp("4.1.1.2", val, pts, lnk)
                                res_data["4.1.1.2"] = {"valor": val, "pontos": pts, "link": lnk}
                                
                                if "Não" in val:
                                        save_resp("4.1.1.2.1", "XYZ", 0.0, "")
                                        res_data["4.1.1.2.1"] = {"valor": "XYZ", "pontos": 0.0, "link": ""}
                                        st.session_state[f"q41121_{ano_sel}"] = "XYZ"

                        def cb_text_4_1_1_2():
                                lnk = st.session_state[f"t_4_1_1_2_{ano_sel}"]
                                val = st.session_state.get(chave_radio_4112, d4112.get("valor", "Selecione..."))
                                pts = opcoes_4112.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d4112.get("link", "") or "")]
                                
                                mudou_opcao_4112 = val != d4112.get("valor", "")
                                mudou_link_4112 = lnk != d4112.get("link", "")
                                
                                if mudou_opcao_4112 or mudou_link_4112:
                                        save_resp("4.1.1.2", val, pts, lnk)
                                        res_data["4.1.1.2"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_4112 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_4_1_1_2_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_4_1_1_2_{ano_sel}"] = True

                        c4112_1, c4112_2 = st.columns([1, 1])
                        with c4112_1:
                                lista_opcoes_4112 = list(opcoes_4112.keys())
                                idx4112 = 0
                                if d4112.get("valor") in opcoes_4112:
                                        idx4112 = lista_opcoes_4112.index(d4112["valor"])
                                elif d4112.get("valor"):
                                        if "todos os programas" in d4112["valor"]: idx4112 = lista_opcoes_4112.index("Sim, para todos os programas finalísticos avaliados do PPA – 04")
                                        elif "maior parte" in d4112["valor"]: idx4112 = lista_opcoes_4112.index("Sim, para a maior parte dos programas finalísticos avaliados – 03")
                                        elif "menor parte" in d4112["valor"]: idx4112 = lista_opcoes_4112.index("Sim, para a menor parte dos programas finalísticos avaliados – 01")
                                        elif "Não" in d4112["valor"]: idx4112 = lista_opcoes_4112.index("Não – 00")
                                        
                                sel_4_1_1_2 = st.radio("Selecione 4.1.1.2:", options=lista_opcoes_4112, index=idx4112, key=chave_radio_4112, on_change=cb_radio_4_1_1_2, label_visibility="collapsed")
                                pts_4_1_1_2 = opcoes_4112[sel_4_1_1_2]
                                
                        with c4112_2:
                                link_4_1_1_2 = st.text_area("Link/Evidência (4.1.1.2):", value=d4112.get("link", ""), key=f"t_4_1_1_2_{ano_sel}", on_change=cb_text_4_1_1_2, height=130)
                                placeholder_links_4112 = st.empty()
                                links_4112_visuais = [u[0] for u in re.findall(regex_pure_url, link_4_1_1_2 or "")]
                                if links_4112_visuais:
                                        placeholder_links_4112.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_4112_visuais]))
                        
                        txt_score_4112 = f"📊 Pontuação Aplicada no Quesito 4.1.1.2: {pts_4_1_1_2:.1f} pontos"
                        if sel_4_1_1_2 == "Selecione...": txt_score_4112 += " (Aguardando seleção)"
                        st.code(txt_score_4112, language="text")
                        bloco_comentarios("4.1.1.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_1_1_2_{ano_sel}", False):
                modal_aviso_link("4.1.1.2", st.session_state.get(f"links_pendentes_4_1_1_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_1_1_2_{ano_sel}"] = False


        # --- QUESITO 4.1.1.2.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_divulgacao_link_4_1_1_2_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.1.1.2.1 - Link de Divulgação dos Resultados", expanded=True):
                        st.subheader("4.1.1.2.1 • Link de Divulgação")
                        st.write("**4.1.1.2.1 Página eletrônica (link) de divulgação dos resultados (XYZ se não disponível):**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        d41121 = res_data.get("4.1.1.2.1", {"valor": "", "pontos": 0.0, "link": ""})
                        if not isinstance(d41121, dict): d41121 = {"valor": str(d41121), "pontos": 0.0, "link": ""}
                        
                        v_salvo_41121 = d41121.get("valor", "")

                        def cb_input_4_1_1_2_1():
                                lnk = st.session_state[f"q41121_{ano_sel}"]
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d41121.get("valor", "") or "")]
                                
                                mudou_link_41121 = lnk != d41121.get("valor", "")
                                
                                if mudou_link_41121:
                                        save_resp("4.1.1.2.1", lnk, 0.0, "")
                                        res_data["4.1.1.2.1"] = {"valor": lnk, "pontos": 0.0, "link": ""}
                                        
                                        if links_atuais and links_atuais != links_antigos:
                                                st.session_state[f"links_pendentes_4_1_1_2_1_{ano_sel}"] = links_atuais
                                                st.session_state[f"gatilho_modal_4_1_1_2_1_{ano_sel}"] = True

                        link_input_41121 = st.text_input(
                                "Link URL (PPA):", 
                                value=v_salvo_41121, 
                                key=f"q41121_{ano_sel}",
                                on_change=cb_input_4_1_1_2_1,
                                label_visibility="collapsed"
                        )
                        
                        placeholder_links_41121 = st.empty()
                        links_41121_visuais = [u[0] for u in re.findall(regex_pure_url, link_input_41121 or "")]
                        if links_41121_visuais:
                                placeholder_links_41121.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_41121_visuais]))
                        
                        txt_score_41121 = "📊 Quesito Informativo (0.0 pontos)"
                        if not link_input_41121: txt_score_41121 += " (Aguardando preenchimento)"
                        st.code(txt_score_41121, language="text")
                        bloco_comentarios("4.1.1.2.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_1_1_2_1_{ano_sel}", False):
                modal_aviso_link("4.1.1.2.1", st.session_state.get(f"links_pendentes_4_1_1_2_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_1_1_2_1_{ano_sel}"] = False

        # --- QUESITO 4.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_coerencia_indicadores_4_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.2 - Coerência dos Indicadores com as Metas", expanded=True):
                        st.subheader("4.2 • Coerência dos Indicadores")
                        st.write("**4.2 Os indicadores são mensuráveis e estão coerentes com as metas físico-financeiras estabelecidas?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_42 = {
                                "Selecione...": 0.0, 
                                "Todos os indicadores do PPA - 25": 25.0, 
                                "A maior parte dos indicadores – 17": 17.0, 
                                "A menor parte dos indicadores – 08": 8.0, 
                                "Nenhum indicador – 00": 0.0
                        }
                        
                        d42 = res_data.get("4.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d42 is None: d42 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_42 = d42.get("valor", "Selecione...")
                        chave_radio_42 = f"r_4_2_{v_salvo_42}_{ano_sel}"

                        def cb_radio_4_2():
                                val = st.session_state[chave_radio_42]
                                pts = opcoes_42[val]
                                lnk = st.session_state.get(f"t_4_2_{ano_sel}", d42.get("link", ""))
                                save_resp("4.2", val, pts, lnk)
                                res_data["4.2"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_4_2():
                                lnk = st.session_state[f"t_4_2_{ano_sel}"]
                                val = st.session_state.get(chave_radio_42, d42.get("valor", "Selecione..."))
                                pts = opcoes_42.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d42.get("link", "") or "")]
                                
                                mudou_opcao_42 = val != d42.get("valor", "")
                                mudou_link_42 = lnk != d42.get("link", "")
                                
                                if mudou_opcao_42 or mudou_link_42:
                                        save_resp("4.2", val, pts, lnk)
                                        res_data["4.2"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_42 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_4_2_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = True

                        c42_1, c42_2 = st.columns([1, 1])
                        with c42_1:
                                lista_opcoes_42 = list(opcoes_42.keys())
                                idx42 = 0
                                if d42.get("valor") in opcoes_42:
                                        idx42 = lista_opcoes_42.index(d42["valor"])
                                elif d42.get("valor"):
                                        if "Todos os" in d42["valor"]: idx42 = lista_opcoes_42.index("Todos os indicadores do PPA - 25")
                                        elif "maior parte" in d42["valor"]: idx42 = lista_opcoes_42.index("A maior parte dos indicadores – 17")
                                        elif "menor parte" in d42["valor"]: idx42 = lista_opcoes_42.index("A menor parte dos indicadores – 08")
                                        elif "Nenhum" in d42["valor"]: idx42 = lista_opcoes_42.index("Nenhum indicador – 00")
                                        
                                sel_4_2 = st.radio("Selecione 4.2:", options=lista_opcoes_42, index=idx42, key=chave_radio_42, on_change=cb_radio_4_2, label_visibility="collapsed")
                                pts_4_2 = opcoes_42[sel_4_2]
                                
                        with c42_2:
                                link_4_2 = st.text_area("Link/Evidência (4.2):", value=d42.get("link", ""), key=f"t_4_2_{ano_sel}", on_change=cb_text_4_2, height=130)
                                placeholder_links_42 = st.empty()
                                links_42_visuais = [u[0] for u in re.findall(regex_pure_url, link_4_2 or "")]
                                if links_42_visuais:
                                        placeholder_links_42.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_42_visuais]))
                        
                        txt_score_42 = f"📊 Pontuação Aplicada no Quesito 4.2: {pts_4_2:.1f} pontos"
                        if sel_4_2 == "Selecione...": txt_score_42 += " (Aguardando seleção)"
                        st.code(txt_score_42, language="text")
                        bloco_comentarios("4.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_2_{ano_sel}", False):
                modal_aviso_link("4.2", st.session_state.get(f"links_pendentes_4_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = False


        # --- QUESITO 4.3 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_planos_setoriais_4_3_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 4.3 - Planos Setoriais Incorporados no PPA", expanded=True):
                        st.subheader("4.3 • Planos Setoriais")
                        st.write("**4.3 Assinale os Planos Setoriais que foram incorporados no Plano Plurianual (PPA):**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        planos_pesos_43 = {
                                "Plano Diretor – 00": 0.0,
                                "Plano Municipal da Educação – 2,5": 2.5,
                                "Plano Municipal pela Primeira Infância – 00": 0.0,
                                "Plano Municipal da Saúde – 2,5": 2.5,
                                "Plano de Mobilidade Urbana – 00": 0.0,
                                "Plano de Saneamento Básico – 2,5": 2.5,
                                "Plano de Resíduos Sólidos – 2,5": 2.5,
                                "Plano de Contingência Municipal – PLANCON de Defesa Civil – 2,5": 2.5,
                                "Plano Diretor de Tecnologia da Informação – 2,5": 2.5,
                                "Não incorporou nenhum dos planos acima – -10 (perde 10 pontos)": -10.0
                        }
                        
                        d43 = res_data.get("4.3", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d43 is None: d43 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_43 = ast.literal_eval(d43.get("valor", "[]"))
                                if not isinstance(lista_salva_43, list): lista_salva_43 = []
                        except Exception:
                                lista_salva_43 = []

                        def cb_check_4_3():
                                sel = []
                                for idx, plano in enumerate(planos_pesos_43.keys()):
                                        key_chk = f"chk_43_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(plano)
                                
                                if any("Não incorporou" in p for p in sel):
                                        pts = -10.0
                                else:
                                        pts = sum(planos_pesos_43[p] for p in sel)
                                        
                                lnk = st.session_state.get(f"t_4_3_{ano_sel}", d43.get("link", ""))
                                save_resp("4.3", str(sel), float(pts), lnk)
                                res_data["4.3"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}

                        def cb_text_4_3():
                                lnk = st.session_state[f"t_4_3_{ano_sel}"]
                                sel = []
                                for idx, plano in enumerate(planos_pesos_43.keys()):
                                        key_chk = f"chk_43_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(plano)
                                                
                                if any("Não incorporou" in p for p in sel):
                                        pts = -10.0
                                else:
                                        pts = sum(planos_pesos_43[p] for p in sel)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d43.get("link", "") or "")]
                                
                                mudou_opcao_43 = str(sel) != d43.get("valor", "[]")
                                mudou_link_43 = lnk != d43.get("link", "")
                                
                                if mudou_opcao_43 or mudou_link_43:
                                        save_resp("4.3", str(sel), float(pts), lnk)
                                        res_data["4.3"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_43 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_4_3_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_4_3_{ano_sel}"] = True

                        c43_1, c43_2 = st.columns([1, 1])
                        with c43_1:
                                lista_atual_selecao_43 = []
                                for idx, (plano, pt) in enumerate(planos_pesos_43.items()):
                                        isChecked = st.checkbox(
                                                plano, 
                                                value=plano in lista_salva_43, 
                                                key=f"chk_43_{idx}_{ano_sel}",
                                                on_change=cb_check_4_3
                                        )
                                        if isChecked:
                                                lista_atual_selecao_43.append(plano)
                                                
                                if any("Não incorporou" in p for p in lista_atual_selecao_43):
                                        pts_calculados_43 = -10.0
                                else:
                                        pts_calculados_43 = sum(planos_pesos_43[p] for p in lista_atual_selecao_43)
                                
                        with c43_2:
                                link_4_3 = st.text_area("Link/Evidência (4.3):", value=d43.get("link", ""), key=f"t_4_3_{ano_sel}", on_change=cb_text_4_3, height=220)
                                placeholder_links_43 = st.empty()
                                links_43_visuais = [u[0] for u in re.findall(regex_pure_url, link_4_3 or "")]
                                if links_43_visuais:
                                        placeholder_links_43.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_43_visuais]))
                        
                        sufixo_penalidade = " (Penalidade aplicada)" if pts_calculados_43 < 0 else ""
                        txt_score_43 = f"📊 Pontuação Aplicada no Quesito 4.3: {pts_calculados_43:.1f} pontos{sufixo_penalidade}"
                        if not lista_atual_selecao_43: 
                                txt_score_43 = f"📊 Pontuação Aplicada no Quesito 4.3: 0.0 pontos (Aguardando seleção)"
                                
                        st.code(txt_score_43, language="text")
                        bloco_comentarios("4.3", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_4_3_{ano_sel}", False):
                modal_aviso_link("4.3", st.session_state.get(f"links_pendentes_4_3_{ano_sel}", []))
                st.session_state[f"gatilho_modal_4_3_{ano_sel}"] = False

# =============================================================================
        # SEÇÃO 5: RECEITA
        # =============================================================================
        st.header("5.0 Previsão de Receitas")

        # --- QUESITO 5.0 • TOTALMENTE INDEPENDENTE (ESTRUTURA DE VALIDAÇÃO DO SEU MODELO) ---
        with st.container(key=f"container_bloco_previsao_receitas_5_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 5.0 - Estudo de Previsão de Receitas", expanded=True):
                st.subheader("5.0 • Previsão de Receitas")
                st.write("**É realizado estudo/análise para previsão de receitas, no mínimo, anualmente? Aplicação de índice inflacionário ao valor arrecadado do exercício anterior NÃO é estudo/análise de previsão de receita**")
                
                opcoes_50 = {
                    "Selecione...": 0.0, 
                    "Sim – 06": 6.0, 
                    "Não – 00": 0.0
                }
                
                d50 = res_data.get("5.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d50 is None: d50 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_50 = d50.get("valor", "Selecione...")
                chave_radio_50 = f"r_5_0_{v_salvo_50}_{ano_sel}"

                # Padrão de extração de links
                regex_pure_url = r'(https?://[^\s<>"]+?)(?=[.,;:]?(\s|$))'

                # Callback para o Radio Button do 5.0
                def cb_radio_5_0():
                    val = st.session_state[chave_radio_50]
                    pts = opcoes_50[val]
                    lnk = st.session_state.get(f"t_5_0_{ano_sel}", d50.get("link", ""))
                    save_resp("5.0", val, pts, lnk)
                    res_data["5.0"] = {"valor": val, "pontos": pts, "link": lnk}

                # Callback para a Área de Texto do 5.0 (Baseado fielmente na lógica do seu modelo)
                def cb_text_5_0():
                    lnk = st.session_state[f"t_5_0_{ano_sel}"]
                    val = st.session_state.get(chave_radio_50, d50.get("valor", "Selecione..."))
                    pts = opcoes_50.get(val, 0.0)
                    
                    links_50_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_50_antigos = [u[0] for u in re.findall(regex_pure_url, d50.get("link", "") or "")]
                    
                    mudou_opcao_50 = val != d50.get("valor", "")
                    mudou_link_50 = lnk != d50.get("link", "")
                    
                    if mudou_opcao_50 or mudou_link_50:
                        save_resp("5.0", val, pts, lnk)
                        res_data["5.0"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if mudou_link_50 and links_50_atuais:
                            if links_50_atuais != links_50_antigos:
                                # Dispara o modal passando os dois argumentos como no seu exemplo
                                st.session_state[f"links_pendentes_5_0_{ano_sel}"] = links_50_atuais
                                st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

                c50_1, c50_2 = st.columns([1, 1])
                with c50_1:
                    lista_opcoes_50 = list(opcoes_50.keys())
                    idx50 = 0
                    if d50.get("valor") in opcoes_50:
                        idx50 = lista_opcoes_50.index(d50["valor"])
                    elif d50.get("valor"):
                        if "Sim" in d50["valor"]: idx50 = lista_opcoes_50.index("Sim – 06")
                        elif "Não" in d50["valor"]: idx50 = lista_opcoes_50.index("Não – 00")
                        
                    sel_5_0 = st.radio(
                        "Selecione 5.0:", 
                        options=lista_opcoes_50, 
                        index=idx50, 
                        key=chave_radio_50, 
                        on_change=cb_radio_5_0, 
                        label_visibility="collapsed"
                    )
                    pts_5_0 = opcoes_50[sel_5_0]
                    
                with c50_2:
                    link_5_0 = st.text_area(
                        "Link/Evidência (5.0):", 
                        value=d50.get("link", ""), 
                        key=f"t_5_0_{ano_sel}", 
                        on_change=cb_text_5_0, 
                        height=130
                    )
                    placeholder_links_50 = st.empty()
                    
                    links_50_visuais = [u[0] for u in re.findall(regex_pure_url, link_5_0 or "")]
                    if links_50_visuais:
                        placeholder_links_50.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_50_visuais]))
                
                txt_score_50 = f"📊 Pontuação Aplicada no Quesito 5.0: {pts_5_0:.1f} pontos"
                if sel_5_0 == "Selecione...": 
                    txt_score_50 += " (Aguardando seleção)"
                st.code(txt_score_50, language="text")
                bloco_comentarios("5.0", res_data)

        # Ativação síncrona do Modal usando a assinatura de 2 argumentos igual ao modelo
        if st.session_state.get(f"gatilho_modal_5_0_{ano_sel}", False):
            modal_aviso_link("5.0", st.session_state.get(f"links_pendentes_5_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = False

      
          # --- QUESITO 5.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_tributos_5_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 5.1 - Tipos de Tributos e Repasses Avaliados", expanded=True):
                        st.subheader("5.1 • Análise e Estudo da Previsão da Receita")
                        st.write("**5.1 Assinale os tipos de tributos e repasses/transferências avaliados na análise e estudo da previsão da receita:**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        tribs_51 = {
                                "Imposto sobre a Propriedade Predial e Territorial Urbano (IPTU) – 0,5": 0.5, 
                                "Imposto sobre a Transmissão de Bens Imóveis (ITBI) – 0,5": 0.5, 
                                "Imposto Sobre Serviços de Qualquer Natureza (ISSQN) – 0,5": 0.5, 
                                "Taxas – 0,25": 0.25, 
                                "Contribuições – 0,25": 0.25, 
                                "Transferências Obrigatórias Recebidas da União. Ex.: FPM, CIDE, ITR, Royalties e FUNDEB. – 01": 1.0, 
                                "Transferências Obrigatórias Recebidas do Estado. Ex.: ICMS, IPVA. – 01": 1.0, 
                                "Outros - 0,0": 0.0
                        }
                        
                        d51 = res_data.get("5.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d51 is None: d51 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_51 = ast.literal_eval(d51.get("valor", "[]"))
                                if not isinstance(lista_salva_51, list): lista_salva_51 = []
                        except Exception:
                                lista_salva_51 = []

                        def cb_check_5_1():
                                sel = []
                                pts = 0.0
                                for idx, (t, pt) in enumerate(tribs_51.items()):
                                        key_chk = f"chk_51_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(t)
                                                pts += pt
                                lnk = st.session_state.get(f"t_5_1_{ano_sel}", d51.get("link", ""))
                                save_resp("5.1", str(sel), float(pts), lnk)
                                res_data["5.1"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}

                        def cb_text_5_1():
                                lnk = st.session_state[f"t_5_1_{ano_sel}"]
                                sel = []
                                pts = 0.0
                                for idx, (t, pt) in enumerate(tribs_51.items()):
                                        key_chk = f"chk_51_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(t)
                                                pts += pt
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d51.get("link", "") or "")]
                                
                                mudou_opcao_51 = str(sel) != d51.get("valor", "[]")
                                mudou_link_51 = lnk != d51.get("link", "")
                                
                                if mudou_opcao_51 or mudou_link_51:
                                        save_resp("5.1", str(sel), float(pts), lnk)
                                        res_data["5.1"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_51 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_5_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = True

                        c51_1, c51_2 = st.columns([1, 1])
                        with c51_1:
                                pts_calculados_51 = 0.0
                                for idx, (t, pt) in enumerate(tribs_51.items()):
                                        isChecked = st.checkbox(
                                                t, 
                                                value=t in lista_salva_51, 
                                                key=f"chk_51_{idx}_{ano_sel}",
                                                on_change=cb_check_5_1
                                        )
                                        if isChecked: pts_calculados_51 += pt
                                
                        with c51_2:
                                link_5_1 = st.text_area("Link/Evidência (5.1):", value=d51.get("link", ""), key=f"t_5_1_{ano_sel}", on_change=cb_text_5_1, height=220)
                                placeholder_links_51 = st.empty()
                                links_51_visuais = [u[0] for u in re.findall(regex_pure_url, link_5_1 or "")]
                                if links_51_visuais:
                                        placeholder_links_51.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_51_visuais]))
                        
                        txt_score_51 = f"📊 Pontuação Aplicada no Quesito 5.1: {pts_calculados_51:.2f} pontos"
                        if not lista_salva_51: txt_score_51 += " (Aguardando seleção)"
                                
                        st.code(txt_score_51, language="text")
                        bloco_comentarios("5.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_5_1_{ano_sel}", False):
                modal_aviso_link("5.1", st.session_state.get(f"links_pendentes_5_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = False


        # --- QUESITO 5.1.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_estimativa_icms_5_1_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 5.1.1 - Previsão de Repasse do ICMS Estadual", expanded=True):
                        st.subheader("5.1.1 • Estimativa de Transferências Obrigatórias")
                        st.write("**5.1.1 A estimativa de transferências obrigatórias leva em consideração o cálculo de previsão de repasse do ICMS realizado periodicamente pela Fazenda Pública Estadual?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opc511 = {
                                "Selecione...": 0.0,
                                "Sim, com reestimativa da receita prevista na LOA no decorrer da execução orçamentária-financeira – 02": 2.0, 
                                "Sim, somente para elaborar a LOA – 01": 1.0, 
                                "Não – 00": 0.0
                        }
                        
                        d511 = res_data.get("5.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d511 is None: d511 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_511 = d511.get("valor", "Selecione...")
                        chave_radio_511 = f"r_5_1_1_{v_salvo_511}_{ano_sel}"

                        def cb_radio_5_1_1():
                                val = st.session_state[chave_radio_511]
                                pts = opc511[val]
                                lnk = st.session_state.get(f"t_5_1_1_{ano_sel}", d511.get("link", ""))
                                save_resp("5.1.1", val, pts, lnk)
                                res_data["5.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_5_1_1():
                                lnk = st.session_state[f"t_5_1_1_{ano_sel}"]
                                val = st.session_state.get(chave_radio_511, d511.get("valor", "Selecione..."))
                                pts = opc511.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d511.get("link", "") or "")]
                                
                                mudou_opcao_511 = val != d511.get("valor", "")
                                mudou_link_511 = lnk != d511.get("link", "")
                                
                                if mudou_opcao_511 or mudou_link_511:
                                        save_resp("5.1.1", val, pts, lnk)
                                        res_data["5.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_511 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_5_1_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_5_1_1_{ano_sel}"] = True

                        c511_1, c511_2 = st.columns([1, 1])
                        with c511_1:
                                lista_opcoes_511 = list(opc511.keys())
                                idx511 = 0
                                if d511.get("valor") in opc511:
                                        idx511 = lista_opcoes_511.index(d511["valor"])
                                elif d511.get("valor"):
                                        if "decorrer da execução" in d511["valor"]: idx511 = lista_opcoes_511.index("Sim, com reestimativa da receita prevista na LOA no decorrer da execução orçamentária-financeira – 02")
                                        elif "somente para elaborar" in d511["valor"]: idx511 = lista_opcoes_511.index("Sim, somente para elaborar a LOA – 01")
                                        elif "Não" in d511["valor"]: idx511 = lista_opcoes_511.index("Não – 00")
                                        
                                sel_5_1_1 = st.radio("Selecione 5.1.1:", options=lista_opcoes_511, index=idx511, key=chave_radio_511, on_change=cb_radio_5_1_1, label_visibility="collapsed")
                                pts_5_1_1 = opc511[sel_5_1_1]
                                
                        with c511_2:
                                link_5_1_1 = st.text_area("Link/Evidência (5.1.1):", value=d511.get("link", ""), key=f"t_5_1_1_{ano_sel}", on_change=cb_text_5_1_1, height=130)
                                placeholder_links_511 = st.empty()
                                links_511_visuais = [u[0] for u in re.findall(regex_pure_url, link_5_1_1 or "")]
                                if links_511_visuais:
                                        placeholder_links_511.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_511_visuais]))
                        
                        txt_score_511 = f"📊 Pontuação Aplicada no Quesito 5.1.1: {pts_5_1_1:.1f} pontos"
                        if sel_5_1_1 == "Selecione...": txt_score_511 += " (Aguardando seleção)"
                        st.code(txt_score_511, language="text")
                        bloco_comentarios("5.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_5_1_1_{ano_sel}", False):
                modal_aviso_link("5.1.1", st.session_state.get(f"links_pendentes_5_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_5_1_1_{ano_sel}"] = False


        # --- QUESITO 5.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_metodologia_receita_5_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 5.2 - Metodologia de Projeção Conforme a Espécie", expanded=True):
                        st.subheader("5.2 • Metodologia por Espécie de Receita")
                        st.write("**5.2 A metodologia utilizada para projeção da receita varia de acordo com a espécie da receita orçamentária projetada?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_52 = {
                                "Selecione...": 0.0,
                                "Sim – 06": 6.0,
                                "Não – 00": 0.0
                        }
                        
                        d52 = res_data.get("5.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d52 is None: d52 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_52 = d52.get("valor", "Selecione...")
                        chave_radio_52 = f"r_5_2_{v_salvo_52}_{ano_sel}"

                        def cb_radio_5_2():
                                val = st.session_state[chave_radio_52]
                                pts = opcoes_52[val]
                                lnk = st.session_state.get(f"t_5_2_{ano_sel}", d52.get("link", ""))
                                save_resp("5.2", val, pts, lnk)
                                res_data["5.2"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_5_2():
                                lnk = st.session_state[f"t_5_2_{ano_sel}"]
                                val = st.session_state.get(chave_radio_52, d52.get("valor", "Selecione..."))
                                pts = opcoes_52.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d52.get("link", "") or "")]
                                
                                mudou_opcao_52 = val != d52.get("valor", "")
                                mudou_link_52 = lnk != d52.get("link", "")
                                
                                if mudou_opcao_52 or mudou_link_52:
                                        save_resp("5.2", val, pts, lnk)
                                        res_data["5.2"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_52 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_5_2_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = True

                        c52_1, c52_2 = st.columns([1, 1])
                        with c52_1:
                                lista_opcoes_52 = list(opcoes_52.keys())
                                idx52 = 0
                                if d52.get("valor") in opcoes_52:
                                        idx52 = lista_opcoes_52.index(d52["valor"])
                                elif d52.get("valor"):
                                        if "Sim" in d52["valor"]: idx52 = lista_opcoes_52.index("Sim – 06")
                                        elif "Não" in d52["valor"]: idx52 = lista_opcoes_52.index("Não – 00")
                                        
                                sel_5_2 = st.radio("Selecione 5.2:", options=lista_opcoes_52, index=idx52, key=chave_radio_52, on_change=cb_radio_5_2, label_visibility="collapsed")
                                pts_5_2 = opcoes_52[sel_5_2]
                                
                        with c52_2:
                                link_5_2 = st.text_area("Link/Evidência (5.2):", value=d52.get("link", ""), key=f"t_5_2_{ano_sel}", on_change=cb_text_5_2, height=130)
                                placeholder_links_52 = st.empty()
                                links_5_2_visuais = [u[0] for u in re.findall(regex_pure_url, link_5_2 or "")]
                                if links_5_2_visuais:
                                        placeholder_links_52.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_5_2_visuais]))
                        
                        txt_score_52 = f"📊 Pontuação Aplicada no Quesito 5.2: {pts_5_2:.1f} pontos"
                        if sel_5_2 == "Selecione...": txt_score_52 += " (Aguardando seleção)"
                        st.code(txt_score_52, language="text")
                        bloco_comentarios("5.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_5_2_{ano_sel}", False):
                modal_aviso_link("5.2", st.session_state.get(f"links_pendentes_5_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = False


        # --- QUESITO 6.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_itens_ldo_6_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 6.0 - Itens que a LDO Dispõe", expanded=True):
                        st.subheader("6.0 • Disposições da LDO")
                        st.write("**6.0 Assinale os itens que a LDO dispõe:**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        itens_ldo_60 = {
                                "Custos estimados, indicators e metas físicas que se correlacionam com as ações do governo municipal – 0,5": 0.5, 
                                "Critérios para limitação desempenho e movimentação financeira; ressalvados os pagamentos do serviço da dívida, os relativos à inovação e ao desenvolvimento científico e tecnológico custeadas por fundo criado para tal finalidade. – 0,5": 0.5, 
                                "Critérios para repasses a entidades do terceiro setor – 00": 0.0, 
                                "Critérios para ajuda financeira a entidades da Administração indireta – 00": 0.0, 
                                "Critérios para o Poder Executivo estabelecer a programação financeira mensal para todo o Município, nele incluído a Câmara – 01": 1.0, 
                                "Percentual da Receita Corrente Líquida que será retido, na peça orçamentária, enquanto Reserva de Contingência, destinada a passivos contingentes e outros riscos fiscais – 01": 1.0, 
                                "Critérios para contratação de horas extras quando o Poder superar o limite prudencial para pessoal: Executivo, 51,30% da RCL; Legislativo, 5,7% da RCL – 0,5": 0.5, 
                                "Determinação do índice de preços para atualização monetária do principal da Dívida Mobiliária Refinanciada – 00": 0.0, 
                                "Autorização para o Município auxiliar o custeio de despesas próprias do Estado e da União – 00": 0.0, 
                                "Requisitos para início de novos projetos, após o adequado atendimento/manutenção dos que estão em andamento – 0,5": 0.5,
                                "Dispor sobre pagamento de servidor ou empregado público com recursos vinculados à parceria firmada com o terceiro setor – 00": 0.0
                        }
                        
                        d60 = res_data.get("6.0", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d60 is None: d60 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_60 = ast.literal_eval(d60.get("valor", "[]"))
                                if not isinstance(lista_salva_60, list): lista_salva_60 = []
                        except Exception:
                                lista_salva_60 = []

                        def cb_check_6_0():
                                sel = []
                                pts = 0.0
                                for idx, (item_texto, pt) in enumerate(itens_ldo_60.items()):
                                        key_chk = f"chk_60_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(item_texto)
                                                pts += pt
                                lnk = st.session_state.get(f"t_6_0_{ano_sel}", d60.get("link", ""))
                                save_resp("6.0", str(sel), float(pts), lnk)
                                res_data["6.0"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}

                        def cb_text_6_0():
                                lnk = st.session_state[f"t_6_0_{ano_sel}"]
                                sel = []
                                pts = 0.0
                                for idx, (item_texto, pt) in enumerate(itens_ldo_60.items()):
                                        key_chk = f"chk_60_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(item_texto)
                                                pts += pt
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d60.get("link", "") or "")]
                                
                                mudou_opcao_60 = str(sel) != d60.get("valor", "[]")
                                mudou_link_60 = lnk != d60.get("link", "")
                                
                                if mudou_opcao_60 or mudou_link_60:
                                        save_resp("6.0", str(sel), float(pts), lnk)
                                        res_data["6.0"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_60 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_6_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

                        c60_1, c60_2 = st.columns([1, 1])
                        with c60_1:
                                pts_calculados_60 = 0.0
                                for idx, (item_texto, pt) in enumerate(itens_ldo_60.items()):
                                        isChecked = st.checkbox(
                                                item_texto, 
                                                value=item_texto in lista_salva_60, 
                                                key=f"chk_60_{idx}_{ano_sel}",
                                                on_change=cb_check_6_0
                                        )
                                        if isChecked: pts_calculados_60 += pt
                                
                        with c60_2:
                                link_6_0 = st.text_area("Link/Evidência (6.0):", value=d60.get("link", ""), key=f"t_6_0_{ano_sel}", on_change=cb_text_6_0, height=250)
                                placeholder_links_60 = st.empty()
                                links_60_visuais = [u[0] for u in re.findall(regex_pure_url, link_6_0 or "")]
                                if links_60_visuais:
                                        placeholder_links_60.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_60_visuais]))
                        
                        txt_score_60 = f"📊 Pontuação Aplicada no Quesito 6.0: {pts_calculados_60:.2f} pontos"
                        if not lista_salva_60: txt_score_60 += " (Aguardando seleção)"
                                
                        st.code(txt_score_60, language="text")
                        bloco_comentarios("6.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
                modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = False


        # --- QUESITO 7.0 e 7.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_alteracao_decreto_7_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 7.0 / 7.1 - Alteração Orçamentária por Decreto", expanded=True):
                        st.subheader("7.0 • Alterações Orçamentárias por Decreto")
                        st.write("**7.0 Houve alteração orçamentária decorrente de remanejamento, transposição ou transferência de uma categoria de programação para outra ou de um órgão para outro por decreto?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_70 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d70 = res_data.get("7.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d70 is None: d70 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                        
                        d71 = res_data.get("7.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d71 is None: d71 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        funcs_alt_71 = {
                                "10 - Saúde – -05 (perde 05 pontos)": -5.0, 
                                "12 - Educação – -05 (perde 05 pontos)": -5.0, 
                                "17 - Saneamento – -05 (perde 05 pontos)": -5.0, 
                                "19 - Ciência e Tecnologia – 00": 0.0, 
                                "26 - Transporte – -05 (perde 05 pontos)": -5.0, 
                                "Outras – -05 (perde 05 pontos)": -5.0
                        }

                        try:
                                lista_salva_71 = ast.literal_eval(d71.get("valor", "[]"))
                                if not isinstance(lista_salva_71, list): lista_salva_71 = []
                        except Exception:
                                lista_salva_71 = []

                        v_salvo_70 = d70.get("valor", "Selecione...")
                        chave_radio_70 = f"r_7_0_{v_salvo_70}_{ano_sel}"

                        def cb_radio_7_0():
                                val = st.session_state[chave_radio_70]
                                lnk = st.session_state.get(f"t_7_0_{ano_sel}", d70.get("link", ""))
                                save_resp("7.0", val, 0.0, lnk)
                                res_data["7.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                # Limpeza automática do subquesito condicional se mudar para Não
                                if val != "Sim":
                                        save_resp("7.1", "[]", 0.0, "")
                                        res_data["7.1"] = {"valor": "[]", "pontos": 0.0, "link": ""}
                                        for idx in range(len(funcs_alt_71)):
                                                st.session_state[f"chk_71_{idx}_{ano_sel}"] = False

                        def cb_text_7_0():
                                lnk = st.session_state[f"t_7_0_{ano_sel}"]
                                val = st.session_state.get(chave_radio_70, d70.get("valor", "Selecione..."))
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d70.get("link", "") or "")]
                                
                                mudou_opcao_70 = val != d70.get("valor", "")
                                mudou_link_70 = lnk != d70.get("link", "")
                                
                                if mudou_opcao_70 or mudou_link_70:
                                        save_resp("7.0", val, 0.0, lnk)
                                        res_data["7.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                        
                                        if mudou_link_70 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_7_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

                        def cb_check_7_1():
                                sel = []
                                pts = 0.0
                                for idx, (f, pt) in enumerate(funcs_alt_71.items()):
                                        key_chk = f"chk_71_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(f)
                                                pts += pt
                                save_resp("7.1", str(sel), float(pts), "")
                                res_data["7.1"] = {"valor": str(sel), "pontos": float(pts), "link": ""}

                        c70_1, c70_2 = st.columns([1, 1])
                        with c70_1:
                                lista_opcoes_70 = list(opcoes_70.keys())
                                idx70 = 0
                                if d70.get("valor") in opcoes_70:
                                        idx70 = lista_opcoes_70.index(d70["valor"])
                                        
                                sel_7_0 = st.radio("Selecione 7.0:", options=lista_opcoes_70, index=idx70, key=chave_radio_70, on_change=cb_radio_7_0, label_visibility="collapsed")
                                
                        with c70_2:
                                link_7_0 = st.text_area("Link/Evidência (7.0):", value=d70.get("link", ""), key=f"t_7_0_{ano_sel}", on_change=cb_text_7_0, height=100)
                                placeholder_links_70 = st.empty()
                                links_70_visuais = [u[0] for u in re.findall(regex_pure_url, link_7_0 or "")]
                                if links_70_visuais:
                                        placeholder_links_70.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_70_visuais]))
                        
                        # --- SUBQUESITO CONDICIONAL 7.1 ---
                        pts_calculados_71 = 0.0
                        if sel_7_0 == "Sim":
                                st.write("---")
                                st.write("**7.1 Assinale a classificação funcional da despesa, objeto de alterações orçamentárias decorrentes de remanejamento, transposição e transferências realizadas por decreto:**")
                                
                                c71_bloco = st.container()
                                with c71_bloco:
                                        for idx, (f, pt) in enumerate(funcs_alt_71.items()):
                                                isChecked = st.checkbox(
                                                        f, 
                                                        value=f in lista_salva_71, 
                                                        key=f"chk_71_{idx}_{ano_sel}",
                                                        on_change=cb_check_7_1
                                                )
                                                if isChecked: pts_calculados_71 += pt

                        # Exibição unificada de escores
                        if sel_7_0 == "Sim":
                                sufixo_penalidade = " (Penalidades aplicadas)" if pts_calculados_71 < 0 else ""
                                txt_score_7 = f"📊 Impacto de Pontuação (Quesito 7.0 + 7.1): {pts_calculados_71:.1f} pontos{sufixo_penalidade}"
                        elif sel_7_0 == "Não":
                                txt_score_7 = "📊 Impacto de Pontuação (Quesito 7.0): 0.0 pontos (Sem penalidades aplicadas)"
                        else:
                                txt_score_7 = "📊 Impacto de Pontuação (Quesito 7.0): 0.0 pontos (Aguardando seleção)"
                                
                        st.code(txt_score_7, language="text")
                        bloco_comentarios("7.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_7_0_{ano_sel}", False):
                modal_aviso_link("7.0", st.session_state.get(f"links_pendentes_7_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = False

        # --- QUESITO 8.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_metas_fiscais_8_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.0 - Anexo de Metas Fiscais na LDO", expanded=True):
                        st.subheader("8.0 • Anexo de Metas Fiscais")
                        st.write("**O Anexo de Metas Fiscais integra a Lei de Diretrizes Orçamentárias (LDO), nos termos exigidos pela Lei de Responsabilidade Fiscal?**")
                        st.caption("ℹ *Estabelecidas metas anuais, em valores correntes e constantes, relativas a receitas, despesas, resultados nominal e primário e montante da dívida pública, para o exercício a que se referirem e para os dois seguintes. Caso não esteja disponível na internet, recomendamos anexar o Anexo de Metas Fiscais (MDF), conforme Instrução de Preenchimento (IP) no Sistema de Questionários.*")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_80 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d80 = res_data.get("8.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d80 is None: d80 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_80 = d80.get("valor", "Selecione...")
                        chave_radio_80 = f"r_8_0_{v_salvo_80}_{ano_sel}"

                        def cb_radio_8_0():
                                val = st.session_state[chave_radio_80]
                                lnk = st.session_state.get(f"t_8_0_{ano_sel}", d80.get("link", ""))
                                save_resp("8.0", val, 0.0, lnk)
                                res_data["8.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                # Se alterado para Não, limpa com segurança os quesitos dependentes para evitar lixo
                                if val == "Não":
                                        save_resp("8.1", "", 0.0, "")
                                        res_data["8.1"] = {"valor": "", "pontos": 0.0, "link": ""}
                                        save_resp("8.2", "[]", 0.0, "")
                                        res_data["8.2"] = {"valor": "[]", "pontos": 0.0, "link": ""}

                        def cb_text_8_0():
                                lnk = st.session_state[f"t_8_0_{ano_sel}"]
                                val = st.session_state.get(chave_radio_80, d80.get("valor", "Selecione..."))
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d80.get("link", "") or "")]
                                
                                mudou_opcao_80 = val != d80.get("valor", "")
                                mudou_link_80 = lnk != d80.get("link", "")
                                
                                if mudou_opcao_80 or mudou_link_80:
                                        save_resp("8.0", val, 0.0, lnk)
                                        res_data["8.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                        
                                        if mudou_link_80 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

                        c80_1, c80_2 = st.columns([1, 1])
                        with c80_1:
                                lista_opcoes_80 = list(opcoes_80.keys())
                                idx80 = 0
                                if d80.get("valor") in opcoes_80:
                                        idx80 = lista_opcoes_80.index(d80["valor"])
                                        
                                sel_8_0 = st.radio("Selecione 8.0:", options=lista_opcoes_80, index=idx80, key=chave_radio_80, on_change=cb_radio_8_0, label_visibility="collapsed")
                                
                        with c80_2:
                                link_8_0 = st.text_area("Link/Evidência (8.0):", value=d80.get("link", ""), key=f"t_8_0_{ano_sel}", on_change=cb_text_8_0, height=100)
                                placeholder_links_80 = st.empty()
                                links_80_visuais = [u[0] for u in re.findall(regex_pure_url, link_8_0 or "")]
                                if links_80_visuais:
                                        placeholder_links_80.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_80_visuais]))
                        
                        txt_score_80 = f"📊 Impacto de Pontuação no Quesito 8.0: 0.0 pontos"
                        if sel_8_0 == "Selecione...": txt_score_80 += " (Aguardando seleção)"
                        st.code(txt_score_80, language="text")
                        bloco_comentarios("8.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_8_0_{ano_sel}", False):
                modal_aviso_link("8.0", st.session_state.get(f"links_pendentes_8_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = False

        
        # --- QUESITO 8.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_url_metas_8_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.1 - Link de Divulgação das Metas Fiscais", expanded=True):
                        st.subheader("8.1 • URL do Anexo de Metas Fiscais")
                        st.write("**Informe a página eletrônica (link na internet) de divulgação do Anexo de Metas Fiscais (XYZ se não disponível):**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        d81 = res_data.get("8.1", {"valor": "", "pontos": 0.0, "link": ""})
                        if d81 is None: d81 = {"valor": "", "pontos": 0.0, "link": ""}
                        
                        chave_input_81 = f"inp_81_{ano_sel}"

                        def cb_text_8_1():
                                val = st.session_state[chave_input_81]
                                lnk = st.session_state.get(f"t_8_1_{ano_sel}", d81.get("link", ""))
                                
                                # Processamento de regras de score baseado no valor inserido
                                pts = 0.0
                                if val.strip().upper() == "XYZ":
                                        pts = -10.0
                                elif not val.strip():
                                        pts = 0.0
                                        
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d81.get("link", "") or "")]
                                
                                mudou_opcao_81 = val != d81.get("valor", "")
                                mudou_link_81 = lnk != d81.get("link", "")
                                
                                if mudou_opcao_81 or mudou_link_81:
                                        save_resp("8.1", val, float(pts), lnk)
                                        res_data["8.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_81 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_8_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = True

                        c81_1, c81_2 = st.columns([1, 1])
                        with c81_1:
                                v81_atual = st.text_input("Página eletrônica (link):", value=d81.get("valor", ""), key=chave_input_81, on_change=cb_text_8_1)
                                
                                # Cálculo em runtime para exibição imediata do rótulo
                                pts_live_81 = 0.0
                                if v81_atual.strip().upper() == "XYZ":
                                        pts_live_81 = -10.0
                                        txt_score_81 = f"❌ Penalidade Aplicada: {pts_live_81:.1f} pontos (AMF Não Disponível)"
                                        tipo_code_81 = "text"
                                elif not v81_atual.strip():
                                        txt_score_81 = "📊 Pontuação: 0.0 pontos (Aguardando preenchimento)"
                                        tipo_code_81 = "text"
                                else:
                                        txt_score_81 = "✅ Link do Anexo Registrado (Sem penalidades)"
                                        tipo_code_81 = "text"
                                
                        with c81_2:
                                link_8_1 = st.text_area("Link/Evidência (8.1):", value=d81.get("link", ""), key=f"t_8_1_{ano_sel}", on_change=cb_text_8_1, height=100)
                                placeholder_links_81 = st.empty()
                                links_81_visuais = [u[0] for u in re.findall(regex_pure_url, link_8_1 or "")]
                                if links_81_visuais:
                                        placeholder_links_81.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_81_visuais]))
                        
                        st.code(txt_score_81, language=tipo_code_81)
                        bloco_comentarios("8.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_8_1_{ano_sel}", False):
                modal_aviso_link("8.1", st.session_state.get(f"links_pendentes_8_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = False


        # --- QUESITO 8.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_demonstrativos_amf_8_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 8.2 - Demonstrativos Contidos no Anexo de Metas Fiscais", expanded=True):
                        st.subheader("8.2 • Demonstrativos da AMF")
                        st.write("**Assinale os demonstrativos contidos no Anexo de Metas Fiscais:**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        demonstrativos_82 = {
                                "Metas Anuais – 0,7": 0.7,
                                "Avaliação do Cumprimento das Metas Fiscais do Exercício Anterior – 0,7": 0.7,
                                "Metas Fiscais Atuais Comparadas com as Metas Fiscais Fixadas nos três exercícios anteriores – 0,7": 0.7,
                                "Evolução do Patrimônio Líquido – 0,7": 0.7,
                                "Origem e Aplicação dos Recursos Obtidos com a Alienação de Ativos – 00": 0.0,
                                "Avaliação da Situação Financeira e Atuarial do RPPS – 00": 0.0,
                                "Estimativa e Compensação da Renúncia de Receita – 00": 0.0,
                                "Margem de Expansão das Despesas Obrigatórias de Caráter Continuado – 1,2": 1.2,
                                "Outros – 00": 0.0
                        }
                        
                        d82 = res_data.get("8.2", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d82 is None: d82 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_82 = ast.literal_eval(d82.get("valor", "[]"))
                                if not isinstance(lista_salva_82, list): lista_salva_82 = []
                        except Exception:
                                lista_salva_82 = []

                        def cb_check_8_2():
                                sel = []
                                pts = 0.0
                                for idx, (item, pt) in enumerate(demonstrativos_82.items()):
                                        key_chk = f"chk_82_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(item)
                                                pts += pt
                                lnk = st.session_state.get(f"t_8_2_{ano_sel}", d82.get("link", ""))
                                save_resp("8.2", str(sel), float(pts), lnk)
                                res_data["8.2"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}

                        def cb_text_8_2():
                                lnk = st.session_state[f"t_8_2_{ano_sel}"]
                                sel = []
                                pts = 0.0
                                for idx, (item, pt) in enumerate(demonstrativos_82.items()):
                                        key_chk = f"chk_82_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(item)
                                                pts += pt
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d82.get("link", "") or "")]
                                
                                mudou_opcao_82 = str(sel) != d82.get("valor", "[]")
                                mudou_link_82 = lnk != d82.get("link", "")
                                
                                if mudou_opcao_82 or mudou_link_82:
                                        save_resp("8.2", str(sel), float(pts), lnk)
                                        res_data["8.2"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_82 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_8_2_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = True

                        c82_1, c82_2 = st.columns([1, 1])
                        with c82_1:
                                pts_calculados_82 = 0.0
                                for idx, (item, pt) in enumerate(demonstrativos_82.items()):
                                        isChecked = st.checkbox(
                                                item, 
                                                value=item in lista_salva_82, 
                                                key=f"chk_82_{idx}_{ano_sel}",
                                                on_change=cb_check_8_2
                                        )
                                        if isChecked: pts_calculados_82 += pt
                                
                        with c82_2:
                                link_8_2 = st.text_area("Link/Evidência (8.2):", value=d82.get("link", ""), key=f"t_8_2_{ano_sel}", on_change=cb_text_8_2, height=250)
                                placeholder_links_82 = st.empty()
                                links_82_visuais = [u[0] for u in re.findall(regex_pure_url, link_8_2 or "")]
                                if links_82_visuais:
                                        placeholder_links_82.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_82_visuais]))
                        
                        txt_score_82 = f"📊 Pontuação Aplicada no Quesito 8.2: {pts_calculados_82:.2f} pontos"
                        if not lista_salva_82: txt_score_82 += " (Aguardando seleção)"
                                
                        st.code(txt_score_82, language="text")
                        bloco_comentarios("8.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_8_2_{ano_sel}", False):
                modal_aviso_link("8.2", st.session_state.get(f"links_pendentes_8_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = False

        # --- QUESITO 9.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_riscos_fiscais_9_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.0 - Presença do Anexo de Riscos Fiscais na LDO", expanded=True):
                        st.subheader("9.0 • Anexo de Riscos Fiscais")
                        st.write("**O Anexo de Riscos Fiscais integra a Lei de Diretrizes Orçamentárias (LDO), nos termos exigidos pela Lei de Responsabilidade Fiscal?**")
                        st.caption("ℹ *Avalia os passivos contingentes e outros riscos capazes de afetar as contas públicas, informando as providências a serem tomadas, caso se concretizem.*")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_90 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d90 = res_data.get("9.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d90 is None: d90 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_90 = d90.get("valor", "Selecione...")
                        chave_radio_90 = f"r_9_0_{v_salvo_90}_{ano_sel}"

                        def cb_radio_9_0():
                                val = st.session_state[chave_radio_90]
                                lnk = st.session_state.get(f"t_9_0_{ano_sel}", d90.get("link", ""))
                                save_resp("9.0", val, 0.0, lnk)
                                res_data["9.0"] = {"valor": val, "pontos": 0.0, "link": lnk}

                        def cb_text_9_0():
                                lnk = st.session_state[f"t_9_0_{ano_sel}"]
                                val = st.session_state.get(chave_radio_90, d90.get("valor", "Selecione..."))
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d90.get("link", "") or "")]
                                
                                mudou_opcao_90 = val != d90.get("valor", "")
                                mudou_link_90 = lnk != d90.get("link", "")
                                
                                if mudou_opcao_90 or mudou_link_90:
                                        save_resp("9.0", val, 0.0, lnk)
                                        res_data["9.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                        
                                        if mudou_link_90 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_9_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = True

                        c90_1, c90_2 = st.columns([1, 1])
                        with c90_1:
                                lista_opcoes_90 = list(opcoes_90.keys())
                                idx90 = 0
                                if d90.get("valor") in opcoes_90:
                                        idx90 = lista_opcoes_90.index(d90["valor"])
                                        
                                sel_9_0 = st.radio("Selecione 9.0:", options=lista_opcoes_90, index=idx90, key=chave_radio_90, on_change=cb_radio_9_0, label_visibility="collapsed")
                                
                        with c90_2:
                                link_9_0 = st.text_area("Link/Evidência (9.0):", value=d90.get("link", ""), key=f"t_9_0_{ano_sel}", on_change=cb_text_9_0, height=100)
                                placeholder_links_90 = st.empty()
                                links_90_visuais = [u[0] for u in re.findall(regex_pure_url, link_9_0 or "")]
                                if links_90_visuais:
                                        placeholder_links_90.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_90_visuais]))
                        
                        st.code("📊 Impacto de Pontuação no Quesito 9.0: 0.0 pontos", language="text")
                        bloco_comentarios("9.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_9_0_{ano_sel}", False):
                modal_aviso_link("9.0", st.session_state.get(f"links_pendentes_9_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = False


        # --- QUESITO 9.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_url_riscos_9_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.1 - Link Eletrônico do Anexo de Riscos Fiscais", expanded=True):
                        st.subheader("9.1 • URL do Anexo de Riscos Fiscais")
                        st.write("**Informe a página eletrônica (link na internet) de divulgação do Anexo de Riscos Fiscais (XYZ se não disponível):**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        d91 = res_data.get("9.1", {"valor": "", "pontos": 0.0, "link": ""})
                        if d91 is None: d91 = {"valor": "", "pontos": 0.0, "link": ""}
                        
                        chave_input_91 = f"inp_91_{ano_sel}"

                        def cb_text_9_1():
                                val = st.session_state[chave_input_91]
                                lnk = st.session_state.get(f"t_9_1_{ano_sel}", d91.get("link", ""))
                                
                                pts = 0.0
                                if val.strip().upper() == "XYZ":
                                        pts = -10.0
                                        
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d91.get("link", "") or "")]
                                
                                mudou_opcao_91 = val != d91.get("valor", "")
                                mudou_link_91 = lnk != d91.get("link", "")
                                
                                if mudou_opcao_91 or mudou_link_91:
                                        save_resp("9.1", val, float(pts), lnk)
                                        res_data["9.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_91 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_9_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = True

                        c91_1, c91_2 = st.columns([1, 1])
                        with c91_1:
                                v91_atual = st.text_input("Página eletrônica (link):", value=d91.get("valor", ""), key=chave_input_91, on_change=cb_text_9_1)
                                
                                if v91_atual.strip().upper() == "XYZ":
                                        txt_score_91 = "❌ Penalidade Aplicada: -10.0 pontos (Anexo Não Disponível)"
                                elif not v91_atual.strip():
                                        txt_score_91 = "📊 Pontuação: 0.0 pontos (Aguardando preenchimento)"
                                else:
                                        txt_score_91 = "✅ Link do Anexo Informado (Sem penalidades)"
                                
                        with c91_2:
                                link_9_1 = st.text_area("Link/Evidência (9.1):", value=d91.get("link", ""), key=f"t_9_1_{ano_sel}", on_change=cb_text_9_1, height=100)
                                placeholder_links_91 = st.empty()
                                links_91_visuais = [u[0] for u in re.findall(regex_pure_url, link_9_1 or "")]
                                if links_91_visuais:
                                        placeholder_links_91.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_91_visuais]))
                        
                        st.code(txt_score_91, language="text")
                        bloco_comentarios("9.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_9_1_{ano_sel}", False):
                modal_aviso_link("9.1", st.session_state.get(f"links_pendentes_9_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = False


        # --- QUESITO 9.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_etapas_riscos_9_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 9.2 - Etapas para Gerenciamento de Riscos Fiscais", expanded=True):
                        st.subheader("9.2 • Etapas de Gerenciamento da ARF")
                        st.write("**Assinale as etapas para gerenciamento dos riscos contidas no Anexo de Riscos Fiscais:**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        etapas_risco_92 = {
                                "Identificação do tipo de risco e da exposição ao risco – 0,5": 0.5,
                                "Mensuração ou quantificação dessa exposição – 0,5": 0.5,
                                "Estimativa do grau de tolerância das contas públicas ao comportamento frente ao risco – 0,5": 0.5,
                                "Decisão estratégica sobre as opções para enfrentar o risco – 0,5": 0.5,
                                "Implementação de condutas de mitigação do risco e de mecanismos de controle para prevenir perdas decorrentes do risco – 0,5": 0.5,
                                "Monitoramento contínuo da exposição ao longo do tempo, preferencialmente através de sistemas institucionalizados (Controle Interno) – 01": 1.0
                        }
                        
                        d92 = res_data.get("9.2", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d92 is None: d92 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_92 = ast.literal_eval(d92.get("valor", "[]"))
                                if not isinstance(lista_salva_92, list): lista_salva_92 = []
                        except Exception:
                                lista_salva_92 = []

                        def cb_check_9_2():
                                sel = []
                                pts = 0.0
                                for idx, (item, pt) in enumerate(etapas_risco_92.items()):
                                        key_chk = f"chk_92_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(item)
                                                pts += pt
                                lnk = st.session_state.get(f"t_9_2_{ano_sel}", d92.get("link", ""))
                                save_resp("9.2", str(sel), float(pts), lnk)
                                res_data["9.2"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}

                        def cb_text_9_2():
                                lnk = st.session_state[f"t_9_2_{ano_sel}"]
                                sel = []
                                pts = 0.0
                                for idx, (item, pt) in enumerate(etapas_risco_92.items()):
                                        key_chk = f"chk_92_{idx}_{ano_sel}"
                                        if st.session_state.get(key_chk, False):
                                                sel.append(item)
                                                pts += pt
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d92.get("link", "") or "")]
                                
                                mudou_opcao_92 = str(sel) != d92.get("valor", "[]")
                                mudou_link_92 = lnk != d92.get("link", "")
                                
                                if mudou_opcao_92 or mudou_link_92:
                                        save_resp("9.2", str(sel), float(pts), lnk)
                                        res_data["9.2"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_92 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_9_2_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = True

                        c92_1, c92_2 = st.columns([1, 1])
                        with c92_1:
                                pts_calculados_92 = 0.0
                                for idx, (item, pt) in enumerate(etapas_risco_92.items()):
                                        isChecked = st.checkbox(
                                                item, 
                                                value=item in lista_salva_92, 
                                                key=f"chk_92_{idx}_{ano_sel}",
                                                on_change=cb_check_9_2
                                        )
                                        if isChecked: pts_calculados_92 += pt
                                        
                        with c92_2:
                                link_9_2 = st.text_area("Link/Evidência (9.2):", value=d92.get("link", ""), key=f"t_9_2_{ano_sel}", on_change=cb_text_9_2, height=220)
                                placeholder_links_92 = st.empty()
                                links_92_visuais = [u[0] for u in re.findall(regex_pure_url, link_9_2 or "")]
                                if links_92_visuais:
                                        placeholder_links_92.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_92_visuais]))
                                
                        txt_score_92 = f"📊 Pontuação Aplicada no Quesito 9.2: {pts_calculados_92:.2f} pontos"
                        if not lista_salva_92: txt_score_92 += " (Aguardando seleção)"
                                
                        st.code(txt_score_92, language="text")
                        bloco_comentarios("9.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_9_2_{ano_sel}", False):
                modal_aviso_link("9.2", st.session_state.get(f"links_pendentes_9_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = False

        # --- QUESITO 10.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_compatibilidade_10_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 10.0 - Itens de Compatibilidade Orçamentária", expanded=True):
                        st.subheader("10.0 • Compatibilidade LOA x PPA x LDO")
                        st.write("**Assinale os itens capazes de atestar a compatibilidade entre a LOA, PPA e LDO:**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e lógica anulatória.*")
                        
                        compatibilidades_100 = {
                                "Programas constantes do PPA constam na LOA – 01": 1.0,
                                "Programas e ações constantes da LDO constam da LOA – 02": 2.0,
                                "As receitas e despesas da LOA são compatíveis com o Resultado Primário da LDO, incluindo, no máximo, a variação da inflação do interregno temporal dos referidos projetos de lei – 02": 2.0,
                                "O Resultado Nominal constante da LDO consta da LOA, com variação de no máximo a variação da inflação do interregno temporal dos referidos projetos de lei – 02": 2.0,
                                "A estimativa de renúncia fiscal prevista na LDO coincide com o estimado na LOA com variação limitada à variação da inflação – 02": 2.0,
                                "A estimativa de receita e respectivos critérios presentes na LOA são compatíveis com os previstos na LDO em relação à receita de IPTU – 02": 2.0,
                                "A estimativa de receita e respectivos critérios presentes na LOA são compatíveis com os previstos na LDO em relação à receita de ISSQN – 02": 2.0,
                                "A estimativa de receita e respectivos critérios presentes na LOA são compatíveis com os previstos na LDO em relação à receita de ITBI – 02": 2.0,
                                "Os investimentos, parte das despesas de capital, previstas na LOA e LDO are compatíveis com as previsões do PPA – 02": 2.0,
                                "A LDO e a LOA não são compatíveis com o PPA – -10 (perde 10 pontos)": -10.0
                        }
                        
                        d100 = res_data.get("10.0", {"valor": "[]", "pontos": 0.0, "link": ""})
                        if d100 is None: d100 = {"valor": "[]", "pontos": 0.0, "link": ""}

                        try:
                                lista_salva_100 = ast.literal_eval(d100.get("valor", "[]"))
                                if not isinstance(lista_salva_100, list): lista_salva_100 = []
                        except Exception:
                                lista_salva_100 = []

                        def cb_check_10_0():
                                sel = []
                                for idx, (item, pt) in enumerate(compatibilidades_100.items()):
                                        if st.session_state.get(f"chk_100_{idx}_{ano_sel}", False):
                                                sel.append(item)
                                                
                                if any("não são compatíveis" in p for p in sel):
                                        pts = -10.0
                                else:
                                        pts = sum(compatibilidades_100[p] for p in sel)
                                        
                                lnk = st.session_state.get(f"t_10_0_{ano_sel}", d100.get("link", ""))
                                save_resp("10.0", str(sel), float(pts), lnk)
                                res_data["10.0"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}

                        def cb_text_10_0():
                                lnk = st.session_state[f"t_10_0_{ano_sel}"]
                                sel = []
                                for idx, (item, pt) in enumerate(compatibilidades_100.items()):
                                        if st.session_state.get(f"chk_100_{idx}_{ano_sel}", False):
                                                sel.append(item)
                                                
                                if any("não são compatíveis" in p for p in sel):
                                        pts = -10.0
                                else:
                                        pts = sum(compatibilidades_100[p] for p in sel)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d100.get("link", "") or "")]
                                
                                mudou_opcao_100 = str(sel) != d100.get("valor", "[]")
                                mudou_link_100 = lnk != d100.get("link", "")
                                
                                if mudou_opcao_100 or mudou_link_100:
                                        save_resp("10.0", str(sel), float(pts), lnk)
                                        res_data["10.0"] = {"valor": str(sel), "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link_100 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_10_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = True

                        c100_1, c100_2 = st.columns([1, 1])
                        with c100_1:
                                pts_calculados_100 = 0.0
                                flag_anulacao = False
                                
                                for idx, (item, pt) in enumerate(compatibilidades_100.items()):
                                        isChecked = st.checkbox(
                                                item, 
                                                value=item in lista_salva_100, 
                                                key=f"chk_100_{idx}_{ano_sel}",
                                                on_change=cb_check_10_0
                                        )
                                        if isChecked:
                                                if "não são compatíveis" in item:
                                                        flag_anulacao = True
                                                pts_calculados_100 += pt
                                
                                if flag_anulacao:
                                        pts_finais_100 = -10.0
                                        txt_score_100 = f"❌ Penalidade Aplicada no Quesito 10.0: {pts_finais_100:.1f} pontos (Incompatibilidade declarada)"
                                else:
                                        pts_finais_100 = pts_calculados_100
                                        txt_score_100 = f"📊 Pontuação Aplicada no Quesito 10.0: {pts_finais_100:.1f} pontos"
                                        
                        with c100_2:
                                link_100 = st.text_area("Link/Evidência (10.0):", value=d100.get("link", ""), key=f"t_10_0_{ano_sel}", on_change=cb_text_10_0, height=250)
                                placeholder_links_100 = st.empty()
                                links_100_visuais = [u[0] for u in re.findall(regex_pure_url, link_100 or "")]
                                if links_100_visuais:
                                        placeholder_links_100.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_100_visuais]))
                                
                        st.code(txt_score_100, language="text")
                        bloco_comentarios("10.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_10_0_{ano_sel}", False):
                modal_aviso_link("10.0", st.session_state.get(f"links_pendentes_10_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = False


        # --- QUESITO 11.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_creditos_11_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 11.0 - Previsão de Créditos Adicionais por Decreto", expanded=True):
                        st.subheader("11.0 • Créditos Adicionais na LOA")
                        st.write("**Na Lei Orçamentária Anual (LOA), há previsão para abertura de créditos adicionais por decreto?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_110 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d110 = res_data.get("11.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d110 is None: d110 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_110 = d110.get("valor", "Selecione...")
                        chave_radio_110 = f"r_110_{v_salvo_110}_{ano_sel}"

                        def cb_radio_11_0():
                                val = st.session_state[chave_radio_110]
                                lnk = st.session_state.get(f"t_11_0_{ano_sel}", d110.get("link", ""))
                                save_resp("11.0", val, 0.0, lnk)
                                res_data["11.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                if val == "Não":
                                        save_resp("11.1", "0.0|0.0", 0.0, "")
                                        if "11.1" in res_data:
                                                res_data["11.1"] = {"valor": "0.0|0.0", "pontos": 0.0, "link": ""}

                        def cb_text_11_0():
                                lnk = st.session_state[f"t_11_0_{ano_sel}"]
                                val = st.session_state.get(chave_radio_110, d110.get("valor", "Selecione..."))
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d110.get("link", "") or "")]
                                
                                mudou_opcao_110 = val != d110.get("valor", "")
                                mudou_link_110 = lnk != d110.get("link", "")
                                
                                if mudou_opcao_110 or mudou_link_110:
                                        save_resp("11.0", val, 0.0, lnk)
                                        res_data["11.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                        
                                        if mudou_link_110 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_11_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = True

                        c110_1, c110_2 = st.columns([1, 1])
                        with c110_1:
                                lista_opcoes_110 = list(opcoes_110.keys())
                                idx110 = 0
                                if d110.get("valor") in opcoes_110:
                                        idx110 = lista_opcoes_110.index(d110["valor"])
                                        
                                st.radio("Selecione 11.0:", options=lista_opcoes_110, index=idx110, key=chave_radio_110, on_change=cb_radio_11_0, label_visibility="collapsed")
                                
                        with c110_2:
                                link_110 = st.text_area("Link/Evidência (11.0):", value=d110.get("link", ""), key=f"t_11_0_{ano_sel}", on_change=cb_text_11_0, height=100)
                                placeholder_links_110 = st.empty()
                                links_110_visuais = [u[0] for u in re.findall(regex_pure_url, link_110 or "")]
                                if links_110_visuais:
                                        placeholder_links_110.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_110_visuais]))
                        
                        st.code("📊 Impacto de Pontuação no Quesito 11.0: 0.0 pontos", language="text")
                        bloco_comentarios("11.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_11_0_{ano_sel}", False):
                modal_aviso_link("11.0", st.session_state.get(f"links_pendentes_11_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = False

        # --- QUESITO 11.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_suplementar_11_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 11.1 - Percentual Autorizado para Crédito Adicional Suplementar", expanded=True):
                        st.subheader("11.1 • Percentual de Crédito Suplementar")
                        st.write("**Qual o percentual autorizado na Lei Orçamentária Anual (LOA) para abertura de crédito adicional suplementar?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e cálculo matemático comparativo.*")
                        
                        d111 = res_data.get("11.1", {"valor": "0.0|0.0", "pontos": 0.0, "link": ""})
                        if d111 is None: d111 = {"valor": "0.0|0.0", "pontos": 0.0, "link": ""}
                        
                        try:
                                string_valores = d111.get("valor", "0.0|0.0")
                                if "|" not in string_valores: string_valores = f"{string_valores}|0.0"
                                v_loa_salvo, v_inf_salvo = string_valores.split("|")
                                val_loa_inicial = float(v_loa_salvo)
                                val_inf_inicial = float(v_inf_salvo)
                        except Exception:
                                val_loa_inicial = 0.0
                                val_inf_inicial = 0.0

                        chave_num_loa = f"q111_loa_{ano_sel}"
                        chave_num_inf = f"q111_inf_{ano_sel}"
                        chave_text_link = f"t_11_1_{ano_sel}"

                        def cb_processa_mudanca_11_1():
                                v_loa = float(st.session_state.get(chave_num_loa, val_loa_inicial))
                                v_inf = float(st.session_state.get(chave_num_inf, val_inf_inicial))
                                lnk = st.session_state.get(chave_text_link, d111.get("link", ""))
                                
                                # Lógica de negócio e pontuação corporativa
                                if v_loa == 0.0 and v_inf == 0.0:
                                        pts = 0.0
                                else:
                                        pts = 6.0 if v_loa <= v_inf else 0.0
                                        
                                valor_composto = f"{v_loa}|{v_inf}"
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d111.get("link", "") or "")]
                                
                                mudou_campos = valor_composto != d111.get("valor", "0.0|0.0")
                                mudou_link = lnk != d111.get("link", "")
                                
                                if mudou_campos or mudou_link:
                                        save_resp("11.1", valor_composto, float(pts), lnk)
                                        res_data["11.1"] = {"valor": valor_composto, "pontos": float(pts), "link": lnk}
                                        
                                        if mudou_link and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_11_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = True

                        c111_1, c111_2 = st.columns([1, 1])
                        with c111_1:
                                v111_atual = st.number_input("Percentual autorizado na LOA (%):", min_value=0.0, max_value=100.0, value=val_loa_inicial, step=0.01, format="%.2f", key=chave_num_loa, on_change=cb_processa_mudanca_11_1)
                                inf111_atual = st.number_input("Informe a inflação oficial do período (%):", min_value=0.0, max_value=100.0, value=val_inf_inicial, step=0.01, format="%.2f", key=chave_num_inf, on_change=cb_processa_mudanca_11_1)
                                
                                if v111_atual == 0.0 and inf111_atual == 0.0:
                                        txt_score_111 = "📊 Pontuação: 0.0 pontos (Aguardando modificação dos campos)"
                                else:
                                        if v111_atual <= inf111_atual:
                                                txt_score_111 = f"✅ Pontuação: 6.0 pontos (% alteração [{v111_atual:.2f}%] ≤ inflação [{inf111_atual:.2f}%])"
                                        else:
                                                txt_score_111 = f"❌ Pontuação: 0.0 pontos (% alteração [{v111_atual:.2f}%] > inflação [{inf111_atual:.2f}%])"
                                                
                        with c111_2:
                                link_111 = st.text_area("Link/Evidência (11.1):", value=d111.get("link", ""), key=chave_text_link, on_change=cb_processa_mudanca_11_1, height=140)
                                placeholder_links_111 = st.empty()
                                links_111_visuais = [u[0] for u in re.findall(regex_pure_url, link_111 or "")]
                                if links_111_visuais:
                                        placeholder_links_111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_111_visuais]))
                                
                        st.code(txt_score_111, language="text")
                        bloco_comentarios("11.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_11_1_{ano_sel}", False):
                modal_aviso_link("11.1", st.session_state.get(f"links_pendentes_11_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_11_1_{ano_sel}"] = False


        # --- QUESITO 12.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_estrutura_12_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 12.0 - Estrutura Administrativa de Planejamento", expanded=True):
                        st.subheader("12.0 • Estrutura de Planejamento")
                        st.write("**Há estrutura administrativa voltada para planejamento?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e limpeza segura de resíduos.*")
                        
                        opcoes_120 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d120 = res_data.get("12.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d120 is None: d120 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_120 = d120.get("valor", "Selecione...")
                        chave_radio_120 = f"r_120_{v_salvo_120}_{ano_sel}"

                        def cb_radio_12_0():
                                val = st.session_state[chave_radio_120]
                                lnk = st.session_state.get(f"t_120_{ano_sel}", d120.get("link", ""))
                                save_resp("12.0", val, 0.0, lnk)
                                res_data["12.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                # Cascata de limpeza síncrona e segura se alterado para "Não"
                                if val == "Não":
                                        save_resp("12.1", "Não", 0.0, "")
                                        save_resp("12.1.1", "", 0.0, "")
                                        save_resp("12.1.2", "", 0.0, "")
                                        if "12.1" in res_data: res_data["12.1"] = {"valor": "Não", "pontos": 0.0, "link": ""}
                                        if "12.1.1" in res_data: res_data["12.1.1"] = {"valor": "", "pontos": 0.0, "link": ""}
                                        if "12.1.2" in res_data: res_data["12.1.2"] = {"valor": "", "pontos": 0.0, "link": ""}

                        def cb_text_12_0():
                                lnk = st.session_state[f"t_120_{ano_sel}"]
                                val = st.session_state.get(chave_radio_120, d120.get("valor", "Selecione..."))
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d120.get("link", "") or "")]
                                
                                mudou_opcao_120 = val != d120.get("valor", "")
                                mudou_link_120 = lnk != d120.get("link", "")
                                
                                if mudou_opcao_120 or mudou_link_120:
                                        save_resp("12.0", val, 0.0, lnk)
                                        res_data["12.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                        
                                        if mudou_link_120 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_12_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = True

                        c120_1, c120_2 = st.columns([1, 1])
                        with c120_1:
                                lista_opcoes_120 = list(opcoes_120.keys())
                                idx120 = 0
                                if d120.get("valor") in opcoes_120:
                                        idx120 = lista_opcoes_120.index(d120["valor"])
                                        
                                st.radio("Selecione 12.0:", options=lista_opcoes_120, index=idx120, key=chave_radio_120, on_change=cb_radio_12_0, label_visibility="collapsed")
                                
                        with c120_2:
                                link_120 = st.text_area("Link/Evidência (12.0):", value=d120.get("link", ""), key=f"t_120_{ano_sel}", on_change=cb_text_12_0, height=100)
                                placeholder_links_120 = st.empty()
                                links_120_visuais = [u[0] for u in re.findall(regex_pure_url, link_120 or "")]
                                if links_120_visuais:
                                        placeholder_links_120.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_120_visuais]))
                        
                        st.code("📊 Impacto de Pontuação no Quesito 12.0: 0.0 pontos", language="text")
                        bloco_comentarios("12.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_12_0_{ano_sel}", False):
                modal_aviso_link("12.0", st.session_state.get(f"links_pendentes_12_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = False


        # --- QUESITO 12.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_rh_planejamento_12_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 12.1 - Recursos Humanos para Atividades de Planejamento", expanded=True):
                        st.subheader("12.1 • RH de Planejamento")
                        st.write("**A prefeitura dispõe de recursos humanos para operacionalização das atividades de planejamento?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e cascata de limpeza para subníveis.*")
                        
                        opcoes_121 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d121 = res_data.get("12.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d121 is None: d121 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_121 = d121.get("valor", "Selecione...")
                        chave_radio_121 = f"r_121_{v_salvo_121}_{ano_sel}"

                        def cb_radio_12_1():
                                val = st.session_state[chave_radio_121]
                                lnk = st.session_state.get(f"t_121_{ano_sel}", d121.get("link", ""))
                                save_resp("12.1", val, 0.0, lnk)
                                res_data["12.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                # Limpeza em cascata dos subníveis inferiores caso selecionado "Não"
                                if val == "Não":
                                        save_resp("12.1.1", "", 0.0, "")
                                        save_resp("12.1.2", "", 0.0, "")
                                        if "12.1.1" in res_data: res_data["12.1.1"] = {"valor": "", "pontos": 0.0, "link": ""}
                                        if "12.1.2" in res_data: res_data["12.1.2"] = {"valor": "", "pontos": 0.0, "link": ""}

                        def cb_text_12_1():
                                lnk = st.session_state[f"t_121_{ano_sel}"]
                                val = st.session_state.get(chave_radio_121, d121.get("valor", "Selecione..."))
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d121.get("link", "") or "")]
                                
                                mudou_opcao_121 = val != d121.get("valor", "")
                                mudou_link_121 = lnk != d121.get("link", "")
                                
                                if mudou_opcao_121 or mudou_link_121:
                                        save_resp("12.1", val, 0.0, lnk)
                                        res_data["12.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                        
                                        if mudou_link_121 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_12_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = True

                        c121_1, c121_2 = st.columns([1, 1])
                        with c121_1:
                                lista_opcoes_121 = list(opcoes_121.keys())
                                idx121 = 0
                                if d121.get("valor") in opcoes_121:
                                        idx121 = lista_opcoes_121.index(d121["valor"])
                                        
                                st.radio("Selecione 12.1:", options=lista_opcoes_121, index=idx121, key=chave_radio_121, on_change=cb_radio_12_1, label_visibility="collapsed")
                                
                        with c121_2:
                                link_121 = st.text_area("Link/Evidência (12.1):", value=d121.get("link", ""), key=f"t_121_{ano_sel}", on_change=cb_text_12_1, height=100)
                                placeholder_links_121 = st.empty()
                                links_121_visuais = [u[0] for u in re.findall(regex_pure_url, link_121 or "")]
                                if links_121_visuais:
                                        placeholder_links_121.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_121_visuais]))
                                        
                        st.code("📊 Impacto de Pontuação no Quesito 12.1: 0.0 pontos", language="text")
                        bloco_comentarios("12.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_12_1_{ano_sel}", False):
                modal_aviso_link("12.1", st.session_state.get(f"links_pendentes_12_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = False
 
        # --- QUESITO 12.1.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_rh_planejamento_12_1_1_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 12.1.1 - Qualificação Técnica da Equipe de Planejamento", expanded=True):
                        st.subheader("12.1.1 • Qualificação da Equipe")
                        st.write("**Os servidores da equipe de planejamento possuem qualificação técnica para o exercício das atividades de planejamento, gestão e orçamento?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_1211 = {
                                "Selecione...": 0.0,
                                "Sim, todos os servidores possuem qualificação técnica – 00": 0.0,
                                "Sim, a maior parte dos servidores possuem qualificação técnica – -05 (perde 05 pontos)": -5.0,
                                "Sim, a menor parte dos servidores possuem qualificação técnica – -08 (perde 08 pontos)": -8.0,
                                "Não – -10 (perde 10 pontos)": -10.0
                        }
                        
                        d1211 = res_data.get("12.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d1211 is None: d1211 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_1211 = d1211.get("valor", "Selecione...")
                        chave_radio_1211 = f"r_1211_{v_salvo_1211}_{ano_sel}"

                        def cb_radio_12_1_1():
                                val = st.session_state[chave_radio_1211]
                                pts = opcoes_1211.get(val, 0.0)
                                lnk = st.session_state.get(f"t_1211_{ano_sel}", d1211.get("link", ""))
                                save_resp("12.1.1", val, pts, lnk)
                                res_data["12.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_12_1_1():
                                lnk = st.session_state[f"t_1211_{ano_sel}"]
                                val = st.session_state.get(chave_radio_1211, d1211.get("valor", "Selecione..."))
                                pts = opcoes_1211.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d1211.get("link", "") or "")]
                                
                                mudou_opcao_1211 = val != d1211.get("valor", "")
                                mudou_link_1211 = lnk != d1211.get("link", "")
                                
                                if mudou_opcao_1211 or mudou_link_1211:
                                        save_resp("12.1.1", val, pts, lnk)
                                        res_data["12.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_1211 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_12_1_1_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_12_1_1_{ano_sel}"] = True

                        c1211_1, c1211_2 = st.columns([1, 1])
                        with c1211_1:
                                lista_opcoes_1211 = list(opcoes_1211.keys())
                                idx1211 = 0
                                if d1211.get("valor") in opcoes_1211:
                                        idx1211 = lista_opcoes_1211.index(d1211["valor"])
                                        
                                st.radio("Selecione 12.1.1:", options=lista_opcoes_1211, index=idx1211, key=chave_radio_1211, on_change=cb_radio_12_1_1, label_visibility="collapsed")
                                
                        with c1211_2:
                                link_1211 = st.text_area("Link/Evidência (12.1.1):", value=d1211.get("link", ""), key=f"t_1211_{ano_sel}", on_change=cb_text_12_1_1, height=100)
                                placeholder_links_1211 = st.empty()
                                links_1211_visuais = [u[0] for u in re.findall(regex_pure_url, link_1211 or "")]
                                if links_1211_visuais:
                                        placeholder_links_1211.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1211_visuais]))
                                        
                        ponto_atual = d1211.get("pontos", 0.0)
                        st.code(f"📊 Impacto de Pontuação no Quesito 12.1.1: {ponto_atual} pontos", language="text")
                        bloco_comentarios("12.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_12_1_1_{ano_sel}", False):
                modal_aviso_link("12.1.1", st.session_state.get(f"links_pendentes_12_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_12_1_1_{ano_sel}"] = False

# --- QUESITO 12.1.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_rh_planejamento_12_1_2_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 12.1.2 - Treinamento Periódico para Planejamento", expanded=True):
                        st.subheader("12.1.2 • Treinamento de Servidores")
                        st.write("**Os servidores responsáveis pelo planejamento recebem treinamento específico para a matéria? Treinamento periódico pelo menos 1 vez ao ano.**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                        
                        opcoes_1212 = {
                                "Selecione...": 0.0,
                                "Sim – 00": 0.0,
                                "Não – -10 (perde 10 pontos)": -10.0
                        }
                        
                        d1212 = res_data.get("12.1.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d1212 is None: d1212 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_1212 = d1212.get("valor", "Selecione...")
                        chave_radio_1212 = f"r_1212_{v_salvo_1212}_{ano_sel}"

                        def cb_radio_12_1_2():
                                val = st.session_state[chave_radio_1212]
                                pts = opcoes_1212.get(val, 0.0)
                                lnk = st.session_state.get(f"t_1212_{ano_sel}", d1212.get("link", ""))
                                save_resp("12.1.2", val, pts, lnk)
                                res_data["12.1.2"] = {"valor": val, "pontos": pts, "link": lnk}

                        def cb_text_12_1_2():
                                lnk = st.session_state[f"t_1212_{ano_sel}"]
                                val = st.session_state.get(chave_radio_1212, d1212.get("valor", "Selecione..."))
                                pts = opcoes_1212.get(val, 0.0)
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d1212.get("link", "") or "")]
                                
                                mudou_opcao_1212 = val != d1212.get("valor", "")
                                mudou_link_1212 = lnk != d1212.get("link", "")
                                
                                if mudou_opcao_1212 or mudou_link_1212:
                                        save_resp("12.1.2", val, pts, lnk)
                                        res_data["12.1.2"] = {"valor": val, "pontos": pts, "link": lnk}
                                        
                                        if mudou_link_1212 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_12_1_2_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = True

                        c1212_1, c1212_2 = st.columns([1, 1])
                        with c1212_1:
                                lista_opcoes_1212 = list(opcoes_1212.keys())
                                idx1212 = 0
                                if d1212.get("valor") in opcoes_1212:
                                        idx1212 = lista_opcoes_1212.index(d1212["valor"])
                                        
                                st.radio("Selecione 12.1.2:", options=lista_opcoes_1212, index=idx1212, key=chave_radio_1212, on_change=cb_radio_12_1_2, label_visibility="collapsed")
                                
                        with c1212_2:
                                link_1212 = st.text_area("Link/Evidência (12.1.2):", value=d1212.get("link", ""), key=f"t_1212_{ano_sel}", on_change=cb_text_12_1_2, height=100)
                                placeholder_links_1212 = st.empty()
                                links_1212_visuais = [u[0] for u in re.findall(regex_pure_url, link_1212 or "")]
                                if links_1212_visuais:
                                        placeholder_links_1212.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1212_visuais]))
                                        
                        ponto_atual = d1212.get("pontos", 0.0)
                        st.code(f"📊 Impacto de Pontuação no Quesito 12.1.2: {ponto_atual} pontos", language="text")
                        bloco_comentarios("12.1.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_12_1_2_{ano_sel}", False):
                modal_aviso_link("12.1.2", st.session_state.get(f"links_pendentes_12_1_2_{ano_sel}", []))
                st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = False


        # --- QUESITO 13.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_acompanhamento_13_0_final_{ano_sel}", border=True):
                with st.expander(f"📌 Quesito 13.0 - Acompanhamento da Execução do Planejamento", expanded=True):
                        st.subheader("13.0 • Acompanhamento da Execução")
                        st.write("**Há acompanhamento da execução do planejamento?**")
                        st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e cascata de limpeza para subníveis.*")
                        
                        opcoes_130 = {
                                "Selecione...": 0.0,
                                "Sim": 0.0,
                                "Não": 0.0
                        }
                        
                        d130 = res_data.get("13.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                        if d130 is None: d130 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                        v_salvo_130 = d130.get("valor", "Selecione...")
                        chave_radio_130 = f"r_130_{v_salvo_130}_{ano_sel}"

                        def cb_radio_13_0():
                                val = st.session_state[chave_radio_130]
                                lnk = st.session_state.get(f"t_130_{ano_sel}", d130.get("link", ""))
                                save_resp("13.0", val, 0.0, lnk)
                                res_data["13.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                
                                # Limpeza em cascata dos subníveis inferiores caso selecionado "Não"
                                if val == "Não":
                                        save_resp("13.1", "[]", 0.0, "")
                                        save_resp("13.1.1", "[]", 0.0, "")
                                        save_resp("13.1.1.1", "", 0.0, "")
                                        if "13.1" in res_data: res_data["13.1"] = {"valor": "[]", "pontos": 0.0, "link": ""}
                                        if "13.1.1" in res_data: res_data["13.1.1"] = {"valor": "[]", "pontos": 0.0, "link": ""}
                                        if "13.1.1.1" in res_data: res_data["13.1.1.1"] = {"valor": "", "pontos": 0.0, "link": ""}

                        def cb_text_13_0():
                                lnk = st.session_state[f"t_130_{ano_sel}"]
                                val = st.session_state.get(chave_radio_130, d130.get("valor", "Selecione..."))
                                
                                links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                                links_antigos = [u[0] for u in re.findall(regex_pure_url, d130.get("link", "") or "")]
                                
                                mudou_opcao_130 = val != d130.get("valor", "")
                                mudou_link_130 = lnk != d130.get("link", "")
                                
                                if mudou_opcao_130 or mudou_link_130:
                                        save_resp("13.0", val, 0.0, lnk)
                                        res_data["13.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                                        
                                        if mudou_link_130 and links_atuais:
                                                if links_atuais != links_antigos:
                                                        st.session_state[f"links_pendentes_13_0_{ano_sel}"] = links_atuais
                                                        st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = True

                        c130_1, c130_2 = st.columns([1, 1])
                        with c130_1:
                                lista_opcoes_130 = list(opcoes_130.keys())
                                idx130 = 0
                                if d130.get("valor") in opcoes_130:
                                        idx130 = lista_opcoes_130.index(d130["valor"])
                                        
                                st.radio("Selecione 13.0:", options=lista_opcoes_130, index=idx130, key=chave_radio_130, on_change=cb_radio_13_0, label_visibility="collapsed")
                                
                        with c130_2:
                                link_130 = st.text_area("Link/Evidência (13.0):", value=d130.get("link", ""), key=f"t_130_{ano_sel}", on_change=cb_text_13_0, height=100)
                                placeholder_links_130 = st.empty()
                                links_130_visuais = [u[0] for u in re.findall(regex_pure_url, link_130 or "")]
                                if links_130_visuais:
                                        placeholder_links_130.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_130_visuais]))
                                        
                        st.code("📊 Impacto de Pontuação no Quesito 13.0: 0.0 pontos", language="text")
                        bloco_comentarios("13.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_13_0_{ano_sel}", False):
                modal_aviso_link("13.0", st.session_state.get(f"links_pendentes_13_0_{ano_sel}", []))
                st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = False

        # --- QUESITO 13.1 • MULTI-CHECKBOX INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_metas_fiscais_13_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.1 - Audiências Públicas de Metas Fiscais", expanded=True):
                st.subheader("13.1 • Metas Fiscais e Audiências")
                st.write("**A prefeitura demonstra e avalia, com periodicidade quadrimestral, o cumprimento das metas fiscais em audiências públicas?** *(Art. 9º, § 4º, da LRF)*")
                st.caption("ℹ *Salvamento automático por ações interativas de estado e validação de link.*")
                
                opc131 = {
                    "Realizou Audiência pública do 1º Quadrimestre até o final do mês de maio de 2025 – 02": 2.0,
                    "Realizou Audiência pública do 2º Quadrimestre até o final do mês de setembro de 2025 – 02": 2.0,
                    "Realizou Audiência pública do 3º Quadrimestre até o final do mês de fevereiro de 2026 – 02": 2.0,
                    "Não realizou audiência pública quadrimestral dentro do prazo – 00": 0.0,
                    "Não realizou nenhuma audiência pública quadrimestral na Câmara Municipal – -10 (perde 10 pontos)": -10.0
                }
                
                d131 = res_data.get("13.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d131 is None: d131 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_131 = ast.literal_eval(d131.get("valor", "[]"))
                    if not isinstance(lista_salva_131, list): lista_salva_131 = []
                except Exception:
                    lista_salva_131 = []

                c131_1, c131_2 = st.columns([1, 1])
                with c131_1:
                    sel131 = []
                    mudou_check_131 = False
                    
                    for idx, (opt, pt) in enumerate(opc131.items()):
                        v_antigo = opt in lista_salva_131
                        v_novo = st.checkbox(opt, value=v_antigo, key=f"ck_131_opt_{idx}_{ano_sel}")
                        if v_novo:
                            sel131.append(opt)
                        if v_novo != v_antigo:
                            mudou_check_131 = True
                            
                    if any("Não realizou nenhuma" in p for p in sel131):
                        pts131 = -10.0
                    elif any("dentro do prazo" in p for p in sel131):
                        pts131 = 0.0
                    else:
                        pts131 = sum(opc131[p] for p in sel131)

                with c131_2:
                    def cb_text_13_1():
                        lnk = st.session_state[f"t_131_{ano_sel}"]
                        links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                        links_antigos = [u[0] for u in re.findall(regex_pure_url, d131.get("link", "") or "")]
                        
                        save_resp("13.1", str(sel131), pts131, lnk)
                        res_data["13.1"] = {"valor": str(sel131), "pontos": pts131, "link": lnk}
                        
                        if lnk != d131.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_13_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = True
                    
                    link_131 = st.text_area("Link/Evidência (13.1):", value=d131.get("link", ""), key=f"t_131_{ano_sel}", on_change=cb_text_13_1, height=130)
                    placeholder_links_131 = st.empty()
                    links_131_visuais = [u[0] for u in re.findall(regex_pure_url, link_131 or "")]
                    if links_131_visuais:
                        placeholder_links_131.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_131_visuais]))

                if mudou_check_131:
                    save_resp("13.1", str(sel131), pts131, link_131)
                    res_data["13.1"] = {"valor": str(sel131), "pontos": pts131, "link": link_131}
                    st.rerun()

                st.code(f"📊 Impacto de Pontuação no Quesito 13.1: {pts131} pontos", language="text")
                bloco_comentarios("13.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_13_1_{ano_sel}", False):
            modal_aviso_link("13.1", st.session_state.get(f"links_pendentes_13_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = False


        # --- QUESITO 13.1.1 • MULTI-CHECKBOX INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_relatorios_13_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.1.1 - Elaboração de Relatórios Quadrimestrais", expanded=True):
                st.subheader("13.1.1 • Relatórios Quadrimestrais")
                st.write("**Foram elaborados os Relatórios Quadrimestrais das metas fiscais para as audiências públicas?**")
                st.caption("ℹ *Salvamento automático por ações interativas de estado e validação de link.*")
                
                opc1311 = {
                    "Relatório da Audiência pública do 1º Quadrimestre – 01": 1.0,
                    "Relatório da Audiência pública do 2º Quadrimestre – 01": 1.0,
                    "Relatório da Audiência pública do 3º Quadrimestre – 01": 1.0,
                    "Não elaborou relatório de nenhuma audiência pública quadrimestral – 00": 0.0
                }
                
                d1311 = res_data.get("13.1.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d1311 is None: d1311 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_1311 = ast.literal_eval(d1311.get("valor", "[]"))
                    if not isinstance(lista_salva_1311, list): lista_salva_1311 = []
                except Exception:
                    lista_salva_1311 = []

                c1311_1, c1311_2 = st.columns([1, 1])
                with c1311_1:
                    sel1311 = []
                    mudou_check_1311 = False
                    
                    for idx, (opt, pt) in enumerate(opc1311.items()):
                        v_antigo = opt in lista_salva_1311
                        v_novo = st.checkbox(opt, value=v_antigo, key=f"ck_1311_opt_{idx}_{ano_sel}")
                        if v_novo:
                            sel1311.append(opt)
                        if v_novo != v_antigo:
                            mudou_check_1311 = True
                            
                    if any("Não elaborou" in p for p in sel1311):
                        pts1311 = 0.0
                    else:
                        pts1311 = sum(opc1311[p] for p in sel1311)

                with c1311_2:
                    def cb_text_13_1_1():
                        lnk = st.session_state[f"t_1311_{ano_sel}"]
                        links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                        links_antigos = [u[0] for u in re.findall(regex_pure_url, d1311.get("link", "") or "")]
                        
                        save_resp("13.1.1", str(sel1311), pts1311, lnk)
                        res_data["13.1.1"] = {"valor": str(sel1311), "pontos": pts1311, "link": lnk}
                        
                        if lnk != d1311.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_13_1_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_13_1_1_{ano_sel}"] = True
                    
                    link_1311 = st.text_area("Link/Evidência (13.1.1):", value=d1311.get("link", ""), key=f"t_1311_{ano_sel}", on_change=cb_text_13_1_1, height=130)
                    placeholder_links_1311 = st.empty()
                    links_1311_visuais = [u[0] for u in re.findall(regex_pure_url, link_1311 or "")]
                    if links_1311_visuais:
                        placeholder_links_1311.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1311_visuais]))

                if mudou_check_1311:
                    save_resp("13.1.1", str(sel1311), pts1311, link_1311)
                    res_data["13.1.1"] = {"valor": str(sel1311), "pontos": pts1311, "link": link_1311}
                    st.rerun()

                st.code(f"📊 Impacto de Pontuação no Quesito 13.1.1: {pts1311} points", language="text")
                bloco_comentarios("13.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_13_1_1_{ano_sel}", False):
            modal_aviso_link("13.1.1", st.session_state.get(f"links_pendentes_13_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_1_1_{ano_sel}"] = False


        # --- QUESITO 13.1.1.1 • INPUT TEXT INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_url_divulgacao_13_1_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.1.1.1 - Página Eletrônica de Divulgação", expanded=True):
                st.subheader("13.1.1.1 • URL de Divulgação")
                st.write("**Informe a página eletrônica (link na internet) de divulgação dos Relatórios Quadrimestrais de Metas Fiscais:** *(Insira XYZ se indisponível)*")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                d13111 = res_data.get("13.1.1.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d13111 is None: d13111 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_input_13_1_1_1():
                    v_input = st.session_state[f"i_13111_{ano_sel}"]
                    pts = 2.0 if v_input.strip() and v_input.strip().upper() != "XYZ" else 0.0
                    lnk = st.session_state.get(f"t_13111_{ano_sel}", d13111.get("link", ""))
                    save_resp("13.1.1.1", v_input, pts, lnk)
                    res_data["13.1.1.1"] = {"valor": v_input, "pontos": pts, "link": lnk}

                def cb_text_13_1_1_1():
                    lnk = st.session_state[f"t_13111_{ano_sel}"]
                    v_input = st.session_state.get(f"i_13111_{ano_sel}", d13111.get("valor", ""))
                    pts = 2.0 if v_input.strip() and v_input.strip().upper() != "XYZ" else 0.0
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d13111.get("link", "") or "")]
                    
                    mudou_val = v_input != d13111.get("valor", "")
                    mudou_lnk = lnk != d13111.get("link", "")
                    
                    if mudou_val or mudou_lnk:
                        save_resp("13.1.1.1", v_input, pts, lnk)
                        res_data["13.1.1.1"] = {"valor": v_input, "pontos": pts, "link": lnk}
                        
                        if mudou_lnk and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_13_1_1_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_13_1_1_1_{ano_sel}"] = True

                c13111_1, c13111_2 = st.columns([1, 1])
                with c13111_1:
                    st.text_input("Link URL (Relatórios):", value=d13111.get("valor", ""), key=f"i_13111_{ano_sel}", on_change=cb_input_13_1_1_1)
                    
                with c13111_2:
                    link_13111 = st.text_area("Link/Evidência (13.1.1.1):", value=d13111.get("link", ""), key=f"t_13111_{ano_sel}", on_change=cb_text_13_1_1_1, height=100)
                    placeholder_links_13111 = st.empty()
                    links_13111_visuais = [u[0] for u in re.findall(regex_pure_url, link_13111 or "")]
                    if links_13111_visuais:
                        placeholder_links_13111.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_13111_visuais]))
                        
                ponto_atual = d13111.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 13.1.1.1: {ponto_atual} pontos", language="text")
                bloco_comentarios("13.1.1.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_13_1_1_1_{ano_sel}", False):
            modal_aviso_link("13.1.1.1", st.session_state.get(f"links_pendentes_13_1_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_1_1_1_{ano_sel}"] = False

# --- QUESITO 13.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_acompanhamento_13_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.2 - Acompanhamento Mensal com Participação do Prefeito", expanded=True):
                st.subheader("13.2 • Acompanhamento Mensal")
                st.write("**Houve acompanhamento mensal da execução orçamentária com participação do Prefeito?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes_132 = {
                    "Selecione...": 0.0,
                    "Sim – 04": 4.0,
                    "Não – 00": 0.0
                }
                
                d132 = res_data.get("13.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d132 is None: d132 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_132 = d132.get("valor", "Selecione...")
                chave_radio_132 = f"r_132_{v_salvo_132}_{ano_sel}"

                def cb_radio_13_2():
                    val = st.session_state[chave_radio_132]
                    pts = opcoes_132.get(val, 0.0)
                    lnk = st.session_state.get(f"t_132_{ano_sel}", d132.get("link", ""))
                    save_resp("13.2", val, pts, lnk)
                    res_data["13.2"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_13_2():
                    lnk = st.session_state[f"t_132_{ano_sel}"]
                    val = st.session_state.get(chave_radio_132, d132.get("valor", "Selecione..."))
                    pts = opcoes_132.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d132.get("link", "") or "")]
                    
                    if val != d132.get("valor", "") or lnk != d132.get("link", ""):
                        save_resp("13.2", val, pts, lnk)
                        res_data["13.2"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d132.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_13_2_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_13_2_{ano_sel}"] = True

                c132_1, c132_2 = st.columns([1, 1])
                with c132_1:
                    lista_opcoes_132 = list(opcoes_132.keys())
                    idx132 = lista_opcoes_132.index(d132.get("valor")) if d132.get("valor") in opcoes_132 else 0
                    st.radio("Selecione 13.2:", options=lista_opcoes_132, index=idx132, key=chave_radio_132, on_change=cb_radio_13_2, label_visibility="collapsed")
                    
                with c132_2:
                    link_132 = st.text_area("Link/Evidência (13.2):", value=d132.get("link", ""), key=f"t_132_{ano_sel}", on_change=cb_text_13_2, height=100)
                    placeholder_links_132 = st.empty()
                    links_132_visuais = [u[0] for u in re.findall(regex_pure_url, link_132 or "")]
                    if links_132_visuais:
                        placeholder_links_132.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_132_visuais]))
                        
                pts_atuais_132 = d132.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 13.2: {pts_atuais_132} pontos", language="text")
                bloco_comentarios("13.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_13_2_{ano_sel}", False):
            modal_aviso_link("13.2", st.session_state.get(f"links_pendentes_13_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_2_{ano_sel}"] = False


        # --- QUESITO 13.3 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_retroalimentacao_13_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 13.3 - Retroalimentação do Replanejamento Orçamentário", expanded=True):
                st.subheader("13.3 • Retroalimentação para o Replanejamento")
                st.write("**O acompanhamento e avaliação da execução orçamentária serve de retroalimentação para o replanejamento dos programas e metas das peças orçamentárias?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes_133 = {
                    "Selecione...": 0.0,
                    "Sim, com emissão de relatórios e ciência do prefeito – 20": 20.0,
                    "Sim, com emissão de relatório e sem ciência do prefeito – 10": 10.0,
                    "Sim, sem emissão de relatório e sem ciência do prefeito – 05": 5.0,
                    "Não – 00": 0.0
                }
                
                d133 = res_data.get("13.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d133 is None: d133 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_133 = d133.get("valor", "Selecione...")
                chave_radio_133 = f"r_133_{v_salvo_133}_{ano_sel}"

                def cb_radio_13_3():
                    val = st.session_state[chave_radio_133]
                    pts = opcoes_133.get(val, 0.0)
                    lnk = st.session_state.get(f"t_133_{ano_sel}", d133.get("link", ""))
                    save_resp("13.3", val, pts, lnk)
                    res_data["13.3"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_13_3():
                    lnk = st.session_state[f"t_133_{ano_sel}"]
                    val = st.session_state.get(chave_radio_133, d133.get("valor", "Selecione..."))
                    pts = opcoes_133.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d133.get("link", "") or "")]
                    
                    if val != d133.get("valor", "") or lnk != d133.get("link", ""):
                        save_resp("13.3", val, pts, lnk)
                        res_data["13.3"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d133.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_13_3_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_13_3_{ano_sel}"] = True

                c133_1, c133_2 = st.columns([1, 1])
                with c133_1:
                    lista_opcoes_133 = list(opcoes_133.keys())
                    idx133 = lista_opcoes_133.index(d133.get("valor")) if d133.get("valor") in opcoes_133 else 0
                    st.radio("Selecione 13.3:", options=lista_opcoes_133, index=idx133, key=chave_radio_133, on_change=cb_radio_13_3, label_visibility="collapsed")
                    
                with c133_2:
                    link_133 = st.text_area("Link/Evidência (13.3):", value=d133.get("link", ""), key=f"t_133_{ano_sel}", on_change=cb_text_13_3, height=120)
                    placeholder_links_133 = st.empty()
                    links_133_visuais = [u[0] for u in re.findall(regex_pure_url, link_133 or "")]
                    if links_133_visuais:
                        placeholder_links_133.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_133_visuais]))
                        
                pts_atuais_133 = d133.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 13.3: {pts_atuais_133} pontos", language="text")
                bloco_comentarios("13.3", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_13_3_{ano_sel}", False):
            modal_aviso_link("13.3", st.session_state.get(f"links_pendentes_13_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_13_3_{ano_sel}"] = False


        # =============================================================================
        # SEÇÃO 14: SISTEMA DE CONTROLE INTERNO
        # =============================================================================

        # --- QUESITO 14.0 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_controle_interno_14_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.0 - Instituição e Regulamentação do Sistema de Controle Interno", expanded=True):
                st.subheader("14.0 • Sistema de Controle Interno")
                st.write("**Houve a instituição e regulamentação das operações do Sistema de Controle Interno?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes_140 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                
                d140 = res_data.get("14.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d140 is None: d140 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_140 = d140.get("valor", "Selecione...")
                chave_radio_140 = f"r_140_{v_salvo_140}_{ano_sel}"

                def cb_radio_14_0():
                    val = st.session_state[chave_radio_140]
                    lnk = st.session_state.get(f"t_140_{ano_sel}", d140.get("link", ""))
                    save_resp("14.0", val, 0.0, lnk)
                    res_data["14.0"] = {"valor": val, "pontos": 0.0, "link": lnk}

                def cb_text_14_0():
                    lnk = st.session_state[f"t_140_{ano_sel}"]
                    val = st.session_state.get(chave_radio_140, d140.get("valor", "Selecione..."))
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d140.get("link", "") or "")]
                    
                    if val != d140.get("valor", "") or lnk != d140.get("link", ""):
                        save_resp("14.0", val, 0.0, lnk)
                        res_data["14.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                        
                        if lnk != d140.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_0_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = True

                c140_1, c140_2 = st.columns([1, 1])
                with c140_1:
                    lista_opcoes_140 = list(opcoes_140.keys())
                    idx140 = lista_opcoes_140.index(d140.get("valor")) if d140.get("valor") in opcoes_140 else 0
                    st.radio("Selecione 14.0:", options=lista_opcoes_140, index=idx140, key=chave_radio_140, on_change=cb_radio_14_0, label_visibility="collapsed")
                    
                with c140_2:
                    link_140 = st.text_area("Link/Evidência (14.0):", value=d140.get("link", ""), key=f"t_140_{ano_sel}", on_change=cb_text_14_0, height=100)
                    placeholder_links_140 = st.empty()
                    links_140_visuais = [u[0] for u in re.findall(regex_pure_url, link_140 or "")]
                    if links_140_visuais:
                        placeholder_links_140.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_140_visuais]))
                        
                st.code("📊 Impacto de Pontuação no Quesito 14.0: 0.0 pontos", language="text")
                bloco_comentarios("14.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_0_{ano_sel}", False):
            modal_aviso_link("14.0", st.session_state.get(f"links_pendentes_14_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = False

# --- QUESITO 14.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_regulamentacao_14_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.1 - Instrumento Normativo de Regulamentação", expanded=True):
                st.subheader("14.1 • Instrumento Normativo")
                st.write("**Informe o instrumento normativo de regulamentação do Sistema de Controle Interno, Número e Data da publicação:**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                d141 = res_data.get("14.1", {"valor": "||", "pontos": 0.0, "link": ""})
                if d141 is None: d141 = {"valor": "||", "pontos": 0.0, "link": ""}
                
                try:
                    partes_141 = d141["valor"].split("|")
                    inst_inicial = partes_141[0] if len(partes_141) > 0 else ""
                    num_inicial = partes_141[1] if len(partes_141) > 1 else ""
                    data_inicial = partes_141[2] if len(partes_141) > 2 else ""
                except Exception:
                    inst_inicial, num_inicial, data_inicial = "", "", ""

                def cb_input_14_1():
                    v_inst = st.session_state[f"q141_inst_{ano_sel}"]
                    v_num = st.session_state[f"q141_num_{ano_sel}"]
                    v_data = st.session_state[f"q141_data_{ano_sel}"]
                    valor_composto = f"{v_inst}|{v_num}|{v_data}"
                    lnk = st.session_state.get(f"t_141_{ano_sel}", d141.get("link", ""))
                    save_resp("14.1", valor_composto, 0.0, lnk)
                    res_data["14.1"] = {"valor": valor_composto, "pontos": 0.0, "link": lnk}

                def cb_text_14_1():
                    lnk = st.session_state[f"t_141_{ano_sel}"]
                    v_inst = st.session_state.get(f"q141_inst_{ano_sel}", inst_inicial)
                    v_num = st.session_state.get(f"q141_num_{ano_sel}", num_inicial)
                    v_data = st.session_state.get(f"q141_data_{ano_sel}", data_inicial)
                    valor_composto = f"{v_inst}|{v_num}|{v_data}"
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d141.get("link", "") or "")]
                    
                    if valor_composto != d141.get("valor", "") or lnk != d141.get("link", ""):
                        save_resp("14.1", valor_composto, 0.0, lnk)
                        res_data["14.1"] = {"valor": valor_composto, "pontos": 0.0, "link": lnk}
                        
                        if lnk != d141.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = True

                c141_1, c141_2 = st.columns([1, 1])
                with c141_1:
                    st.text_input("Instrumento Normativo (Ex: Lei, Decreto):", value=inst_inicial, key=f"q141_inst_{ano_sel}", on_change=cb_input_14_1)
                    st.text_input("Número do instrumento:", value=num_inicial, key=f"q141_num_{ano_sel}", on_change=cb_input_14_1)
                    st.text_input("Data da publicação (DD/MM/AAAA):", value=data_inicial, key=f"q141_data_{ano_sel}", on_change=cb_input_14_1)
                    
                with c141_2:
                    link_141 = st.text_area("Link/Evidência (14.1):", value=d141.get("link", ""), key=f"t_141_{ano_sel}", on_change=cb_text_14_1, height=180)
                    placeholder_links_141 = st.empty()
                    links_141_visuais = [u[0] for u in re.findall(regex_pure_url, link_141 or "")]
                    if links_141_visuais:
                        placeholder_links_141.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_141_visuais]))
                        
                st.code("📊 Impacto de Pontuação no Quesito 14.1: 0.0 pontos", language="text")
                bloco_comentarios("14.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_1_{ano_sel}", False):
            modal_aviso_link("14.1", st.session_state.get(f"links_pendentes_14_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = False


        # --- QUESITO 14.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_url_divulgacao_14_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.2 - Página Eletrônica de Divulgação da Regulamentação", expanded=True):
                st.subheader("14.2 • Página Eletrônica de Divulgação")
                st.write("**Página eletrônica (link na internet) de divulgação do instrumento de regulamentação do sistema de controle interno (XYZ se não disponível):**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                d142 = res_data.get("14.2", {"valor": "", "pontos": 0.0, "link": ""})
                if d142 is None: d142 = {"valor": "", "pontos": 0.0, "link": ""}
                if not isinstance(d142, dict): d142 = {"valor": str(d142), "pontos": 0.0, "link": ""}

                def cb_input_14_2():
                    v_input = st.session_state[f"q142_txt_{ano_sel}"]
                    lnk = st.session_state.get(f"t_142_{ano_sel}", d142.get("link", ""))
                    save_resp("14.2", v_input, 0.0, lnk)
                    res_data["14.2"] = {"valor": v_input, "pontos": 0.0, "link": lnk}

                def cb_text_14_2():
                    lnk = st.session_state[f"t_142_{ano_sel}"]
                    v_input = st.session_state.get(f"q142_txt_{ano_sel}", d142.get("valor", ""))
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d142.get("link", "") or "")]
                    
                    if v_input != d142.get("valor", "") or lnk != d142.get("link", ""):
                        save_resp("14.2", v_input, 0.0, lnk)
                        res_data["14.2"] = {"valor": v_input, "pontos": 0.0, "link": lnk}
                        
                        if lnk != d142.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_2_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_2_{ano_sel}"] = True

                c142_1, c142_2 = st.columns([1, 1])
                with c142_1:
                    st.text_input("Página eletrônica (link) 14.2:", value=d142["valor"], key=f"q142_txt_{ano_sel}", on_change=cb_input_14_2)
                    
                with c142_2:
                    link_142 = st.text_area("Link/Evidência (14.2):", value=d142.get("link", ""), key=f"t_142_{ano_sel}", on_change=cb_text_14_2, height=100)
                    placeholder_links_142 = st.empty()
                    links_142_visuais = [u[0] for u in re.findall(regex_pure_url, link_142 or "")]
                    if links_142_visuais:
                        placeholder_links_142.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_142_visuais]))
                        
                st.code("📊 Impacto de Pontuação no Quesito 14.2: 0.0 pontos", language="text")
                bloco_comentarios("14.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_2_{ano_sel}", False):
            modal_aviso_link("14.2", st.session_state.get(f"links_pendentes_14_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_2_{ano_sel}"] = False


        # --- QUESITO 14.3 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_funcoes_14_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.3 - Funções Atribuídas ao Sistema de Controle Interno", expanded=True):
                st.subheader("14.3 • Funções do Controle Interno")
                st.write("**Assinale as funções atribuídas ao sistema controle interno:**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes_143 = {
                    "Avaliar o cumprimento das metas físicas e financeiras dos planos orçamentários, bem como a eficiência de seus resultados – 01": 1.0,
                    "Comprovar a legalidade da gestão orçamentária, financeira e patrimonial – 01": 1.0,
                    "Comprovar a legalidade dos repasses a entidades do terceiro setor, avaliando a eficácia e a eficiência dos resultados alcançados – 01": 1.0,
                    "Exercer o controle das operações de crédito, avais e garantias, bem como dos direitos e haveres do Município – 01": 1.0,
                    "Em conjunto com autoridades da Administração Financeira do Município, assinar o Relatório de Gestão Fiscal – 01": 1.0,
                    "Atestar a regularidade da tomada de contas dos ordenadores de despesa, recebedores, tesoureiros, pagadores ou assemelhados – 01": 1.0,
                    "Apoiar o Tribunal de Contas no exercício de sua missão institutional – 01": 1.0,
                    "Comprovar a eficácia e a eficiência da gestão orçamentária, financeira e patrimonial – 01": 1.0,
                    "Acompanhar as metas de superávit orçamentário, primário e nominal – 01": 1.0,
                    "Observar se as operações de créditos sujeitam-se aos limites e condições das Resoluções 40 e 43/2001, do Senado – 01": 1.0,
                    "Verificar se os empréstimos e financiamentos vêm sendo pagos tal qual previsto nos respectivos contratos – 01": 1.0,
                    "Verificar se está sendo providenciada a recondução da despesa de pessoal e da dívida consolidada a seus limites fiscais – 01": 1.0,
                    "Comprovar se os recursos da alienação de ativos estão sendo despendidos em gastos de capital e, não, em despesas correntes – 01": 1.0,
                    "Constatar se está sendo satisfeito o limite para gastos totais das Câmaras Municipais – 01": 1.0,
                    "Verificar a fidelidade funcional dos responsáveis por bens e valores públicos – 01": 1.0
                }
                
                d143 = res_data.get("14.3", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d143 is None: d143 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_143 = ast.literal_eval(d143["valor"])
                    if not isinstance(lista_salva_143, list): lista_salva_143 = []
                except Exception:
                    lista_salva_143 = []

                def cb_checkbox_14_3():
                    sel = []
                    for item in opcoes_143.keys():
                        ch = f"chk_143_{item}_{ano_sel}"
                        if st.session_state.get(ch, False):
                            sel.append(item)
                    pts = sum(opcoes_143[p] for p in sel)
                    lnk = st.session_state.get(f"t_143_{ano_sel}", d143.get("link", ""))
                    save_resp("14.3", str(sel), pts, lnk)
                    res_data["14.3"] = {"valor": str(sel), "pontos": pts, "link": lnk}

                def cb_text_14_3():
                    lnk = st.session_state[f"t_143_{ano_sel}"]
                    sel = []
                    for item in opcoes_143.keys():
                        ch = f"chk_143_{item}_{ano_sel}"
                        if st.session_state.get(ch, False):
                            sel.append(item)
                    pts = sum(opcoes_143[p] for p in sel)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d143.get("link", "") or "")]
                    
                    if str(sel) != d143.get("valor", "") or lnk != d143.get("link", ""):
                        save_resp("14.3", str(sel), pts, lnk)
                        res_data["14.3"] = {"valor": str(sel), "pontos": pts, "link": lnk}
                        
                        if lnk != d143.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_3_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_3_{ano_sel}"] = True

                c143_1, c143_2 = st.columns([1, 1])
                with c143_1:
                    for item in opcoes_143.keys():
                        st.checkbox(item, value=item in lista_salva_143, key=f"chk_143_{item}_{ano_sel}", on_change=cb_checkbox_14_3)
                    
                with c143_2:
                    link_143 = st.text_area("Link/Evidência (14.3):", value=d143.get("link", ""), key=f"t_143_{ano_sel}", on_change=cb_text_14_3, height=200)
                    placeholder_links_143 = st.empty()
                    links_143_visuais = [u[0] for u in re.findall(regex_pure_url, link_143 or "")]
                    if links_143_visuais:
                        placeholder_links_143.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_143_visuais]))
                        
                pts_atuais_143 = d143.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>Pontuação Total: {pts_atuais_143:.1f} pts</span>", unsafe_allow_html=True)
                bloco_comentarios("14.3", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_3_{ano_sel}", False):
            modal_aviso_link("14.3", st.session_state.get(f"links_pendentes_14_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_3_{ano_sel}"] = False

# --- QUESITO 14.4 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_recursos_humanos_14_4_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4 - Recursos Humanos no Controle Interno", expanded=True):
                st.subheader("14.4 • Recursos Humanos")
                st.write("**A prefeitura dispõe de recursos humanos para operacionalização das atividades do sistema de controle interno?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e cascata de limpeza para subníveis.*")
                
                opcoes_144 = {
                    "Selecione...": 0.0,
                    "Sim – 0,5": 0.5,
                    "Não – 00": 0.0
                }
                
                d144 = res_data.get("14.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d144 is None: d144 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_144 = d144.get("valor", "Selecione...")
                chave_radio_144 = f"r_144_{v_salvo_144}_{ano_sel}"

                def cb_radio_14_4():
                    val = st.session_state[chave_radio_144]
                    pts = opcoes_144.get(val, 0.0)
                    lnk = st.session_state.get(f"t_144_{ano_sel}", d144.get("link", ""))
                    save_resp("14.4", val, pts, lnk)
                    res_data["14.4"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    # Limpeza em cascata dos subníveis inferiores caso selecionado "Não" ou "Selecione..."
                    if val in ["Não – 00", "Selecione..."]:
                        for sub_q in ["14.4.1", "14.4.2", "14.4.3", "14.4.4"]:
                            save_resp(sub_q, "Selecione...", 0.0, "")
                            if sub_q in res_data:
                                res_data[sub_q] = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                def cb_text_14_4():
                    lnk = st.session_state[f"t_144_{ano_sel}"]
                    val = st.session_state.get(chave_radio_144, d144.get("valor", "Selecione..."))
                    pts = opcoes_144.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d144.get("link", "") or "")]
                    
                    if val != d144.get("valor", "") or lnk != d144.get("link", ""):
                        save_resp("14.4", val, pts, lnk)
                        res_data["14.4"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d144.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_{ano_sel}"] = True

                c144_1, c144_2 = st.columns([1, 1])
                with c144_1:
                    lista_opcoes_144 = list(opcoes_144.keys())
                    idx144 = lista_opcoes_144.index(d144.get("valor")) if d144.get("valor") in opcoes_144 else 0
                    st.radio("Selecione 14.4:", options=lista_opcoes_144, index=idx144, key=chave_radio_144, on_change=cb_radio_14_4, label_visibility="collapsed")
                    
                with c144_2:
                    link_144 = st.text_area("Link/Evidência (14.4):", value=d144.get("link", ""), key=f"t_144_{ano_sel}", on_change=cb_text_14_4, height=100)
                    placeholder_links_144 = st.empty()
                    links_144_visuais = [u[0] for u in re.findall(regex_pure_url, link_144 or "")]
                    if links_144_visuais:
                        placeholder_links_144.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_144_visuais]))
                        
                pts_atuais_144 = d144.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 14.4: {pts_atuais_144} pontos", language="text")
                bloco_comentarios("14.4", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_4_{ano_sel}", False):
            modal_aviso_link("14.4", st.session_state.get(f"links_pendentes_14_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_{ano_sel}"] = False


        # --- QUESITO 14.4.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_cargo_efetivo_14_4_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.1 - Responsável pela UCCI em Cargo Efetivo", expanded=True):
                st.subheader("14.4.1 • Responsável pela UCCI em Cargo Efetivo")
                st.write("**O responsável pela Unidade Central de Controle Interno (UCCI) ocupa cargo efetivo na Administração Municipal?** *(Responsável = controlador interno ou controlador geral)*")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes_1441 = {
                    "Selecione...": 0.0,
                    "Sim – 05": 5.0,
                    "Não – 00": 0.0
                }
                
                d1441 = res_data.get("14.4.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d1441 is None: d1441 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_1441 = d1441.get("valor", "Selecione...")
                chave_radio_1441 = f"r_1441_{v_salvo_1441}_{ano_sel}"

                def cb_radio_14_4_1():
                    val = st.session_state[chave_radio_1441]
                    pts = opcoes_1441.get(val, 0.0)
                    lnk = st.session_state.get(f"t_1441_{ano_sel}", d1441.get("link", ""))
                    save_resp("14.4.1", val, pts, lnk)
                    res_data["14.4.1"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_14_4_1():
                    lnk = st.session_state[f"t_1441_{ano_sel}"]
                    val = st.session_state.get(chave_radio_1441, d1441.get("valor", "Selecione..."))
                    pts = opcoes_1441.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1441.get("link", "") or "")]
                    
                    if val != d1441.get("valor", "") or lnk != d1441.get("link", ""):
                        save_resp("14.4.1", val, pts, lnk)
                        res_data["14.4.1"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d1441.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_1_{ano_sel}"] = True

                c1441_1, c1441_2 = st.columns([1, 1])
                with c1441_1:
                    lista_opcoes_1441 = list(opcoes_1441.keys())
                    idx1441 = lista_opcoes_1441.index(d1441.get("valor")) if d1441.get("valor") in opcoes_1441 else 0
                    st.radio("Selecione 14.4.1:", options=lista_opcoes_1441, index=idx1441, key=chave_radio_1441, on_change=cb_radio_14_4_1, label_visibility="collapsed")
                    
                with c1441_2:
                    link_1441 = st.text_area("Link/Evidência (14.4.1):", value=d1441.get("link", ""), key=f"t_1441_{ano_sel}", on_change=cb_text_14_4_1, height=100)
                    placeholder_links_1441 = st.empty()
                    links_1441_visuais = [u[0] for u in re.findall(regex_pure_url, link_1441 or "")]
                    if links_1441_visuais:
                        placeholder_links_1441.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1441_visuais]))
                        
                pts_atuais_1441 = d1441.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 14.4.1: {pts_atuais_1441} pontos", language="text")
                bloco_comentarios("14.4.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_4_1_{ano_sel}", False):
            modal_aviso_link("14.4.1", st.session_state.get(f"links_pendentes_14_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_1_{ano_sel}"] = False


        # --- QUESITO 14.4.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_treinamento_14_4_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.2 - Treinamento do Quadro Funcional", expanded=True):
                st.subheader("14.4.2 • Treinamento Periódico")
                st.write("**O quadro funcional do Sistema de Controle Interno recebe treinamento específico para execução das atividades inerentes ao cargo?** *(Treinamento periódico pelo menos 1 vez ao ano)*")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes_1442 = {
                    "Selecione...": 0.0,
                    "Sim – 06": 6.0,
                    "Não – 00": 0.0
                }
                
                d1442 = res_data.get("14.4.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d1442 is None: d1442 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_1442 = d1442.get("valor", "Selecione...")
                chave_radio_1442 = f"r_1442_{v_salvo_1442}_{ano_sel}"

                def cb_radio_14_4_2():
                    val = st.session_state[chave_radio_1442]
                    pts = opcoes_1442.get(val, 0.0)
                    lnk = st.session_state.get(f"t_1442_{ano_sel}", d1442.get("link", ""))
                    save_resp("14.4.2", val, pts, lnk)
                    res_data["14.4.2"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_14_4_2():
                    lnk = st.session_state[f"t_1442_{ano_sel}"]
                    val = st.session_state.get(chave_radio_1442, d1442.get("valor", "Selecione..."))
                    pts = opcoes_1442.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1442.get("link", "") or "")]
                    
                    if val != d1442.get("valor", "") or lnk != d1442.get("link", ""):
                        save_resp("14.4.2", val, pts, lnk)
                        res_data["14.4.2"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d1442.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_2_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_2_{ano_sel}"] = True

                c1442_1, c1442_2 = st.columns([1, 1])
                with c1442_1:
                    lista_opcoes_1442 = list(opcoes_1442.keys())
                    idx1442 = lista_opcoes_1442.index(d1442.get("valor")) if d1442.get("valor") in opcoes_1442 else 0
                    st.radio("Selecione 14.4.2:", options=lista_opcoes_1442, index=idx1442, key=chave_radio_1442, on_change=cb_radio_14_4_2, label_visibility="collapsed")
                    
                with c1442_2:
                    link_1442 = st.text_area("Link/Evidência (14.4.2):", value=d1442.get("link", ""), key=f"t_1442_{ano_sel}", on_change=cb_text_14_4_2, height=100)
                    placeholder_links_1442 = st.empty()
                    links_1442_visuais = [u[0] for u in re.findall(regex_pure_url, link_1442 or "")]
                    if links_1442_visuais:
                        placeholder_links_1442.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1442_visuais]))
                        
                pts_atuais_1442 = d1442.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 14.4.2: {pts_atuais_1442} pontos", language="text")
                bloco_comentarios("14.4.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_4_2_{ano_sel}", False):
            modal_aviso_link("14.4.2", st.session_state.get(f"links_pendentes_14_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_2_{ano_sel}"] = False


        # --- QUESITO 14.4.3 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_segregacao_14_4_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.3 - Segregação de Funções Financeiras e de Controle", expanded=True):
                st.subheader("14.4.3 • Segregação de Funções")
                st.write("**Na Prefeitura existe formalização da segregação de funções financeiras e de controle?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes_1443 = {
                    "Selecione...": 0.0,
                    "Sim – 05": 5.0,
                    "Não – 00": 0.0
                }
                
                d1443 = res_data.get("14.4.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d1443 is None: d1443 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_1443 = d1443.get("valor", "Selecione...")
                chave_radio_1443 = f"r_1443_{v_salvo_1443}_{ano_sel}"

                def cb_radio_14_4_3():
                    val = st.session_state[chave_radio_1443]
                    pts = opcoes_1443.get(val, 0.0)
                    lnk = st.session_state.get(f"t_1443_{ano_sel}", d1443.get("link", ""))
                    save_resp("14.4.3", val, pts, lnk)
                    res_data["14.4.3"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_14_4_3():
                    lnk = st.session_state[f"t_1443_{ano_sel}"]
                    val = st.session_state.get(chave_radio_1443, d1443.get("valor", "Selecione..."))
                    pts = opcoes_1443.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1443.get("link", "") or "")]
                    
                    if val != d1443.get("valor", "") or lnk != d1443.get("link", ""):
                        save_resp("14.4.3", val, pts, lnk)
                        res_data["14.4.3"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d1443.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_3_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_3_{ano_sel}"] = True

                c1443_1, c1443_2 = st.columns([1, 1])
                with c1443_1:
                    lista_opcoes_1443 = list(opcoes_1443.keys())
                    idx1443 = lista_opcoes_1443.index(d1443.get("valor")) if d1443.get("valor") in opcoes_1443 else 0
                    st.radio("Selecione 14.4.3:", options=lista_opcoes_1443, index=idx1443, key=chave_radio_1443, on_change=cb_radio_14_4_3, label_visibility="collapsed")
                    
                with c1443_2:
                    link_1443 = st.text_area("Link/Evidência (14.4.3):", value=d1443.get("link", ""), key=f"t_1443_{ano_sel}", on_change=cb_text_14_4_3, height=100)
                    placeholder_links_1443 = st.empty()
                    links_1443_visuais = [u[0] for u in re.findall(regex_pure_url, link_1443 or "")]
                    if links_1443_visuais:
                        placeholder_links_1443.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1443_visuais]))
                        
                pts_atuais_1443 = d1443.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 14.4.3: {pts_atuais_1443} pontos", language="text")
                bloco_comentarios("14.4.3", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_4_3_{ano_sel}", False):
            modal_aviso_link("14.4.3", st.session_state.get(f"links_pendentes_14_4_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_3_{ano_sel}"] = False


        # --- QUESITO 14.4.4 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_autonomia_14_4_4_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.4 - Autonomia e Independência da UCCI", expanded=True):
                st.subheader("14.4.4 • Autonomia e Independência")
                st.write("**A Unidade Central de Controle Interno (UCCI) possui autonomia e independência para o exercício de suas funções?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes_1444 = {
                    "Selecione...": 0.0,
                    "Sim – 06": 6.0,
                    "Não – 00": 0.0
                }
                
                d1444 = res_data.get("14.4.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d1444 is None: d1444 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_1444 = d1444.get("valor", "Selecione...")
                chave_radio_1444 = f"r_1444_{v_salvo_1444}_{ano_sel}"

                def cb_radio_14_4_4():
                    val = st.session_state[chave_radio_1444]
                    pts = opcoes_1444.get(val, 0.0)
                    lnk = st.session_state.get(f"t_1444_{ano_sel}", d1444.get("link", ""))
                    save_resp("14.4.4", val, pts, lnk)
                    res_data["14.4.4"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_14_4_4():
                    lnk = st.session_state[f"t_1444_{ano_sel}"]
                    val = st.session_state.get(chave_radio_1444, d1444.get("valor", "Selecione..."))
                    pts = opcoes_1444.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1444.get("link", "") or "")]
                    
                    if val != d1444.get("valor", "") or lnk != d1444.get("link", ""):
                        save_resp("14.4.4", val, pts, lnk)
                        res_data["14.4.4"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d1444.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_4_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_4_{ano_sel}"] = True

                c1444_1, c1444_2 = st.columns([1, 1])
                with c1444_1:
                    lista_opcoes_1444 = list(opcoes_1444.keys())
                    idx1444 = lista_opcoes_1444.index(d1444.get("valor")) if d1444.get("valor") in opcoes_1444 else 0
                    st.radio("Selecione 14.4.4:", options=lista_opcoes_1444, index=idx1444, key=chave_radio_1444, on_change=cb_radio_14_4_4, label_visibility="collapsed")
                    
                with c1444_2:
                    link_1444 = st.text_area("Link/Evidência (14.4.4):", value=d1444.get("link", ""), key=f"t_1444_{ano_sel}", on_change=cb_text_14_4_4, height=100)
                    placeholder_links_1444 = st.empty()
                    links_1444_visuais = [u[0] for u in re.findall(regex_pure_url, link_1444 or "")]
                    if links_1444_visuais:
                        placeholder_links_1444.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1444_visuais]))
                        
                pts_atuais_1444 = d1444.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 14.4.4: {pts_atuais_1444} pontos", language="text")
                bloco_comentarios("14.4.4", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_4_4_{ano_sel}", False):
            modal_aviso_link("14.4.4", st.session_state.get(f"links_pendentes_14_4_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_4_{ano_sel}"] = False

# --- QUESITO 14.4.4.1 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_subordinacao_14_4_4_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.4.1 - Subordinação Organizacional da UCCI", expanded=True):
                st.subheader("14.4.4.1 • Vínculo Organizacional")
                st.write("**A estrutura organizacional da Unidade Central de Controle Interno (UCCI) está associada ou subordinada a qual secretaria/diretoria?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opc14441 = {
                    "Selecione...": 0.0,
                    "Administração – -06 (perde 06 pontos)": -6.0,
                    "Finanças/Fazenda – -06 (perde 06 pontos)": -6.0,
                    "Planejamento/Orçamento/Gestão – -06 (perde 06 pontos)": -6.0,
                    "Gabinete do Prefeito – 00": 0.0,
                    "Outra – -06 (perde 06 pontos)": -6.0
                }
                
                d14441 = res_data.get("14.4.4.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d14441 is None: d14441 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_14441 = d14441.get("valor", "Selecione...")
                chave_radio_14441 = f"r_14441_{v_salvo_14441}_{ano_sel}"

                def cb_radio_14_4_4_1():
                    val = st.session_state[chave_radio_14441]
                    pts = opc14441.get(val, 0.0)
                    lnk = st.session_state.get(f"t_14441_{ano_sel}", d14441.get("link", ""))
                    save_resp("14.4.4.1", val, pts, lnk)
                    res_data["14.4.4.1"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_14_4_4_1():
                    lnk = st.session_state[f"t_14441_{ano_sel}"]
                    val = st.session_state.get(chave_radio_14441, d14441.get("valor", "Selecione..."))
                    pts = opc14441.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d14441.get("link", "") or "")]
                    
                    if val != d14441.get("valor", "") or lnk != d14441.get("link", ""):
                        save_resp("14.4.4.1", val, pts, lnk)
                        res_data["14.4.4.1"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d14441.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_4_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_4_1_{ano_sel}"] = True

                c14441_1, c14441_2 = st.columns([1, 1])
                with c14441_1:
                    lista_opcoes_14441 = list(opc14441.keys())
                    idx14441 = lista_opcoes_14441.index(d14441.get("valor")) if d14441.get("valor") in opc14441 else 0
                    st.radio("Selecione 14.4.4.1:", options=lista_opcoes_14441, index=idx14441, key=chave_radio_14441, on_change=cb_radio_14_4_4_1, label_visibility="collapsed")
                    
                with c14441_2:
                    link_14441 = st.text_area("Link/Evidência (14.4.4.1):", value=d14441.get("link", ""), key=f"t_14441_{ano_sel}", on_change=cb_text_14_4_4_1, height=140)
                    placeholder_links_14441 = st.empty()
                    links_14441_visuais = [u[0] for u in re.findall(regex_pure_url, link_14441 or "")]
                    if links_14441_visuais:
                        placeholder_links_14441.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_14441_visuais]))
                        
                pts_atuais_14441 = d14441.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 14.4.4.1: {pts_atuais_14441} pontos", language="text")
                bloco_comentarios("14.4.4.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_4_4_1_{ano_sel}", False):
            modal_aviso_link("14.4.4.1", st.session_state.get(f"links_pendentes_14_4_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_4_1_{ano_sel}"] = False


        # --- QUESITO 14.4.4.2 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_comunicacao_14_4_4_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.4.2 - Comunicação de Irregularidades ou Ilegalidades", expanded=True):
                st.subheader("14.4.4.2 • Comunicações Efetuadas")
                st.write("**A Unidade Central de Controle Interno (UCCI) procedeu com alguma comunicação de irregularidade ou ilegalidade em 2025?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e cascata de limpeza.*")
                
                opc14442 = {
                    "Selecione...": 0.0,
                    "Sim, houve comunicação da irregularidade ou ilegalidade – 00": 0.0,
                    "Houve irregularidade ou ilegalidade, mas não procedeu a comunicação – -03 (perde 03 pontos)": -3.0,
                    "Não houve irregularidades nem ilegalidades – 00": 0.0
                }
                
                d14442 = res_data.get("14.4.4.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d14442 is None: d14442 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_14442 = d14442.get("valor", "Selecione...")
                chave_radio_14442 = f"r_14442_{v_salvo_1442}_{ano_sel}"

                def cb_radio_14_4_4_2():
                    val = st.session_state[chave_radio_14442]
                    pts = opc14442.get(val, 0.0)
                    lnk = st.session_state.get(f"t_14442_{ano_sel}", d14442.get("link", ""))
                    save_resp("14.4.4.2", val, pts, lnk)
                    res_data["14.4.4.2"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    # Limpeza das tabelas numéricas dependentes acopladas se a resposta mudar ou desativar o gatilho
                    if val != "Sim, houve comunicação da irregularidade ou ilegalidade – 00":
                        for sub_composto in ["14.4.4.2.1_tcesp", "14.4.4.2.1_mpsp"]:
                            save_resp(sub_composto, "0", 0.0, "")
                            if sub_composto in res_data:
                                res_data[sub_composto] = {"valor": "0", "pontos": 0.0, "link": ""}

                def cb_text_14_4_4_2():
                    lnk = st.session_state[f"t_14442_{ano_sel}"]
                    val = st.session_state.get(chave_radio_14442, d14442.get("valor", "Selecione..."))
                    pts = opc14442.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d14442.get("link", "") or "")]
                    
                    if val != d14442.get("valor", "") or lnk != d14442.get("link", ""):
                        save_resp("14.4.4.2", val, pts, lnk)
                        res_data["14.4.4.2"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d14442.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_4_2_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_4_2_{ano_sel}"] = True

                c14442_1, c14442_2 = st.columns([1, 1])
                with c14442_1:
                    lista_opcoes_14442 = list(opc14442.keys())
                    idx14442 = lista_opcoes_14442.index(d14442.get("valor")) if d14442.get("valor") in opc14442 else 0
                    st.radio("Selecione 14.4.4.2:", options=lista_opcoes_14442, index=idx14442, key=chave_radio_14442, on_change=cb_radio_14_4_4_2, label_visibility="collapsed")
                    
                with c14442_2:
                    link_14442 = st.text_area("Link/Evidência (14.4.4.2):", value=d14442.get("link", ""), key=f"t_14442_{ano_sel}", on_change=cb_text_14_4_2, height=120)
                    placeholder_links_14442 = st.empty()
                    links_14442_visuais = [u[0] for u in re.findall(regex_pure_url, link_14442 or "")]
                    if links_14442_visuais:
                        placeholder_links_14442.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_14442_visuais]))
                        
                pts_atuais_14442 = d14442.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 14.4.4.2: {pts_atuais_14442} pontos", language="text")
                bloco_comentarios("14.4.4.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_4_4_2_{ano_sel}", False):
            modal_aviso_link("14.4.4.2", st.session_state.get(f"links_pendentes_14_4_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_4_2_{ano_sel}"] = False

# --- QUESITO CONDICIONAL COMPREENSIVO 14.4.4.2.1 • FILHO DE 14.4.4.2 ---
        if d14442.get("valor") == "Sim, houve comunicação da irregularidade ou ilegalidade – 00":
            with st.container(key=f"container_bloco_quantitativos_14_4_4_2_1_final_{ano_sel}", border=True):
                with st.expander(f"📊 Quesito 14.4.4.2.1 - Quantidade de Irregularidades Comunicadas", expanded=True):
                    st.subheader("14.4.4.2.1 • Quantitativos Informados")
                    st.write("**Informe a quantidade de irregularidades ou ilegalidades comunicadas ao:**")
                    st.caption("ℹ *Mecanismo de salvamento acoplado e unificado em lote via callbacks.*")
                    
                    d144421_tce = res_data.get("14.4.4.2.1_tcesp", {"valor": "0", "pontos": 0.0, "link": ""})
                    d144421_mp = res_data.get("14.4.4.2.1_mpsp", {"valor": "0", "pontos": 0.0, "link": ""})
                    
                    if d144421_tce is None: d144421_tce = {"valor": "0", "pontos": 0.0, "link": ""}
                    if d144421_mp is None: d144421_mp = {"valor": "0", "pontos": 0.0, "link": ""}
                    
                    chave_num_tce = f"n_144421_tce_{d144421_tce.get('valor','0')}_{ano_sel}"
                    chave_num_mp = f"n_144421_mp_{d144421_mp.get('valor','0')}_{ano_sel}"

                    def cb_composto_quantitativos_14_4_4_2_1():
                        val_tce = str(st.session_state.get(chave_num_tce, d144421_tce.get("valor", "0")))
                        val_mp = str(st.session_state.get(chave_num_mp, d144421_mp.get("valor", "0")))
                        lnk = st.session_state.get(f"t_144421_{ano_sel}", d144421_tce.get("link", ""))
                        
                        save_resp("14.4.4.2.1_tcesp", val_tce, 0.0, lnk)
                        save_resp("14.4.4.2.1_mpsp", val_mp, 0.0, lnk)
                        res_data["14.4.4.2.1_tcesp"] = {"valor": val_tce, "pontos": 0.0, "link": lnk}
                        res_data["14.4.4.2.1_mpsp"] = {"valor": val_mp, "pontos": 0.0, "link": lnk}
                        
                        links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                        links_antigos = [u[0] for u in re.findall(regex_pure_url, d144421_tce.get("link", "") or "")]
                        
                        if lnk != d144421_tce.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_4_2_1_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_4_2_1_{ano_sel}"] = True

                    c144421_1, c144421_2 = st.columns([1, 1])
                    with c144421_1:
                        c_sub_tce, c_sub_mp = st.columns(2)
                        with c_sub_tce:
                            v_ini_tce = int(d144421_tce.get("valor")) if d144421_tce.get("valor", "").isdigit() else 0
                            st.number_input("TCESP:", min_value=0, step=1, value=v_ini_tce, key=chave_num_tce, on_change=cb_composto_quantitativos_14_4_4_2_1)
                        with c_sub_mp:
                            v_ini_mp = int(d144421_mp.get("valor")) if d144421_mp.get("valor", "").isdigit() else 0
                            st.number_input("MPSP:", min_value=0, step=1, value=v_ini_mp, key=chave_num_mp, on_change=cb_composto_quantitativos_14_4_4_2_1)
                            
                    with c144421_2:
                        link_144421 = st.text_area("Link/Evidência (14.4.4.2.1):", value=d144421_tce.get("link", ""), key=f"t_144421_{ano_sel}", on_change=cb_composto_quantitativos_14_4_4_2_1, height=100)
                        placeholder_links_144421 = st.empty()
                        links_144421_visuais = [u[0] for u in re.findall(regex_pure_url, link_144421 or "")]
                        if links_144421_visuais:
                            placeholder_links_144421.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_144421_visuais]))
                            
                    st.code("📊 Impacto de Pontuação no Quesito 14.4.4.2.1: 0.0 pontos", language="text")
                    bloco_comentarios("14.4.4.2.1", res_data, ano_sel)

            if st.session_state.get(f"gatilho_modal_14_4_4_2_1_{ano_sel}", False):
                modal_aviso_link("14.4.4.2.1", st.session_state.get(f"links_pendentes_14_4_4_2_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_14_4_4_2_1_{ano_sel}"] = False


        # --- QUESITO 14.4.5 • TOTALMENTE INDEPENDENTE (BLINDADO COM O PADRÃO 1.0) ---
        with st.container(key=f"container_bloco_relatorios_14_4_5_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 14.4.5 - Relatórios Periódicos do Controle Interno", expanded=True):
                st.subheader("14.4.5 • Relatórios Periódicos")
                st.write("**O responsável pela Unidade Central de Controle Interno (UCCI) apresentou relatórios periódicos que demonstram efetivo exercício de suas atribuições?** *(Periodicidade mínima anual)*")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link e cascata de limpeza para filhos.*")
                
                opcoes_1445 = {
                    "Selecione...": 0.0,
                    "Sim – 05": 5.0,
                    "Não – 00": 0.0
                }
                
                d1445 = res_data.get("14.4.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d1445 is None: d1445 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_1445 = d1445.get("valor", "Selecione...")
                chave_radio_1445 = f"r_1445_{v_salvo_1445}_{ano_sel}"

                def cb_radio_14_4_5():
                    val = st.session_state[chave_radio_1445]
                    pts = opcoes_1445.get(val, 0.0)
                    lnk = st.session_state.get(f"t_1445_{ano_sel}", d1445.get("link", ""))
                    save_resp("14.4.5", val, pts, lnk)
                    res_data["14.4.5"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    # Se marcar "Não" ou resetar para "Selecione...", limpa os sub-quesitos filhos em cascata
                    if val in ["Não – 00", "Selecione..."]:
                        for sub_q in ["14.4.5.1", "14.4.5.1.1"]:
                            save_resp(sub_q, "Selecione...", 0.0, "")
                            if sub_q in res_data:
                                res_data[sub_q] = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                def cb_text_14_4_5():
                    lnk = st.session_state[f"t_1445_{ano_sel}"]
                    val = st.session_state.get(chave_radio_1445, d1445.get("valor", "Selecione..."))
                    pts = opcoes_1445.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1445.get("link", "") or "")]
                    
                    if val != d1445.get("valor", "") or lnk != d1445.get("link", ""):
                        save_resp("14.4.5", val, pts, lnk)
                        res_data["14.4.5"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d1445.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_4_5_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_4_5_{ano_sel}"] = True

                c1445_1, c1445_2 = st.columns([1, 1])
                with c1445_1:
                    lista_opcoes_1445 = list(opcoes_1445.keys())
                    idx1445 = lista_opcoes_1445.index(d1445.get("valor")) if d1445.get("valor") in opcoes_1445 else 0
                    st.radio("Selecione 14.4.5:", options=lista_opcoes_1445, index=idx1445, key=chave_radio_1445, on_change=cb_radio_14_4_5, label_visibility="collapsed")
                    
                with c1445_2:
                    link_1445 = st.text_area("Link/Evidência (14.4.5):", value=d1445.get("link", ""), key=f"t_1445_{ano_sel}", on_change=cb_text_14_4_5, height=100)
                    placeholder_links_1445 = st.empty()
                    links_1445_visuais = [u[0] for u in re.findall(regex_pure_url, link_1445 or "")]
                    if links_1445_visuais:
                        placeholder_links_1445.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1445_visuais]))
                        
                pts_atuais_1445 = d1445.get("pontos", 0.0)
                st.code(f"📊 Impacto de Pontuação no Quesito 14.4.5: {pts_atuais_1445} pontos", language="text")
                bloco_comentarios("14.4.5", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_4_5_{ano_sel}", False):
            modal_aviso_link("14.4.5", st.session_state.get(f"links_pendentes_14_4_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_4_5_{ano_sel}"] = False

# --- QUESITO CONDICIONAL 14.4.5.1 • FILHO DE 14.4.5 ---
        # Exibido apenas se o pai (14.4.5) for "Sim – 05"
        if d1445.get("valor") == "Sim – 05":
            with st.container(key=f"container_bloco_providencias_14_4_5_1_final_{ano_sel}", border=True):
                with st.expander(f"📋 Quesito 14.4.5.1 - Providências do Prefeito", expanded=True):
                    st.subheader("14.4.5.1 • Providências Determinadas")
                    st.write("**Com base no relatório do Controle Interno, o Prefeito determinou as providências cabíveis diante das irregularidades e ilegalidades apontadas?**")
                    st.caption("ℹ *Salvamento por callback nativo com cascata de limpeza associada.*")
                    
                    opcoes_14451 = {
                        "Selecione...": 0.0,
                        "Sim - de todos os apontamentos – 06": 6.0,
                        "Sim - de parte dos apontamentos – 02": 2.0,
                        "Não – 00": 0.0,
                        "Não foram relatadas irregularidades – 06": 6.0
                    }
                    
                    d14451 = res_data.get("14.4.5.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                    if d14451 is None: d14451 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                    v_salvo_14451 = d14451.get("valor", "Selecione...")
                    chave_radio_14451 = f"r_14451_{v_salvo_14451}_{ano_sel}"

                    def cb_radio_14_4_5_1():
                        val = st.session_state[chave_radio_14451]
                        pts = opcoes_14451.get(val, 0.0)
                        lnk = st.session_state.get(f"t_14451_{ano_sel}", d14451.get("link", ""))
                        save_resp("14.4.5.1", val, pts, lnk)
                        res_data["14.4.5.1"] = {"valor": val, "pontos": pts, "link": lnk}

                    def cb_text_14_4_5_1():
                        lnk = st.session_state[f"t_14451_{ano_sel}"]
                        val = st.session_state.get(chave_radio_14451, d14451.get("valor", "Selecione..."))
                        pts = opcoes_14451.get(val, 0.0)
                        
                        links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                        links_antigos = [u[0] for u in re.findall(regex_pure_url, d14451.get("link", "") or "")]
                        
                        if val != d14451.get("valor", "") or lnk != d14451.get("link", ""):
                            save_resp("14.4.5.1", val, pts, lnk)
                            res_data["14.4.5.1"] = {"valor": val, "pontos": pts, "link": lnk}
                            
                            if lnk != d14451.get("link", "") and links_atuais:
                                if links_atuais != links_antigos:
                                    st.session_state[f"links_pendentes_14_4_5_1_{ano_sel}"] = links_atuais
                                    st.session_state[f"gatilho_modal_14_4_5_1_{ano_sel}"] = True

                    c14451_1, c14451_2 = st.columns([1, 1])
                    with c14451_1:
                        lista_opcoes_14451 = list(opcoes_14451.keys())
                        idx14451 = lista_opcoes_14451.index(d14451.get("valor")) if d14451.get("valor") in opcoes_14451 else 0
                        st.radio("Selecione 14.4.5.1:", options=lista_opcoes_14451, index=idx14451, key=chave_radio_14451, on_change=cb_radio_14_4_5_1, label_visibility="collapsed")
                        
                    with c14451_2:
                        link_14451 = st.text_area("Link/Evidência (14.4.5.1):", value=d14451.get("link", ""), key=f"t_14451_{ano_sel}", on_change=cb_text_14_4_5_1, height=120)
                        placeholder_links_14451 = st.empty()
                        links_14451_visuais = [u[0] for u in re.findall(regex_pure_url, link_14451 or "")]
                        if links_14451_visuais:
                            placeholder_links_14451.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_14451_visuais]))
                            
                    pts_atuais_14451 = d14451.get("pontos", 0.0)
                    st.code(f"📊 Impacto de Pontuação no Quesito 14.4.5.1: {pts_atuais_14451} pontos", language="text")
                    bloco_comentarios("14.4.5.1", res_data, ano_sel)

            if st.session_state.get(f"gatilho_modal_14_4_5_1_{ano_sel}", False):
                modal_aviso_link("14.4.5.1", st.session_state.get(f"links_pendentes_14_4_5_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_14_4_5_1_{ano_sel}"] = False


        # --- QUESITO CONDICIONAL 14.4.5.1.1 • NETO DE 14.4.5 ---
        # Exibido apenas se o pai (14.4.5) for "Sim – 05"
        if d1445.get("valor") == "Sim – 05":
            with st.container(key=f"container_bloco_prazos_14_4_5_1_1_final_{ano_sel}", border=True):
                with st.expander(f"🔍 Quesito 14.4.5.1.1 - Acompanhamento de Prazos", expanded=True):
                    st.subheader("14.4.5.1.1 • Medidas e Prazos")
                    st.write("**O Controle Interno acompanhou as medidas e os prazos das providências determinadas pelo Prefeito diante dos apontamentos do relatório do Controle Interno?**")
                    st.caption("ℹ *Atenção: Este quesito possui pontuação redutora (penalidade de -3.0 pts se assinalado 'Não').*")
                    
                    opcoes_144511 = {
                        "Selecione...": 0.0,
                        "Sim - de todas as providências determinadas pelo Prefeito – 00": 0.0,
                        "Sim - de parte das providências determinadas pelo Prefeito – 00": 0.0,
                        "Não – -03 (perde 03 pontos)": -3.0
                    }
                    
                    d144511 = res_data.get("14.4.5.1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                    if d144511 is None: d144511 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                    v_salvo_144511 = d144511.get("valor", "Selecione...")
                    chave_radio_144511 = f"r_144511_{v_salvo_144511}_{ano_sel}"

                    def cb_radio_14_4_5_1_1():
                        val = st.session_state[chave_radio_144511]
                        pts = opcoes_144511.get(val, 0.0)
                        lnk = st.session_state.get(f"t_144511_{ano_sel}", d144511.get("link", ""))
                        save_resp("14.4.5.1.1", val, pts, lnk)
                        res_data["14.4.5.1.1"] = {"valor": val, "pontos": pts, "link": lnk}

                    def cb_text_14_4_5_1_1():
                        lnk = st.session_state[f"t_144511_{ano_sel}"]
                        val = st.session_state.get(chave_radio_144511, d144511.get("valor", "Selecione..."))
                        pts = opcoes_144511.get(val, 0.0)
                        
                        links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                        links_antigos = [u[0] for u in re.findall(regex_pure_url, d144511.get("link", "") or "")]
                        
                        if val != d144511.get("valor", "") or lnk != d144511.get("link", ""):
                            save_resp("14.4.5.1.1", val, pts, lnk)
                            res_data["14.4.5.1.1"] = {"valor": val, "pontos": pts, "link": lnk}
                            
                            if lnk != d144511.get("link", "") and links_atuais:
                                if links_atuais != links_antigos:
                                    st.session_state[f"links_pendentes_14_4_5_1_1_{ano_sel}"] = links_atuais
                                    st.session_state[f"gatilho_modal_14_4_5_1_1_{ano_sel}"] = True

                    c144511_1, c144511_2 = st.columns([1, 1])
                    with c144511_1:
                        lista_opcoes_144511 = list(opcoes_144511.keys())
                        idx144511 = lista_opcoes_144511.index(d144511.get("valor")) if d144511.get("valor") in opcoes_144511 else 0
                        st.radio("Selecione 14.4.5.1.1:", options=lista_opcoes_144511, index=idx144511, key=chave_radio_144511, on_change=cb_radio_14_4_5_1_1, label_visibility="collapsed")
                        
                    with c144511_2:
                        link_144511 = st.text_area("Link/Evidência (14.4.5.1.1):", value=d144511.get("link", ""), key=f"t_144511_{ano_sel}", on_change=cb_text_14_4_5_1_1, height=120)
                        placeholder_links_144511 = st.empty()
                        links_144511_visuais = [u[0] for u in re.findall(regex_pure_url, link_144511 or "")]
                        if links_144511_visuais:
                            placeholder_links_144511.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_144511_visuais]))
                            
                    pts_atuais_144511 = d144511.get("pontos", 0.0)
                    st.code(f"📊 Impacto de Pontuação no Quesito 14.4.5.1.1: {pts_atuais_144511} pontos", language="text")
                    bloco_comentarios("14.4.5.1.1", res_data, ano_sel)

            if st.session_state.get(f"gatilho_modal_14_4_5_1_1_{ano_sel}", False):
                modal_aviso_link("14.4.5.1.1", st.session_state.get(f"links_pendentes_14_4_5_1_1_{ano_sel}", []))
                st.session_state[f"gatilho_modal_14_4_5_1_1_{ano_sel}"] = False


        # --- QUESITO MASTER 14.5 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_plano_14_5_final_{ano_sel}", border=True):
            with st.expander(f"📈 Quesito 14.5 - Plano Operativo Anual", expanded=True):
                st.subheader("14.5 • Plano Operativo Anual")
                st.write("**Houve a operação de Plano Operativo Anual?** *(Obs.: Plano Operativo Anual consiste no planejamento das atividades a serem executadas no exercício seguinte a sua elaboração).*")
                st.caption("ℹ *Se modificado para 'Não', o sub-quesito estrutural correspondente (14.5.1) será redefinido.*")
                
                opcoes_145 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                
                d145 = res_data.get("14.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d145 is None: d145 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_145 = d145.get("valor", "Selecione...")
                chave_radio_145 = f"r_145_{v_salvo_145}_{ano_sel}"

                def cb_radio_14_5():
                    val = st.session_state[chave_radio_145]
                    pts = opcoes_145.get(val, 0.0)
                    lnk = st.session_state.get(f"t_145_{ano_sel}", d145.get("link", ""))
                    save_resp("14.5", val, pts, lnk)
                    res_data["14.5"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    if val == "Não":
                        save_resp("14.5.1", "Selecione...", 0.0, "")
                        if "14.5.1" in res_data:
                            res_data["14.5.1"] = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                def cb_text_14_5():
                    lnk = st.session_state[f"t_145_{ano_sel}"]
                    val = st.session_state.get(chave_radio_145, d145.get("valor", "Selecione..."))
                    pts = opcoes_145.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d145.get("link", "") or "")]
                    
                    if val != d145.get("valor", "") or lnk != d145.get("link", ""):
                        save_resp("14.5", val, pts, lnk)
                        res_data["14.5"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d145.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_14_5_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_14_5_{ano_sel}"] = True

                c145_1, c145_2 = st.columns([1, 1])
                with c145_1:
                    lista_opcoes_145 = list(opcoes_145.keys())
                    idx145 = lista_opcoes_145.index(d145.get("valor")) if d145.get("valor") in opcoes_145 else 0
                    st.radio("Selecione 14.5:", options=lista_opcoes_145, index=idx145, key=chave_radio_145, on_change=cb_radio_14_5, label_visibility="collapsed")
                    
                with c145_2:
                    link_145 = st.text_area("Link/Evidência (14.5):", value=d145.get("link", ""), key=f"t_145_{ano_sel}", on_change=cb_text_14_5, height=100)
                    placeholder_links_145 = st.empty()
                    links_145_visuais = [u[0] for u in re.findall(regex_pure_url, link_145 or "")]
                    if links_145_visuais:
                        placeholder_links_145.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_145_visuais]))
                        
                st.code("📊 Impacto de Pontuação no Quesito 14.5: 0.0 pontos", language="text")
                bloco_comentarios("14.5", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_5_{ano_sel}", False):
            modal_aviso_link("14.5", st.session_state.get(f"links_pendentes_14_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_5_{ano_sel}"] = False

# --- QUESITO MULTISSELEÇÃO 14.5.1 • TOTALMENTE INDEPENDENTE NA TELA ---
        with st.container(key=f"container_bloco_atividades_plano_14_5_1_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 14.5.1 - Atividades Previstas no Plano Operativo", expanded=True):
                st.subheader("14.5.1 • Atividades do Plano Operativo")
                st.write("**Assinale as atividades previstas no Plano Operativo Anual:**")
                st.caption("ℹ *Exibido de forma independente. A pontuação é calculada por faixas baseada na quantidade de itens selecionados.*")
                
                opcoes_1451 = [
                    "Receitas", "Despesas", "Administração de pessoal", "Estoques e almoxarifados",
                    "Administração do patrimônio", 
                    "Cumprimento das metas do PPA e a execução dos programas de governo e dos orçamentos (LOA e LDO)",
                    "Cumprimento das metas fiscais, físicas e de resultados dos programas de governo, no que tange a eficiência, eficácia e efetividade",
                    "Aplicação de recursos públicos por entidades de direito público",
                    "Aplicação de recursos públicos por entidades de direito privado",
                    "Os limites e condições para a inscrição de despesas em Restos a Pagar",
                    "Cumprimento da legislação de licitações e fiscalização de contratos",
                    "Cumprimento do limite de gastos totais dos legislativos municipais, inclusive no que se refere ao atingimento de metas fiscais (Gestão Fiscal)",
                    "Transferência para o Legislativo Municipal (Repasses de Duodécimos)",
                    "Contabilidade", "Transparência", "Lei de Acesso à Informação", "Outros"
                ]
                
                d1451 = res_data.get("14.5.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d1451 is None: d1451 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_1451 = eval(d1451.get("valor", "[]"))
                    if not isinstance(lista_salva_1451, list): lista_salva_1451 = []
                except:
                    lista_salva_1451 = []

                def cb_composto_multiselecao_14_5_1():
                    itens_checados = []
                    for opt in opcoes_1451:
                        if st.session_state.get(f"chk_1451_{opt}_{ano_sel}", opt in lista_salva_1451):
                            itens_checados.append(opt)
                    
                    qtd = len(itens_checados)
                    if qtd == 0: pts = 0.0
                    elif 1 <= qtd <= 5: pts = 1.0
                    elif 6 <= qtd <= 10: pts = 3.0
                    else: pts = 5.0
                    
                    lnk = st.session_state.get(f"t_1451_{ano_sel}", d1451.get("link", ""))
                    str_lista = str(itens_checados)
                    
                    save_resp("14.5.1", str_lista, pts, lnk)
                    res_data["14.5.1"] = {"valor": str_lista, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1451.get("link", "") or "")]
                    
                    if lnk != d1451.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_14_5_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_14_5_1_{ano_sel}"] = True

                c1451_1, c1451_2 = st.columns([1, 1])
                with c1451_1:
                    for item in opcoes_1451:
                        st.checkbox(item, value=item in lista_salva_1451, key=f"chk_1451_{item}_{ano_sel}", on_change=cb_composto_multiselecao_14_5_1)
                        
                with c1451_2:
                    link_1451 = st.text_area("Link/Evidência (14.5.1):", value=d1451.get("link", ""), key=f"t_1451_{ano_sel}", on_change=cb_composto_multiselecao_14_5_1, height=200)
                    placeholder_links_1451 = st.empty()
                    links_1451_visuais = [u[0] for u in re.findall(regex_pure_url, link_1451 or "")]
                    if links_1451_visuais:
                        placeholder_links_1451.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1451_visuais]))
                        
                try:
                    qtd_atual_print = len(eval(d1451.get("valor", "[]")))
                except:
                    qtd_atual_print = 0
                    
                pts_atuais_1451 = d1451.get("pontos", 0.0)
                st.code(f"📊 Selecionados: {qtd_atual_print} itens | Impacto de Pontuação no Quesito 14.5.1: {pts_atuais_1451} pontos", language="text")
                bloco_comentarios("14.5.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_14_5_1_{ano_sel}", False):
            modal_aviso_link("14.5.1", st.session_state.get(f"links_pendentes_14_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_14_5_1_{ano_sel}"] = False


        # =========================================================================
        # GRUPO 15 - OUVIDORIA PÚBLICA
        # =========================================================================
        st.markdown("## 🏢 GRUPO 15 - OUVIDORIA PÚBLICA")

        # --- QUESITO MASTER 15.0 • TOTALMENTE VISÍVEL E INDEPENDENTE ---
        with st.container(key=f"container_bloco_ouvidoria_master_15_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 15.0 - Criação da Ouvidoria Pública", expanded=True):
                st.subheader("15.0 • Ouvidoria Pública Executiva")
                st.write("**Houve a criação da ouvidoria pública no âmbito do Poder Executivo Municipal?**")
                st.caption("ℹ *Se modificado para 'Não', a árvore de respostas filhas será limpa no banco, mantendo os quesitos visíveis na tela.*")
                
                opcoes_150 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": 0.0
                }
                
                d150 = res_data.get("15.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d150 is None: d150 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_150 = d150.get("valor", "Selecione...")
                chave_radio_150 = f"r_150_{v_salvo_150}_{ano_sel}"

                def cb_radio_15_0():
                    val = st.session_state[chave_radio_150]
                    pts = opcoes_150.get(val, 0.0)
                    lnk = st.session_state.get(f"t_150_{ano_sel}", d150.get("link", ""))
                    save_resp("15.0", val, pts, lnk)
                    res_data["15.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    if val == "Não":
                        limpeza_grupo_15 = {
                            "15.1": "Selecione...", "15.2": "Selecione...", "15.3": "[]", 
                            "15.4": "Selecione...", "15.4.1": "[]", "15.4.2": "Selecione...", 
                            "15.5": "[]"
                        }
                        for sub_q, d_val in limpeza_grupo_15.items():
                            save_resp(sub_q, d_val, 0.0, "")
                            if sub_q in res_data:
                                res_data[sub_q] = {"valor": d_val, "pontos": 0.0, "link": ""}

                def cb_text_15_0():
                    lnk = st.session_state[f"t_150_{ano_sel}"]
                    val = st.session_state.get(chave_radio_150, d150.get("valor", "Selecione..."))
                    pts = opcoes_150.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d150.get("link", "") or "")]
                    
                    if val != d150.get("valor", "") or lnk != d150.get("link", ""):
                        save_resp("15.0", val, pts, lnk)
                        res_data["15.0"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d150.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_15_0_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = True

                c150_1, c150_2 = st.columns([1, 1])
                with c150_1:
                    lista_opcoes_150 = list(opcoes_150.keys())
                    idx150 = lista_opcoes_150.index(d150.get("valor")) if d150.get("valor") in opcoes_150 else 0
                    st.radio("Selecione 15.0:", options=lista_opcoes_150, index=idx150, key=chave_radio_150, on_change=cb_radio_15_0, label_visibility="collapsed")
                    
                with c150_2:
                    link_150 = st.text_area("Link/Evidência (15.0):", value=d150.get("link", ""), key=f"t_150_{ano_sel}", on_change=cb_text_15_0, height=100)
                    placeholder_links_150 = st.empty()
                    links_150_visuais = [u[0] for u in re.findall(regex_pure_url, link_150 or "")]
                    if links_150_visuais:
                        placeholder_links_150.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_150_visuais]))
                        
                st.code("📊 Impacto de Pontuação no Quesito 15.0: 0.0 pontos", language="text")
                bloco_comentarios("15.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_15_0_{ano_sel}", False):
            modal_aviso_link("15.0", st.session_state.get(f"links_pendentes_15_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = False

# --- QUESITO TEXTO 15.1 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_norma_ouvidoria_15_1_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.1 - Instrumento Normativo de Criação", expanded=True):
                st.subheader("15.1 • Instrumento Normativo")
                st.write("**Informe o instrumento normativo de criação da ouvidoria pública, número e data da publicação:**")
                st.info("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o Instrumento Normativo no Sistema de Questionários.*")
                
                d151 = res_data.get("15.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d151 is None: d151 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_composto_texto_15_1():
                    val = st.session_state.get(f"q151_{ano_sel}", d151.get("valor", ""))
                    lnk = st.session_state.get(f"l151_{ano_sel}", d151.get("link", ""))
                    
                    save_resp("15.1", val, 0.0, lnk)
                    res_data["15.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d151.get("link", "") or "")]
                    
                    if lnk != d151.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_15_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = True

                c151_1, c151_2 = st.columns([1, 1])
                with c151_1:
                    st.text_input("Instrumento, número e data:", value=d151.get("valor", ""), key=f"q151_{ano_sel}", on_change=cb_composto_texto_15_1)
                    
                with c151_2:
                    link_151 = st.text_area("Link/Evidência (15.1):", value=d151.get("link", ""), key=f"l151_{ano_sel}", on_change=cb_composto_texto_15_1, height=100)
                    placeholder_links_151 = st.empty()
                    links_151_visuais = [u[0] for u in re.findall(regex_pure_url, link_151 or "")]
                    if links_151_visuais:
                        placeholder_links_151.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_151_visuais]))
                        
                st.code("📊 Impacto de Pontuação no Quesito 15.1: 0.0 pontos", language="text")
                bloco_comentarios("15.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_15_1_{ano_sel}", False):
            modal_aviso_link("15.1", st.session_state.get(f"links_pendentes_15_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = False


        # --- QUESITO TEXTO/LINK 15.2 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_pagina_eletronica_15_2_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.2 - Página Eletrônica do Instrumento", expanded=True):
                st.subheader("15.2 • Página Eletrônica de Divulgação")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do instrumento normativo de criação da Ouvidoria Pública:**")
                st.warning("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ** no campo abaixo.*")
                
                d152 = res_data.get("15.2", {"valor": "", "pontos": 0.0, "link": ""})
                if d152 is None: d152 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_texto_15_2():
                    val = st.session_state.get(f"q152_{ano_sel}", d152.get("valor", ""))
                    # O próprio valor atua como evidência linkable neste cenário
                    save_resp("15.2", val, 0.0, val)
                    res_data["15.2"] = {"valor": val, "pontos": 0.0, "link": val}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d152.get("valor", "") or "")]
                    
                    if val != d152.get("valor", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_15_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_15_2_{ano_sel}"] = True

                c152_1, c152_2 = st.columns([1, 1])
                with c152_1:
                    v152 = st.text_input("Página eletrônica / Link:", value=d152.get("valor", ""), key=f"q152_{ano_sel}", on_change=cb_texto_15_2)
                    
                with c152_2:
                    placeholder_links_152 = st.empty()
                    links_152_visuais = [u[0] for u in re.findall(regex_pure_url, v152 or "")]
                    if links_152_visuais:
                        placeholder_links_152.markdown(f"**Links Ativos Detectados:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_152_visuais]))
                    else:
                        placeholder_links_152.markdown("*Nenhum link ativo detectado no campo ou definido como XYZ.*")
                        
                st.code("📊 Impacto de Pontuação no Quesito 15.2: 0.0 pontos", language="text")
                bloco_comentarios("15.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_15_2_{ano_sel}", False):
            modal_aviso_link("15.2", st.session_state.get(f"links_pendentes_15_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_2_{ano_sel}"] = False


        # --- QUESITO MULTISSELEÇÃO SUBTRATIVO 15.3 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_caracteristicas_15_3_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.3 - Características Estruturais Disponíveis", expanded=True):
                st.subheader("15.3 • Características da Ouvidoria")
                st.write("**Assinale as características que a ouvidoria dispõe para a execução de suas atribuições:**")
                st.caption("ℹ *Cada característica obrigatória não assinalada subtrai -0.5 pontos (Limite máximo de perda: -2.5).*")
                
                caracteristicas_obrigatorias = ["Independência", "Isenção", "Acessibilidade", "Transparência", "Confidencialidade"]
                
                d153 = res_data.get("15.3", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d153 is None: d153 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_153 = eval(d153.get("valor", "[]"))
                    if not isinstance(lista_salva_153, list): lista_salva_153 = []
                except:
                    lista_salva_153 = []

                def cb_composto_multiselecao_15_3():
                    itens_checados = []
                    for opt in caracteristicas_obrigatorias:
                        if st.session_state.get(f"chk_153_{opt}_{ano_sel}", opt in lista_salva_153):
                            itens_checados.append(opt)
                    if st.session_state.get(f"chk_153_outros_{ano_sel}", "Outros" in lista_salva_153):
                        itens_checados.append("Outros")
                        
                    itens_nao_assinalados = sum(1 for x in caracteristicas_obrigatorias if x not in itens_checados)
                    pts = max(-(itens_nao_assinalados * 0.5), -2.5)
                    
                    lnk = st.session_state.get(f"l153_{ano_sel}", d153.get("link", ""))
                    str_lista = str(itens_checados)
                    
                    save_resp("15.3", str_lista, pts, lnk)
                    res_data["15.3"] = {"valor": str_lista, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d153.get("link", "") or "")]
                    
                    if lnk != d153.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_15_3_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_15_3_{ano_sel}"] = True

                c153_1, c153_2 = st.columns([1, 1])
                with c153_1:
                    for item in caracteristicas_obrigatorias:
                        st.checkbox(item, value=item in lista_salva_153, key=f"chk_153_{item}_{ano_sel}", on_change=cb_composto_multiselecao_15_3)
                    st.checkbox("Outros", value="Outros" in lista_salva_153, key=f"chk_153_outros_{ano_sel}", on_change=cb_composto_multiselecao_15_3)
                    
                with c153_2:
                    link_153 = st.text_area("Link/Evidência (15.3):", value=d153.get("link", ""), key=f"l153_{ano_sel}", on_change=cb_composto_multiselecao_15_3, height=180)
                    placeholder_links_153 = st.empty()
                    links_153_visuais = [u[0] for u in re.findall(regex_pure_url, link_153 or "")]
                    if links_153_visuais:
                        placeholder_links_153.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_153_visuais]))
                        
                pts_atuais_153 = d153.get("pontos", 0.0)
                cor_txt = "#28a745" if pts_atuais_153 == 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt}; font-weight:bold;'>📊 Impacto de Pontuação Corrente: {pts_atuais_153:.2f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("15.3", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_15_3_{ano_sel}", False):
            modal_aviso_link("15.3", st.session_state.get(f"links_pendentes_15_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_3_{ano_sel}"] = False


        # --- QUESITO RADIO COM CASCATA DE LIMPEZA INTERNA 15.4 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_relatorio_gestao_15_4_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.4 - Elaboração do Relatório de Gestão", expanded=True):
                st.subheader("15.4 • Relatório de Gestão de Exercício")
                st.write("**A ouvidoria elaborou Relatório de Gestão do exercício de 2025 contendo a consolidação das manifestações encaminhadas pelos usuários de serviços públicos, e com base nelas, apontou falhas e sugeriu melhorias em sua prestação?**")
                st.caption("ℹ *Caso modificado para 'Não', penalização de -10.0 pontos e limpeza de dados nas subseções internas (15.4.1 e 15.4.2).*")
                
                opcoes_154 = {
                    "Selecione...": 0.0,
                    "Sim": 0.0,
                    "Não": -10.0
                }
                
                d154 = res_data.get("15.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d154 is None: d154 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_154 = d154.get("valor", "Selecione...")
                chave_radio_154 = f"r_154_{v_salvo_154}_{ano_sel}"

                def cb_radio_15_4():
                    val = st.session_state[chave_radio_154]
                    pts = opcoes_154.get(val, 0.0)
                    lnk = st.session_state.get(f"l154_{ano_sel}", d154.get("link", ""))
                    
                    save_resp("15.4", val, pts, lnk)
                    res_data["15.4"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    if val == "Não":
                        save_resp("15.4.1", "[]", 0.0, "")
                        save_resp("15.4.2", "Selecione...", 0.0, "")
                        if "15.4.1" in res_data: res_data["15.4.1"] = {"valor": "[]", "pontos": 0.0, "link": ""}
                        if "15.4.2" in res_data: res_data["15.4.2"] = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                def cb_text_15_4():
                    lnk = st.session_state[f"l154_{ano_sel}"]
                    val = st.session_state.get(chave_radio_154, d154.get("valor", "Selecione..."))
                    pts = opcoes_154.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d154.get("link", "") or "")]
                    
                    if val != d154.get("valor", "") or lnk != d154.get("link", ""):
                        save_resp("15.4", val, pts, lnk)
                        res_data["15.4"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d154.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_15_4_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_15_4_{ano_sel}"] = True

                c154_1, c154_2 = st.columns([1, 1])
                with c154_1:
                    lista_opcoes_154 = list(opcoes_154.keys())
                    idx154 = lista_opcoes_154.index(d154.get("valor")) if d154.get("valor") in opcoes_154 else 0
                    st.radio("Selecione 15.4:", options=lista_opcoes_154, index=idx154, key=chave_radio_154, on_change=cb_radio_15_4, label_visibility="collapsed")
                    
                with c154_2:
                    link_154 = st.text_area("Link/Evidência (15.4):", value=d154.get("link", ""), key=f"l154_{ano_sel}", on_change=cb_text_15_4, height=100)
                    placeholder_links_154 = st.empty()
                    links_154_visuais = [u[0] for u in re.findall(regex_pure_url, link_154 or "")]
                    if links_154_visuais:
                        placeholder_links_154.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_154_visuais]))
                        
                pts_atuais_154 = d154.get("pontos", 0.0)
                cor_txt_154 = "#28a745" if pts_atuais_154 == 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_154}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 15.4: {pts_atuais_154:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("15.4", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_15_4_{ano_sel}", False):
            modal_aviso_link("15.4", st.session_state.get(f"links_pendentes_15_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_4_{ano_sel}"] = False

# --- QUESITO MULTISSELEÇÃO SUBTRATIVO 15.4.1 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_info_relatorios_15_4_1_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.4.1 - Informações nos Relatórios Gerenciais", expanded=True):
                st.subheader("15.4.1 • Informações dos Relatórios")
                st.write("**Assinale as informações constantes nos relatórios gerenciais elaborados pela ouvidoria:**")
                st.caption("ℹ *Cada item obrigatório ausente subtrai -2.5 pontos.*")
                
                itens_obrigatorios_1541 = [
                    "Número de manifestações recebidas no exercício anterior",
                    "Motivos das Manifestações",
                    "Análise dos Pontos recorrentes",
                    "Providências adotadas pela administração pública nas soluções apresentadas"
                ]
                
                d1541 = res_data.get("15.4.1", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d1541 is None: d1541 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_1541 = eval(d1541.get("valor", "[]"))
                    if not isinstance(lista_salva_1541, list): lista_salva_1541 = []
                except:
                    lista_salva_1541 = []

                def cb_composto_multiselecao_15_4_1():
                    itens_checados = []
                    for opt in itens_obrigatorios_1541:
                        if st.session_state.get(f"chk_1541_{opt}_{ano_sel}", opt in lista_salva_1541):
                            itens_checados.append(opt)
                            
                    ausentes = sum(1 for x in itens_obrigatorios_1541 if x not in itens_checados)
                    pts = -(ausentes * 2.5)
                    
                    lnk = st.session_state.get(f"l1541_{ano_sel}", d1541.get("link", ""))
                    str_lista = str(itens_checados)
                    
                    save_resp("15.4.1", str_lista, pts, lnk)
                    res_data["15.4.1"] = {"valor": str_lista, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1541.get("link", "") or "")]
                    
                    if lnk != d1541.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_15_4_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_15_4_1_{ano_sel}"] = True

                c1541_1, c1541_2 = st.columns([1, 1])
                with c1541_1:
                    for item in itens_obrigatorios_1541:
                        st.checkbox(item, value=item in lista_salva_1541, key=f"chk_1541_{item}_{ano_sel}", on_change=cb_composto_multiselecao_15_4_1)
                        
                with c1541_2:
                    link_1541 = st.text_area("Link/Evidência (15.4.1):", value=d1541.get("link", ""), key=f"l1541_{ano_sel}", on_change=cb_composto_multiselecao_15_4_1, height=150)
                    placeholder_links_1541 = st.empty()
                    links_1541_visuais = [u[0] for u in re.findall(regex_pure_url, link_1541 or "")]
                    if links_1541_visuais:
                        placeholder_links_1541.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1541_visuais]))
                        
                pts_atuais_1541 = d1541.get("pontos", 0.0)
                cor_txt_1541 = "#28a745" if pts_atuais_1541 == 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_1541}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 15.4.1: {pts_atuais_1541:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("15.4.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_15_4_1_{ano_sel}", False):
            modal_aviso_link("15.4.1", st.session_state.get(f"links_pendentes_15_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_4_1_{ano_sel}"] = False


        # --- QUESITO TEXTO PUNITIVO 15.4.2 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_divulgacao_relatorio_15_4_2_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.4.2 - Link de Divulgação do Relatório de Gestão", expanded=True):
                st.subheader("15.4.2 • Página Eletrônica do Relatório de Gestão")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do Relatório de Gestão do exercício de 2025:**")
                st.warning("⚠️ *Se não estiver disponível na internet, insira explicitamente o texto **XYZ** para anexar manualmente. (Atenção: digitar XYZ aplica uma penalidade de -10 pontos).*")
                
                d1542 = res_data.get("15.4.2", {"valor": "", "pontos": 0.0, "link": ""})
                if d1542 is None: d1542 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_texto_15_4_2():
                    val = st.session_state.get(f"q1542_{ano_sel}", d1542.get("valor", ""))
                    pts = -10.0 if val.strip() == "XYZ" else 0.0
                    
                    save_resp("15.4.2", val, pts, val)
                    res_data["15.4.2"] = {"valor": val, "pontos": pts, "link": val}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1542.get("valor", "") or "")]
                    
                    if val != d1542.get("valor", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_15_4_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_15_4_2_{ano_sel}"] = True

                c1542_1, c1542_2 = st.columns([1, 1])
                with c1542_1:
                    v1542 = st.text_input("Página eletrônica (Link ou XYZ):", value=d1542.get("valor", ""), key=f"q1542_{ano_sel}", on_change=cb_texto_15_4_2)
                    
                with c1542_2:
                    placeholder_links_1542 = st.empty()
                    links_1542_visuais = [u[0] for u in re.findall(regex_pure_url, v1542 or "")]
                    if links_1542_visuais:
                        placeholder_links_1542.markdown(f"**Links Ativos Detectados:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1542_visuais]))
                    else:
                        placeholder_links_1542.markdown("*Nenhum link ativo detectado no campo ou definido como XYZ.*")
                        
                pts_atuais_1542 = d1542.get("pontos", 0.0)
                cor_txt_1542 = "#28a745" if pts_atuais_1542 == 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_1542}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 15.4.2: {pts_atuais_1542:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("15.4.2", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_15_4_2_{ano_sel}", False):
            modal_aviso_link("15.4.2", st.session_state.get(f"links_pendentes_15_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_4_2_{ano_sel}"] = False


        # --- QUESITO MULTISSELEÇÃO SUBTRATIVO 15.5 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_mobilizacao_15_5_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 15.5 - Iniciativas de Divulgação e Mobilização Social", expanded=True):
                st.subheader("15.5 • Divulgação e Mobilização Social")
                st.write("**Assinale as iniciativas de divulgação e mobilização social das ouvidorias:**")
                st.caption("ℹ *Cada item do bloco penalizável ausente subtrai -0.5 pontos da nota total.*")
                
                itens_penalizaveis_155 = [
                    "Link da página eletrônica da ouvidoria no sítio da Prefeitura Municipal",
                    "Utilização de outras plataformas digitais para a divulgação da missão, do modo de trabalho das ouvidorias e incentivando a participação popular. Ex.: instagram, facebook, twiter etc."
                ]
                
                itens_neutros_155 = [
                    "Realização de palestras para grupos e institutions. Ex.: escolas, igrejas, associações civis, outros grupos organizados etc.",
                    "Realização de eventos que estimulem a participação e coleta das demandas sociais. Ex.: realização de audiências públicas para divulgação dos trabalhos desempenhados pela ouvidoria e ouvir as demandas da população."
                ]
                
                d155 = res_data.get("15.5", {"valor": "[]", "pontos": 0.0, "link": ""})
                if d155 is None: d155 = {"valor": "[]", "pontos": 0.0, "link": ""}
                
                try:
                    lista_salva_155 = eval(d155.get("valor", "[]"))
                    if not isinstance(lista_salva_155, list): lista_salva_155 = []
                except:
                    lista_salva_155 = []

                def cb_composto_multiselecao_15_5():
                    itens_checados = []
                    for idx, item in enumerate(itens_penalizaveis_155):
                        if st.session_state.get(f"chk_155_pen_{idx}_{ano_sel}", item in lista_salva_155):
                            itens_checados.append(item)
                    for idx, item in enumerate(itens_neutros_155):
                        if st.session_state.get(f"chk_155_neu_{idx}_{ano_sel}", item in lista_salva_155):
                            itens_checados.append(item)
                    if st.session_state.get(f"chk_155_outras_{ano_sel}", "Outras" in lista_salva_155):
                        itens_checados.append("Outras")
                        
                    ausentes = sum(1 for x in itens_penalizaveis_155 if x not in itens_checados)
                    pts = -(ausentes * 0.5)
                    
                    lnk = st.session_state.get(f"l155_{ano_sel}", d155.get("link", ""))
                    str_lista = str(itens_checados)
                    
                    save_resp("15.5", str_lista, pts, lnk)
                    res_data["15.5"] = {"valor": str_lista, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d155.get("link", "") or "")]
                    
                    if lnk != d155.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_15_5_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_15_5_{ano_sel}"] = True

                c155_1, c155_2 = st.columns([1, 1])
                with c155_1:
                    st.markdown("**Itens de Preenchimento Obrigatório (Sujeitos a Perda):**")
                    for idx, item in enumerate(itens_penalizaveis_155):
                        st.checkbox(item, value=item in lista_salva_155, key=f"chk_155_pen_{idx}_{ano_sel}", on_change=cb_composto_multiselecao_15_5)
                        
                    st.markdown("**Iniciativas Complementares (Neutras):**")
                    for idx, item in enumerate(itens_neutros_155):
                        st.checkbox(item, value=item in lista_salva_155, key=f"chk_155_neu_{idx}_{ano_sel}", on_change=cb_composto_multiselecao_15_5)
                    st.checkbox("Outras", value="Outras" in lista_salva_155, key=f"chk_155_outras_{ano_sel}", on_change=cb_composto_multiselecao_15_5)
                    
                with c155_2:
                    link_155 = st.text_area("Link/Evidência (15.5):", value=d155.get("link", ""), key=f"l155_{ano_sel}", on_change=cb_composto_multiselecao_15_5, height=200)
                    placeholder_links_155 = st.empty()
                    links_155_visuais = [u[0] for u in re.findall(regex_pure_url, link_155 or "")]
                    if links_155_visuais:
                        placeholder_links_155.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_155_visuais]))
                        
                pts_atuais_155 = d155.get("pontos", 0.0)
                cor_txt_155 = "#28a745" if pts_atuais_155 == 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_155}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 15.5: {pts_atuais_155:.2f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("15.5", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_15_5_{ano_sel}", False):
            modal_aviso_link("15.5", st.session_state.get(f"links_pendentes_15_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_15_5_{ano_sel}"] = False


        # =========================================================================
        # GRUPO 16 - CARTA DE SERVIÇOS AO USUÁRIO
        # =========================================================================
        st.markdown("## 📜 GRUPO 16 - CARTA DE SERVIÇOS AO USUÁRIO")

        # --- QUESITO MASTER 16.0 • INDEPENDENTE ---
        with st.container(key=f"container_bloco_carta_master_16_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 16.0 - Elaboração da Carta de Serviços", expanded=True):
                st.subheader("16.0 • Carta de Serviço ao Usuário")
                st.write("**A prefeitura elaborou a \"Carta de Serviço ao Usuário\", que trata dos serviços prestados pelos seus órgãos e entidades, as formas de acesso a esses serviços e seus compromissos e padrões de qualidade de atendimento ao público, conforme artigo 7°, §§ 2º e 3º, da Lei Federal nº 13.460/2017?**")
                st.caption("ℹ *Se modificado para 'Não', o quesito filho 16.1 será limpo e preenchido com 'XYZ' internamente, mantendo-se visível.*")
                
                opc160 = {"Selecione...": 0.0, "Sim – 04": 4.0, "Não – 00": 0.0}
                
                d160 = res_data.get("16.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d160 is None: d160 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_160 = d160.get("valor", "Selecione...")
                chave_radio_160 = f"r_160_{v_salvo_160}_{ano_sel}"

                def cb_radio_16_0():
                    val = st.session_state[chave_radio_160]
                    pts = opc160.get(val, 0.0)
                    lnk = st.session_state.get(f"l160_{ano_sel}", d160.get("link", ""))
                    
                    save_resp("16.0", val, pts, lnk)
                    res_data["16.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    if "Não" in val:
                        save_resp("16.1", "XYZ", 0.0, "")
                        if "16.1" in res_data: res_data["16.1"] = {"valor": "XYZ", "pontos": 0.0, "link": ""}

                def cb_text_16_0():
                    lnk = st.session_state[f"l160_{ano_sel}"]
                    val = st.session_state.get(chave_radio_160, d160.get("valor", "Selecione..."))
                    pts = opc160.get(val, 0.0)
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d160.get("link", "") or "")]
                    
                    if val != d160.get("valor", "") or lnk != d160.get("link", ""):
                        save_resp("16.0", val, pts, lnk)
                        res_data["16.0"] = {"valor": val, "pontos": pts, "link": lnk}
                        
                        if lnk != d160.get("link", "") and links_atuais:
                            if links_atuais != links_antigos:
                                st.session_state[f"links_pendentes_16_0_{ano_sel}"] = links_atuais
                                st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = True

                c160_1, c160_2 = st.columns([1, 1])
                with c160_1:
                    lista_opcoes_160 = list(opc160.keys())
                    idx160 = lista_opcoes_160.index(d160.get("valor")) if d160.get("valor") in opc160 else 0
                    st.radio("Selecione 16.0:", options=lista_opcoes_160, index=idx160, key=chave_radio_160, on_change=cb_radio_16_0, label_visibility="collapsed")
                    
                with c160_2:
                    link_160 = st.text_area("Link/Evidência (16.0):", value=d160.get("link", ""), key=f"l160_{ano_sel}", on_change=cb_text_16_0, height=100)
                    placeholder_links_160 = st.empty()
                    links_160_visuais = [u[0] for u in re.findall(regex_pure_url, link_160 or "")]
                    if links_160_visuais:
                        placeholder_links_160.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_160_visuais]))
                        
                pts_atuais_160 = d160.get("pontos", 0.0)
                cor_txt_160 = "#28a745" if pts_atuais_160 > 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_160}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.0: {pts_atuais_160:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("16.0", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_16_0_{ano_sel}", False):
            modal_aviso_link("16.0", st.session_state.get(f"links_pendentes_16_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = False


        # --- QUESITO FILHO 16.1 • TOTALMENTE VISÍVEL E INDEPENDENTE NA TELA ---
        with st.container(key=f"container_bloco_pagina_carta_16_1_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 16.1 - Página Eletrônica de Divulgação da Carta", expanded=True):
                st.subheader("16.1 • Página Eletrônica da Carta de Serviços")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da \"Carta de Serviço ao Usuário\":**")
                st.warning("⚠️ *Se não estiver disponível, insira exatamente o texto **XYZ**.*")
                
                d161 = res_data.get("16.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d161 is None: d161 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_texto_16_1():
                    val = st.session_state.get(f"q161_{ano_sel}", d161.get("valor", ""))
                    pts = 2.0 if val and val.strip() != "XYZ" else 0.0
                    
                    save_resp("16.1", val, pts, val)
                    res_data["16.1"] = {"valor": val, "pontos": pts, "link": val}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d161.get("valor", "") or "")]
                    
                    if val != d161.get("valor", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_16_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_16_1_{ano_sel}"] = True

                c161_1, c161_2 = st.columns([1, 1])
                with c161_1:
                    v161 = st.text_input("Página eletrônica (Link ou XYZ):", value=d161.get("valor", ""), key=f"q161_{ano_sel}", on_change=cb_texto_16_1)
                    
                with c161_2:
                    placeholder_links_161 = st.empty()
                    links_161_visuais = [u[0] for u in re.findall(regex_pure_url, v161 or "")]
                    if links_161_visuais:
                        placeholder_links_161.markdown(f"**Links Ativos Detectados:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_161_visuais]))
                    else:
                        placeholder_links_161.markdown("*Nenhum link ativo detectado no campo ou definido como XYZ.*")
                        
                pts_atuais_161 = d161.get("pontos", 0.0)
                cor_txt_161 = "#28a745" if pts_atuais_161 > 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_161}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.1: {pts_atuais_161:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("16.1", res_data, ano_sel)

        if st.session_state.get(f"gatilho_modal_16_1_{ano_sel}", False):
            modal_aviso_link("16.1", st.session_state.get(f"links_pendentes_16_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_1_{ano_sel}"] = False

# --- QUESITO MASTER RADIO 16.2 • MODELADO IGUAL AO 16.0 ---
        with st.container(key=f"container_bloco_carta_atualizada_16_2_final_{ano_sel}", border=True):
            with st.expander(f"🗂 Quesito 16.2 - Atualização da Carta de Serviços", expanded=True):
                st.subheader("16.2 • Atualização da Carta")
                st.write("**A 'Carta de Serviço ao Usuário' está atualizada?**")
                
                map_opcoes_162 = {"Selecione...": 0.0, "Sim – 02": 2.0, "Não – 00": 0.0}
                
                d162 = res_data.get("16.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d162 is None: d162 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                # Conversão/ajuste para bater com o padrão de exibição antigo se necessário
                v_salvo_162 = d162.get("valor", "Selecione...")
                if v_salvo_162 == "Sim": v_salvo_162 = "Sim – 02"
                elif v_salvo_162 == "Não": v_salvo_162 = "Não – 00"
                
                chave_radio_162 = f"r_162_{v_salvo_162}_{ano_sel}"

                def cb_radio_16_2():
                    val = st.session_state[chave_radio_162]
                    pts = map_opcoes_162.get(val, 0.0)
                    lnk = st.session_state.get(f"l162_{ano_sel}", d162.get("link", ""))
                    
                    # Salva o valor puro ("Sim" ou "Não") para manter compatibilidade com seu banco
                    val_salvar = "Sim" if "Sim" in val else ("Não" if "Não" in val else "Selecione...")
                    save_resp("16.2", val_salvar, pts, lnk)
                    res_data["16.2"] = {"valor": val_salvar, "pontos": pts, "link": lnk}

                def cb_text_16_2():
                    lnk = st.session_state[f"l162_{ano_sel}"]
                    val = st.session_state.get(chave_radio_162, v_salvo_162)
                    pts = map_opcoes_162.get(val, 0.0)
                    
                    val_salvar = "Sim" if "Sim" in val else ("Não" if "Não" in val else "Selecione...")
                    save_resp("16.2", val_salvar, pts, lnk)
                    res_data["16.2"] = {"valor": val_salvar, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d162.get("link", "") or "")]
                    
                    if lnk != d162.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_16_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_16_2_{ano_sel}"] = True

                c162_1, c162_2 = st.columns([1, 1])
                with c162_1:
                    lista_opcoes_162 = list(map_opcoes_162.keys())
                    idx162 = lista_opcoes_162.index(v_salvo_162) if v_salvo_162 in lista_opcoes_162 else 0
                    st.radio("Selecione 16.2:", options=lista_opcoes_162, index=idx162, key=chave_radio_162, on_change=cb_radio_16_2, label_visibility="collapsed")
                    
                with c162_2:
                    link_162 = st.text_area("Link/Evidência (16.2):", value=d162.get("link", ""), key=f"l162_{ano_sel}", on_change=cb_text_16_2, height=100)
                    placeholder_links_162 = st.empty()
                    links_162_visuais = [u[0] for u in re.findall(regex_pure_url, link_162 or "")]
                    if links_162_visuais:
                        placeholder_links_162.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_162_visuais]))
                        
                pts_atuais_162 = d162.get("pontos", 0.0)
                cor_txt_162 = "#28a745" if pts_atuais_162 > 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_162}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.2: {pts_atuais_162:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("16.2", res_data, ano_sel)

        # GATILHO DO MODAL 16.2
        if st.session_state.get(f"gatilho_modal_16_2_{ano_sel}", False):
            modal_aviso_link("16.2", st.session_state.get(f"links_pendentes_16_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_2_{ano_sel}"] = False


        # --- QUESITO MASTER RADIO 16.3 • MODELADO IGUAL AO 16.0 (COM CASCATA) ---
        with st.container(key=f"container_bloco_regulamentacao_16_3_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 16.3 - Regulamentação da Carta de Serviços", expanded=True):
                st.subheader("16.3 • Regulamentação da Carta")
                st.write("**A prefeitura regulamentou a operacionalização da Carta de Serviços ao Usuário, conforme o artigo 7°, § 5°, da Lei Federal n° 13.460/2017?**")
                st.caption("ℹ *Caso modificado para 'Não', haverá cascata de limpeza automática nas subseções internas (16.3.1 e 16.3.2).*")
                
                opc163 = {"Selecione...": 0.0, "Sim – 04": 4.0, "Não – 00": 0.0}
                
                d163 = res_data.get("16.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d163 is None: d163 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_163 = d163.get("valor", "Selecione...")
                if v_salvo_163 == "Sim": v_salvo_163 = "Sim – 04"
                elif v_salvo_163 == "Não": v_salvo_163 = "Não – 00"
                
                chave_radio_163 = f"r_163_{v_salvo_163}_{ano_sel}"

                def cb_radio_16_3():
                    val = st.session_state[chave_radio_163]
                    pts = opc163.get(val, 0.0)
                    lnk = st.session_state.get(f"l163_{ano_sel}", d163.get("link", ""))
                    
                    val_salvar = "Sim" if "Sim" in val else ("Não" if "Não" in val else "Selecione...")
                    save_resp("16.3", val_salvar, pts, lnk)
                    res_data["16.3"] = {"valor": val_salvar, "pontos": pts, "link": lnk}
                    
                    if "Não" in val:
                        save_resp("16.3.1", "", 0.0, "")
                        save_resp("16.3.2", "", 0.0, "")
                        if "16.3.1" in res_data: res_data["16.3.1"] = {"valor": "", "pontos": 0.0, "link": ""}
                        if "16.3.2" in res_data: res_data["16.3.2"] = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_text_16_3():
                    lnk = st.session_state[f"l163_{ano_sel}"]
                    val = st.session_state.get(chave_radio_163, v_salvo_163)
                    pts = opc163.get(val, 0.0)
                    
                    val_salvar = "Sim" if "Sim" in val else ("Não" if "Não" in val else "Selecione...")
                    save_resp("16.3", val_salvar, pts, lnk)
                    res_data["16.3"] = {"valor": val_salvar, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d163.get("link", "") or "")]
                    
                    if lnk != d163.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_16_3_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_16_3_{ano_sel}"] = True

                c163_1, c163_2 = st.columns([1, 1])
                with c163_1:
                    lista_opcoes_163 = list(opc163.keys())
                    idx163 = lista_opcoes_163.index(v_salvo_163) if v_salvo_163 in lista_opcoes_163 else 0
                    st.radio("Selecione 16.3:", options=lista_opcoes_163, index=idx163, key=chave_radio_163, on_change=cb_radio_16_3, label_visibility="collapsed")
                    
                with c163_2:
                    link_163 = st.text_area("Link/Evidência (16.3):", value=d163.get("link", ""), key=f"l163_{ano_sel}", on_change=cb_text_16_3, height=100)
                    placeholder_links_163 = st.empty()
                    links_163_visuais = [u[0] for u in re.findall(regex_pure_url, link_163 or "")]
                    if links_163_visuais:
                        placeholder_links_163.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_163_visuais]))
                        
                pts_atuais_163 = d163.get("pontos", 0.0)
                cor_txt_163 = "#28a745" if pts_atuais_163 > 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_163}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.3: {pts_atuais_163:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("16.3", res_data, ano_sel)

        # GATILHO DO MODAL 16.3
        if st.session_state.get(f"gatilho_modal_16_3_{ano_sel}", False):
            modal_aviso_link("16.3", st.session_state.get(f"links_pendentes_16_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_3_{ano_sel}"] = False

# --- QUESITO TEXTUAL FILHO 16.3.1 • MODELADO IGUAL AO 16.0 ---
        with st.container(key=f"container_bloco_norma_detalhe_16_3_1_final_{ano_sel}", border=True):
            with st.expander(f"📑 Quesito 16.3.1 - Detalhes do Instrumento Normativo", expanded=True):
                st.subheader("16.3.1 • Dados do Instrumento")
                st.write("**Informe o instrumento normativo que regulamentou a 'Carta de Serviço ao Usuário', Número e Data da publicação:**")
                st.info("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o Instrumento Normativo de regulamentação no Sistema de Questionários.*")
                
                d1631 = res_data.get("16.3.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d1631 is None: d1631 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_input_16_3_1():
                    v_txt = st.session_state[f"q1631_{ano_sel}"]
                    lnk = st.session_state.get(f"l1631_{ano_sel}", d1631.get("link", ""))
                    save_resp("16.3.1", v_txt, 0.0, lnk)
                    res_data["16.3.1"] = {"valor": v_txt, "pontos": 0.0, "link": lnk}

                def cb_text_16_3_1():
                    lnk = st.session_state[f"l1631_{ano_sel}"]
                    v_txt = st.session_state.get(f"q1631_{ano_sel}", d1631.get("valor", ""))
                    
                    save_resp("16.3.1", v_txt, 0.0, lnk)
                    res_data["16.3.1"] = {"valor": v_txt, "pontos": 0.0, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1631.get("link", "") or "")]
                    
                    if lnk != d1631.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_16_3_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_16_3_1_{ano_sel}"] = True

                c1631_1, c1631_2 = st.columns([1, 1])
                with c1631_1:
                    st.text_input("Instrumento normativo, número e data:", value=d1631.get("valor", ""), key=f"q1631_{ano_sel}", on_change=cb_input_16_3_1)
                    
                with c1631_2:
                    link_1631 = st.text_area("Link/Evidência (16.3.1):", value=d1631.get("link", ""), key=f"l1631_{ano_sel}", on_change=cb_text_16_3_1, height=100)
                    placeholder_links_1631 = st.empty()
                    links_1631_visuais = [u[0] for u in re.findall(regex_pure_url, link_1631 or "")]
                    if links_1631_visuais:
                        placeholder_links_1631.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1631_visuais]))
                        
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.3.1: 0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("16.3.1", res_data, ano_sel)

        # GATILHO DO MODAL 16.3.1
        if st.session_state.get(f"gatilho_modal_16_3_1_{ano_sel}", False):
            modal_aviso_link("16.3.1", st.session_state.get(f"links_pendentes_16_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_3_1_{ano_sel}"] = False


        # --- QUESITO TEXTUAL FILHO 16.3.2 • MODELADO IGUAL AO 16.0 ---
        with st.container(key=f"container_bloco_url_norma_16_3_2_final_{ano_sel}", border=True):
            with st.expander(f"🔗 Quesito 16.3.2 - Endereço Eletrônico da Regulamentação", expanded=True):
                st.subheader("16.3.2 • Endereço Eletrônico da Norma")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do instrumento normativo que regulamentou a 'Carta de Serviço ao Usuário':**")
                st.warning("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ** no campo abaixo.*")
                
                d1632 = res_data.get("16.3.2", {"valor": "", "pontos": 0.0, "link": ""})
                if d1632 is None: d1632 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_input_16_3_2():
                    v_txt = st.session_state[f"q1632_{ano_sel}"]
                    # Neste formato, o próprio valor inserido atua como o link/evidência histórica
                    save_resp("16.3.2", v_txt, 0.0, v_txt)
                    res_data["16.3.2"] = {"valor": v_txt, "pontos": 0.0, "link": v_txt}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, v_txt or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d1632.get("valor", "") or "")]
                    
                    if v_txt != d1632.get("valor", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_16_3_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_16_3_2_{ano_sel}"] = True

                c1632_1, c1632_2 = st.columns([1, 1])
                with c1632_1:
                    v_campo_1632 = st.text_input("Página eletrônica (Link ou XYZ) do instrumento:", value=d1632.get("valor", ""), key=f"q1632_{ano_sel}", on_change=cb_input_16_3_2)
                    
                with c1632_2:
                    placeholder_links_1632 = st.empty()
                    links_1632_visuais = [u[0] for u in re.findall(regex_pure_url, v_campo_1632 or "")]
                    if links_1632_visuais:
                        placeholder_links_1632.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_1632_visuais]))
                    else:
                        placeholder_links_1632.markdown("*Nenhum link ativo detectado no campo.*")
                        
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 16.3.2: 0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("16.3.2", res_data, ano_sel)

        # GATILHO DO MODAL 16.3.2
        if st.session_state.get(f"gatilho_modal_16_3_2_{ano_sel}", False):
            modal_aviso_link("16.3.2", st.session_state.get(f"links_pendentes_16_3_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_16_3_2_{ano_sel}"] = False


        # =========================================================================
        # GRUPO 17 - CONSELHO DE USUÁRIOS
        # =========================================================================
        st.markdown("## 👥 GRUPO 17 - CONSELHO DE USUÁRIOS")

        # --- QUESITO MASTER RADIO 17.0 • MODELADO IGUAL AO 16.0 (COM CASCATA) ---
        with st.container(key=f"container_bloco_conselho_master_17_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 17.0 - Regulamentação do Conselho de Usuários", expanded=True):
                st.subheader("17.0 • Regulamentação e Instituição")
                st.write("**A prefeitura regulamentou e instituiu o Conselho de Usuários, nos termos definidos nos artigos 18 a 21 da Lei Federal nº 13.460/2017?**")
                st.caption("ℹ *Se modificado para 'Não', as subseções filhas (17.1 e 17.2) serão automaticamente limpas via cascata.*")
                
                opc170 = {"Selecione...": 0.0, "Sim – 04": 4.0, "Não – 00": 0.0}
                
                d170 = res_data.get("17.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d170 is None: d170 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_170 = d170.get("valor", "Selecione...")
                if v_salvo_170 == "Sim": v_salvo_170 = "Sim – 04"
                elif v_salvo_170 == "Não": v_salvo_170 = "Não – 00"
                
                chave_radio_170 = f"r_170_{v_salvo_170}_{ano_sel}"

                def cb_radio_170():
                    val = st.session_state[chave_radio_170]
                    pts = opc170.get(val, 0.0)
                    lnk = st.session_state.get(f"l170_final_txt_{ano_sel}", d170.get("link", ""))
                    
                    val_salvar = "Sim" if "Sim" in val else ("Não" if "Não" in val else "Selecione...")
                    save_resp("17.0", val_salvar, pts, lnk)
                    res_data["17.0"] = {"valor": val_salvar, "pontos": pts, "link": lnk}
                    
                    if "Não" in val:
                        save_resp("17.1", "", 0.0, "")
                        save_resp("17.2", "", 0.0, "")
                        if "17.1" in res_data: res_data["17.1"] = {"valor": "", "pontos": 0.0, "link": ""}
                        if "17.2" in res_data: res_data["17.2"] = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_text_170():
                    lnk = st.session_state[f"l170_final_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_170, v_salvo_170)
                    pts = opc170.get(val, 0.0)
                    
                    val_salvar = "Sim" if "Sim" in val else ("Não" if "Não" in val else "Selecione...")
                    save_resp("17.0", val_salvar, pts, lnk)
                    res_data["17.0"] = {"valor": val_salvar, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d170.get("link", "") or "")]
                    
                    if lnk != d170.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_17_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_17_0_{ano_sel}"] = True

                c170_1, c170_2 = st.columns([1, 1])
                with c170_1:
                    lista_opcoes_170 = list(opc170.keys())
                    idx170 = lista_opcoes_170.index(v_salvo_170) if v_salvo_170 in lista_opcoes_170 else 0
                    st.radio("Selecione 17.0:", options=lista_opcoes_170, index=idx170, key=chave_radio_170, on_change=cb_radio_170, label_visibility="collapsed")
                    
                with c170_2:
                    link_170 = st.text_area("Link/Evidência (17.0):", value=d170.get("link", ""), key=f"l170_final_txt_{ano_sel}", on_change=cb_text_170, height=100)
                    placeholder_links_170 = st.empty()
                    links_170_visuais = [u[0] for u in re.findall(regex_pure_url, link_170 or "")]
                    if links_170_visuais:
                        placeholder_links_170.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_170_visuais]))
                        
                pts_atuais_170 = d170.get("pontos", 0.0)
                cor_txt_170 = "#28a745" if pts_atuais_170 > 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_170}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 17.0: {pts_atuais_170:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("17.0_exclusivo_g17", res_data, ano_sel)

        # GATILHO DO MODAL 17.0
        if st.session_state.get(f"gatilho_modal_17_0_{ano_sel}", False):
            modal_aviso_link("17.0", st.session_state.get(f"links_pendentes_17_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_0_{ano_sel}"] = False

# --- QUESITO TEXTUAL FILHO 17.1 • MODELADO IGUAL AO 16.0 ---
        with st.container(key=f"container_bloco_norma_conselho_17_1_final_{ano_sel}", border=True):
            with st.expander(f"📑 Quesito 17.1 - Detalhes do Instrumento Normativo do Conselho", expanded=True):
                st.subheader("17.1 • Dados do Instrumento")
                st.write("**Informe o instrumento normativo que regulamentou os Conselhos de Usuários, Número e Data da publicação:**")
                st.info("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o Instrumento Normativo no Sistema de Questionários.*")
                
                d171 = res_data.get("17.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d171 is None: d171 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_input_17_1():
                    v_txt = st.session_state[f"q171_final_input_{ano_sel}"]
                    lnk = st.session_state.get(f"l171_final_input_{ano_sel}", d171.get("link", ""))
                    save_resp("17.1", v_txt, 0.0, lnk)
                    res_data["17.1"] = {"valor": v_txt, "pontos": 0.0, "link": lnk}

                def cb_text_17_1():
                    lnk = st.session_state[f"l171_final_input_{ano_sel}"]
                    v_txt = st.session_state.get(f"q171_final_input_{ano_sel}", d171.get("valor", ""))
                    
                    save_resp("17.1", v_txt, 0.0, lnk)
                    res_data["17.1"] = {"valor": v_txt, "pontos": 0.0, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d171.get("link", "") or "")]
                    
                    if lnk != d171.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_17_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_17_1_{ano_sel}"] = True

                c171_1, c171_2 = st.columns([1, 1])
                with c171_1:
                    st.text_input("Instrumento normativo, número e data:", value=d171.get("valor", ""), key=f"q171_final_input_{ano_sel}", on_change=cb_input_17_1)
                    
                with c171_2:
                    link_171 = st.text_area("Link/Evidência (17.1):", value=d171.get("link", ""), key=f"l171_final_input_{ano_sel}", on_change=cb_text_17_1, height=100)
                    placeholder_links_171 = st.empty()
                    links_171_visuais = [u[0] for u in re.findall(regex_pure_url, link_171 or "")]
                    if links_171_visuais:
                        placeholder_links_171.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_171_visuais]))
                        
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 17.1: 0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("17.1_exclusivo_g17", res_data, ano_sel)

        # GATILHO DO MODAL 17.1
        if st.session_state.get(f"gatilho_modal_17_1_{ano_sel}", False):
            modal_aviso_link("17.1", st.session_state.get(f"links_pendentes_17_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_1_{ano_sel}"] = False


        # --- QUESITO TEXTUAL FILHO 17.2 • MODELADO IGUAL AO 16.0 ---
        with st.container(key=f"container_bloco_url_conselho_17_2_final_{ano_sel}", border=True):
            with st.expander(f"🔗 Quesito 17.2 - Endereço Eletrônico do Conselho", expanded=True):
                st.subheader("17.2 • Endereço Eletrônico da Norma")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da regulamentação do Conselho de Usuários:**")
                st.warning("⚠️ *Se não estiver disponível na internet, insira exatamente o texto **XYZ** no campo abaixo.*")
                
                d172 = res_data.get("17.2", {"valor": "", "pontos": 0.0, "link": ""})
                if d172 is None: d172 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_input_17_2():
                    v_txt = st.session_state[f"q172_final_input_{ano_sel}"]
                    save_resp("17.2", v_txt, 0.0, v_txt)
                    res_data["17.2"] = {"valor": v_txt, "pontos": 0.0, "link": v_txt}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, v_txt or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d172.get("valor", "") or "")]
                    
                    if v_txt != d172.get("valor", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_17_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_17_2_{ano_sel}"] = True

                c172_1, c172_2 = st.columns([1, 1])
                with c172_1:
                    v_campo_172 = st.text_input("Página eletrônica (Link ou XYZ):", value=d172.get("valor", ""), key=f"q172_final_input_{ano_sel}", on_change=cb_input_17_2)
                    
                with c172_2:
                    placeholder_links_172 = st.empty()
                    links_172_visuais = [u[0] for u in re.findall(regex_pure_url, v_campo_172 or "")]
                    if links_172_visuais:
                        placeholder_links_172.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_172_visuais]))
                    else:
                        placeholder_links_172.markdown("*Nenhum link ativo detectado no campo.*")
                        
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 17.2: 0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("17.2_exclusivo_g17", res_data, ano_sel)

        # GATILHO DO MODAL 17.2
        if st.session_state.get(f"gatilho_modal_17_2_{ano_sel}", False):
            modal_aviso_link("17.2", st.session_state.get(f"links_pendentes_17_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_17_2_{ano_sel}"] = False


        # =========================================================================
        # GRUPO 8 - PLANO DIRETOR
        # =========================================================================
        st.markdown("## 🏗️ GRUPO 8 - PLANO DIRETOR")
        from datetime import datetime, date

        # --- QUESITO MASTER RADIO 18.0 • MODELADO IGUAL AO 16.0 (COM CASCATA) ---
        with st.container(key=f"container_bloco_plano_diretor_master_18_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 18.0 - Elaboração do Plano Diretor", expanded=True):
                st.subheader("18.0 • Elaboração")
                st.write("**O município elaborou Plano Diretor conforme Lei nº 10.257/01?**")
                st.caption("ℹ *Se modificado para um valor diferente de 'Sim', a data de atualização do quesito filho 18.1 será limpa.*")
                
                opc180 = {"Selecione...": 0.0, "Sim": 0.0, "Não": 0.0, "Não se aplica": 0.0}
                
                d180 = res_data.get("18.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d180 is None: d180 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}

                v_salvo_180 = d180.get("valor", "Selecione...")
                chave_radio_180 = f"r_180_{v_salvo_180}_{ano_sel}"

                def cb_radio_18_0():
                    val = st.session_state[chave_radio_180]
                    pts = opc180.get(val, 0.0)
                    lnk = st.session_state.get(f"l80_txt_final_{ano_sel}", d180.get("link", ""))
                    
                    save_resp("18.0", val, pts, lnk)
                    res_data["18.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    if val != "Sim":
                        save_resp("18.1", "", 0.0, "")
                        if "18.1" in res_data: res_data["18.1"] = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_text_18_0():
                    lnk = st.session_state[f"l80_txt_final_{ano_sel}"]
                    val = st.session_state.get(chave_radio_180, v_salvo_180)
                    pts = opc180.get(val, 0.0)
                    
                    save_resp("18.0", val, pts, lnk)
                    res_data["18.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d180.get("link", "") or "")]
                    
                    if lnk != d180.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_18_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_18_0_{ano_sel}"] = True

                c180_1, c180_2 = st.columns([1, 1])
                with c180_1:
                    lista_opcoes_180 = list(opc180.keys())
                    idx180 = lista_opcoes_180.index(v_salvo_180) if v_salvo_180 in lista_opcoes_180 else 0
                    st.radio("Selecione 18.0:", options=lista_opcoes_180, index=idx180, key=chave_radio_180, on_change=cb_radio_18_0, label_visibility="collapsed")
                    
                with c180_2:
                    link_180 = st.text_area("Link/Evidência (18.0):", value=d180.get("link", ""), key=f"l80_txt_final_{ano_sel}", on_change=cb_text_18_0, height=100)
                    placeholder_links_180 = st.empty()
                    links_180_visuais = [u[0] for u in re.findall(regex_pure_url, link_180 or "")]
                    if links_180_visuais:
                        placeholder_links_180.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_180_visuais]))
                        
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 18.0: 0.0 pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("18.0_exclusivo_g8", res_data, ano_sel)

        # GATILHO DO MODAL 18.0
        if st.session_state.get(f"gatilho_modal_18_0_{ano_sel}", False):
            modal_aviso_link("18.0", st.session_state.get(f"links_pendentes_18_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_18_0_{ano_sel}"] = False


        # --- QUESITO DATA FILHO 18.1 • TOTALMENTE INDEPENDENTE ---
        with st.container(key=f"container_bloco_data_plano_18_1_final_{ano_sel}", border=True):
            with st.expander(f"📅 Quesito 18.1 - Data de Atualização do Plano Diretor", expanded=True):
                st.subheader("18.1 • Última Atualização")
                st.write("**Informe a data da última atualização do Plano Diretor:**")
                st.info("ℹ️ **Fórmula de Cálculo:**\n* 📅 **Até 31/12/2015:** -10.0 pontos.\n* 📅 **A partir de 01/01/2016:** 0.0 ponto.")
                
                d181 = res_data.get("18.1", {"valor": "", "pontos": 0.0, "link": ""})
                if d181 is None: d181 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_date_18_1():
                    dt_sel = st.session_state[f"dt181_{ano_sel}"]
                    pts = -10.0 if dt_sel <= date(2015, 12, 31) else 0.0
                    lnk = st.session_state.get(f"l181_{ano_sel}", d181.get("link", ""))
                    
                    save_resp("18.1", str(dt_sel), pts, lnk)
                    res_data["18.1"] = {"valor": str(dt_sel), "pontos": pts, "link": lnk}

                def cb_text_18_1():
                    lnk = st.session_state[f"l181_{ano_sel}"]
                    dt_sel = st.session_state.get(f"dt181_{ano_sel}", date.today())
                    pts = -10.0 if dt_sel <= date(2015, 12, 31) else 0.0
                    
                    save_resp("18.1", str(dt_sel), pts, lnk)
                    res_data["18.1"] = {"valor": str(dt_sel), "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d181.get("link", "") or "")]
                    
                    if lnk != d181.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_18_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_18_1_{ano_sel}"] = True

                try:
                    dt_inicial = datetime.strptime(d181["valor"], '%Y-%m-%d').date() if d181["valor"] else date.today()
                except:
                    dt_inicial = date.today()

                c181_1, c181_2 = st.columns([1, 1])
                with c181_1:
                    st.date_input("Data da última atualização:", value=dt_inicial, key=f"dt181_{ano_sel}", format="DD/MM/YYYY", on_change=cb_date_18_1)
                    
                with c181_2:
                    link_181 = st.text_area("Justificativa / Link de Evidência (18.1):", value=d181.get("link", ""), key=f"l181_{ano_sel}", on_change=cb_text_18_1, height=100)
                    placeholder_links_181 = st.empty()
                    links_181_visuais = [u[0] for u in re.findall(regex_pure_url, link_181 or "")]
                    if links_181_visuais:
                        placeholder_links_181.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_181_visuais]))

                pts_atuais_181 = d181.get("pontos", 0.0)
                cor_txt_181 = "#dc3545" if pts_atuais_181 == -10.0 else "#28a745"
                st.markdown(f"<span style='color:{cor_txt_181}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 18.1: {pts_atuais_181:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("18.1_exclusivo_g8", res_data, ano_sel)

        # GATILHO DO MODAL 18.1
        if st.session_state.get(f"gatilho_modal_18_1_{ano_sel}", False):
            modal_aviso_link("18.1", st.session_state.get(f"links_pendentes_18_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_18_1_{ano_sel}"] = False

# --- QUESITO INFORMATIVO TEXTUAL 19.0 • MODELADO IGUAL AO 16.0 ---
        st.markdown('---', unsafe_allow_html=True)
        with st.container(key=f"container_bloco_feedback_19_0_final_{ano_sel}", border=True):
            with st.expander(f"💬 Quesito 19.0 - Encerramento e Feedback", expanded=True):
                st.subheader("19.0 • Feedback sobre o Questionário")
                st.write("**Gostaria de registrar suas impressões, comentários e sugestões a respeito do presente questionário?**")
                
                d190 = res_data.get("19.0", {"valor": "", "pontos": 0.0, "link": ""})
                if d190 is None: d190 = {"valor": "", "pontos": 0.0, "link": ""}

                def cb_text_19_0():
                    lnk = st.session_state[f"l190_text_{ano_sel}"]
                    
                    # Salva o texto inserido tanto no valor quanto na evidência por ser puramente informativo
                    save_resp("19.0", lnk, 0.0, lnk)
                    res_data["19.0"] = {"valor": lnk, "pontos": 0.0, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d190.get("link", "") or "")]
                    
                    if lnk != d190.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_19_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_19_0_{ano_sel}"] = True

                c190_1, c190_2 = st.columns([1, 1])
                with c190_1:
                    st.info("💡 **Quesito Informativo**\n\nEste espaço é destinado à melhoria contínua dos nossos processos. Suas respostas não alteram a nota final do município.")
                    st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto de Pontuação: 0.0 pontos</span>", unsafe_allow_html=True)
                    
                with c190_2:
                    link_190 = st.text_area(
                        "Utilize o espaço abaixo para registrar suas observações:",
                        value=d190.get("link", ""),
                        key=f"l190_text_{ano_sel}",
                        placeholder="Digite aqui suas observações, críticas ou sugestões...",
                        on_change=cb_text_19_0,
                        height=140
                    )
                    placeholder_links_190 = st.empty()
                    links_190_visuais = [u[0] for u in re.findall(regex_pure_url, link_190 or "")]
                    if links_190_visuais:
                        placeholder_links_190.markdown(f"**Links Detectados:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_190_visuais]))

                bloco_comentarios("19.0_exclusivo_g19", res_data, ano_sel)

        # GATILHO DO MODAL 19.0
        if st.session_state.get(f"gatilho_modal_19_0_{ano_sel}", False):
            modal_aviso_link("19.0", st.session_state.get(f"links_pendentes_19_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_19_0_{ano_sel}"] = False

        # =============================================================================
        # INDICADOR P3 • PERCENTUAL DE ALTERAÇÃO DO PLANEJAMENTO INICIAL
        # =============================================================================
        with st.container(key=f"container_bloco_indicador_p3_final_{ano_sel}", border=True):
            with st.expander(f"📊 Indicador P3 - Percentual de Alteração do Planejamento Inicial", expanded=True):
                st.subheader("P3 • Avaliação Orçamentária (LOA)")
                st.write("**Informe os valores totais dos programas para cálculo do indicador P3:**")
                
                st.info("""
                ℹ️ **Regra de Pontuação (K = J / I):**
                * 🔴 **K ≥ 1,3:** -30.0 pontos (Perde 30)
                * 🟢 **0,9 < K < 1,3:** 0.0 ponto
                * 🟡 **0,5 < K ≤ 0,9:** Graduação linear entre 0 e -30.0 pontos $\\rightarrow \\left(\\frac{0,9 - K}{0,4}\\right) \\times (-30)$
                * 🔴 **K ≤ 0,5:** -30.0 pontos (Perde 30)
                """)
                
                # Recupera os dados salvos no banco/dicionário
                dP3 = res_data.get("P3", {"valor": "{}", "pontos": 0.0, "link": ""})
                if dP3 is None: dP3 = {"valor": "{}", "pontos": 0.0, "link": ""}
                
                try:
                    valores_p3 = ast.literal_eval(dP3["valor"])
                    if not isinstance(valores_p3, dict): valores_p3 = {}
                except Exception:
                    valores_p3 = {}
                    
                v_j_salvo = valores_p3.get("J", 0.0)
                v_i_salvo = valores_p3.get("I", 0.0)

                def cb_calculo_p3():
                    # Captura os dados atuais da interface pelos states
                    j = st.session_state[f"num_p3_j_{ano_sel}"]
                    i = st.session_state[f"num_p3_i_{ano_sel}"]
                    lnk = st.session_state.get(f"l_p3_txt_{ano_sel}", dP3.get("link", ""))
                    
                    # Lógica de cálculo do Indicador K
                    if i > 0:
                        k = j / i
                        if k >= 1.3:
                            pts = -30.0
                        elif 0.9 < k < 1.3:
                            pts = 0.0
                        elif 0.5 < k <= 0.9:
                            pts = ((0.9 - k) / 0.4) * (-30.0)
                        else: # k <= 0.5
                            pts = -30.0
                    else:
                        k = 0.0
                        pts = 0.0  # Evita divisão por zero ou dados inconsistentes
                        
                    dict_valores = {"J": j, "I": i, "K": round(k, 4)}
                    str_valores = str(dict_valores)
                    
                    # Salva os resultados
                    save_resp("P3", str_valores, pts, lnk)
                    res_data["P3"] = {"valor": str_valores, "pontos": pts, "link": lnk}

                def cb_text_p3():
                    lnk = st.session_state[f"l_p3_txt_{ano_sel}"]
                    j = st.session_state.get(f"num_p3_j_{ano_sel}", v_j_salvo)
                    i = st.session_state.get(f"num_p3_i_{ano_sel}", v_i_salvo)
                    
                    if i > 0:
                        k = j / i
                        if k >= 1.3: pts = -30.0
                        elif 0.9 < k < 1.3: pts = 0.0
                        elif 0.5 < k <= 0.9: pts = ((0.9 - k) / 0.4) * (-30.0)
                        else: pts = -30.0
                    else:
                        k = 0.0
                        pts = 0.0
                        
                    dict_valores = {"J": j, "I": i, "K": round(k, 4)}
                    str_valores = str(dict_valores)
                    
                    save_resp("P3", str_valores, pts, lnk)
                    res_data["P3"] = {"valor": str_valores, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, dP3.get("link", "") or "")]
                    
                    if lnk != dP3.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_p3_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_p3_{ano_sel}"] = True

                cP3_1, cP3_2 = st.columns([1, 1])
                with cP3_1:
                    st.number_input("Valor Total Final dos Programas (J):", value=float(v_j_salvo), min_value=0.0, step=1000.0, format="%.2f", key=f"num_p3_j_{ano_sel}", on_change=cb_calculo_p3)
                    st.number_input("Valor Total Inicial dos Programas (I):", value=float(v_i_salvo), min_value=0.0, step=1000.0, format="%.2f", key=f"num_p3_i_{ano_sel}", on_change=cb_calculo_p3)
                    
                    # Exibe o valor de K calculado em tempo real com base no dicionário salvo
                    k_atual = valores_p3.get("K", 0.0)
                    st.metric(label="Resultado do Indicador (K = J / I)", value=f"{k_atual:.4f}")
                    
                with cP3_2:
                    link_p3 = st.text_area("Link de Evidência / Memória de Cálculo (P3):", value=dP3.get("link", ""), key=f"l_p3_txt_{ano_sel}", on_change=cb_text_p3, height=155)
                    placeholder_links_p3 = st.empty()
                    links_p3_visuais = [u[0] for u in re.findall(regex_pure_url, link_p3 or "")]
                    if links_p3_visuais:
                        placeholder_links_p3.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_p3_visuais]))

                pts_atuais_p3 = dP3.get("pontos", 0.0)
                cor_txt_p3 = "#28a745" if pts_atuais_p3 == 0.0 else "#dc3545"
                st.markdown(f"<span style='color:{cor_txt_p3}; font-weight:bold;'>📊 Impacto de Pontuação no Indicador P3: {pts_atuais_p3:.2f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("P3_exclusivo", res_data, ano_sel)

        # GATILHO DO MODAL P3
        if st.session_state.get(f"gatilho_modal_p3_{ano_sel}", False):
            modal_aviso_link("P3", st.session_state.get(f"links_pendentes_p3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_p3_{ano_sel}"] = False

        # =============================================================================
        # INDICADOR P4 • PONTUALIDADE NA ENTREGA DE DOCUMENTOS (AUDESP)
        # =============================================================================
        with st.container(key=f"container_bloco_indicador_p4_final_{ano_sel}", border=True):
            with st.expander(f"📊 Indicador P4 - Pontualidade na Entrega de Documentos (Peças de Planejamento)", expanded=True):
                st.subheader("P4 • Dados Extraídos do Sistema AUDESP")
                st.write("**Os documentos relativos às peças de planejamento (Atas de audiência de avaliação do cumprimento metas, Relatório de Atividades, PPA, LDO e LOA) são entregues no prazo ao Tribunal de Contas do Estado de São Paulo?**")
                st.caption("ℹ *Dados de conformidade extraídos da plataforma AUDESP. Modificações salvam os dados assincronamente.*")
                
                # Mapeamento oficial com pontuações explícitas nas strings das opções
                opcoes_p4 = {
                    "Selecione...": 0.0,
                    "Documentos relativos às Peças de Planejamento entregues no prazo – 150 pontos": 150.0,
                    "Documentos relativos às Peças de Planejamento entregues fora do prazo ou não entregue – 00 pontos": 0.0
                }
                
                # Recupera o estado salvo usando a chave padronizada "P4"
                dP4 = res_data.get("P4", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if dP4 is None: dP4 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_p4 = dP4.get("valor", "Selecione...")
                chave_radio_p4 = f"r_p4_{v_salvo_p4}_{ano_sel}"

                def cb_radio_p4():
                    val = st.session_state[chave_radio_p4]
                    pts = opcoes_p4.get(val, 0.0)
                    lnk = st.session_state.get(f"l_p4_txt_{ano_sel}", dP4.get("link", ""))
                    
                    save_resp("P4", val, pts, lnk)
                    res_data["P4"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_p4():
                    lnk = st.session_state[f"l_p4_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_p4, v_salvo_p4)
                    pts = opcoes_p4.get(val, 0.0)
                    
                    save_resp("P4", val, pts, lnk)
                    res_data["P4"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, dP4.get("link", "") or "")]
                    
                    if lnk != dP4.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_p4_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_p4_{ano_sel}"] = True

                c_p4_1, c_p4_2 = st.columns([1, 1])
                with c_p4_1:
                    lista_opcoes_p4 = list(opcoes_p4.keys())
                    idx_p4 = lista_opcoes_p4.index(v_salvo_p4) if v_salvo_p4 in lista_opcoes_p4 else 0
                    
                    st.radio(
                        "Status de entrega AUDESP (P4):",
                        options=lista_opcoes_p4,
                        index=idx_p4,
                        key=chave_radio_p4,
                        on_change=cb_radio_p4,
                        label_visibility="collapsed"
                    )
                    
                with c_p4_2:
                    link_p4 = st.text_area("Link de Evidência / Recibo AUDESP (P4):", value=dP4.get("link", ""), key=f"l_p4_txt_{ano_sel}", on_change=cb_text_p4, height=100)
                    placeholder_links_p4 = st.empty()
                    links_p4_visuais = [u[0] for u in re.findall(regex_pure_url, link_p4 or "")]
                    if links_p4_visuais:
                        placeholder_links_p4.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_p4_visuais]))

                pts_atuais_p4 = dP4.get("pontos", 0.0)
                cor_txt_p4 = "#28a745" if pts_atuais_p4 == 150.0 else ("#dc3545" if v_salvo_p4 != "Selecione..." else "#6c757d")
                st.markdown(f"<span style='color:{cor_txt_p4}; font-weight:bold;'>📊 Impacto de Pontuação no Indicador P4: {pts_atuais_p4:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("P4_exclusivo", res_data, ano_sel)

        # GATILHO DO MODAL P4
        if st.session_state.get(f"gatilho_modal_p4_{ano_sel}", False):
            modal_aviso_link("P4", st.session_state.get(f"links_pendentes_p4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_p4_{ano_sel}"] = False
