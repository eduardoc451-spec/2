import streamlit as st
import sqlite3
import re
import json
from io import BytesIO
from datetime import datetime, date

# Importações essenciais do ReportLab para a geração do PDF do i-Fiscal
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# =============================================================================
# CONSTANTES GLOBAIS - MATRIZ DE QUESITOS OFICIAL DO I-FISCAL
# =============================================================================

FAIXA_CORES = {
    "C": "#ef4444", 
    "C+": "#f97316", 
    "B": "#eab308", 
    "B+": "#22c55e", 
    "A": "#16a34a"
}

CATEGORIAS_MAP = {
    "infraestrutura": {
        "label": "Infraestrutura e Setor Fiscal", 
        "qids": ["1.1", "1.2", "1.3", "1.4", "1.5", "1.5.1"]
    },
    "planejamento": {
        "label": "Planejamento e Diretrizes Orçamentárias", 
        "qids": ["2.0", "3.0", "4.3"]
    },
    "transparencia_gov": {
        "label": "Transparência Fiscal e Governo Digital", 
        "qids": ["5.0", "5.3", "5.4", "6.0"]
    },
    "sistemas_gestao": {
        "label": "Sistemas de Gestão Financeira e Operações", 
        "qids": ["8.0", "8.1", "8.2", "9.4", "9.4.1", "11.0", "13.0", "13.3"]
    },
    "seguranca_processos": {
        "label": "Segurança da Informação e Processos Fiscais", 
        "qids": ["18.1", "19.0", "19.1", "20.0", "20.1", "21.0", "22.0"]
    },
    "auditoria_final": {
        "label": "Quesitos de Auditoria Final (Bloco F)", 
        "qids": [
            "F1", "F2", "F3", "F4", "F5", "F8", "F10", 
            "F12", "F13", "F14", "F15", "F16", "F17", "F18", "F20"
        ]
    },
}

PONTUACOES_MAX = {
    # Quesitos Numéricos
    "1.1": 0.5, "1.2": 1.5, "1.3": 10.0, "1.4": 3.0, "1.5": 5.0, "1.5.1": 5.0,
    "2.0": 4.0, "3.0": 30.0, "4.3": 5.0, 
    "5.0": 3.0, "5.3": 3.0, "5.4": 6.0, "6.0": 2.0, 
    "8.0": 1.0, "8.1": 2.0, "8.2": 15.0, "9.4": 2.0, "9.4.1": 3.0, "11.0": 3.0, "13.0": 1.0, "13.3": 9.0, 
    "18.1": 15.0, "19.0": 3.0, "19.1": 3.0, "20.0": 3.0, "20.1": 6.0, "21.0": 3.0, "22.0": 3.0,
    
    # Quesitos de Bloco F
    "F1": 75.0, "F2": 75.0, "F3": 100.0, "F4": 25.0, "F5": 25.0, 
    "F8": 75.0, "F10": 75.0, "F12": 50.0, "F13": 50.0, "F14": 50.0, 
    "F15": 25.0, "F16": 25.0, "F17": 75.0, "F18": 75.0, "F20": 50.0
}

# TEXTOS ENXUTOS PARA OS CARD DE PERGUNTAS DO FORMULÁRIO
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
    "F20": "Dívida Ativa Inerte: Ausência absoluta de cobrança judicial que resulte em prescrição de débitos?"
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
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}_fiscal"):
        st.rerun()

# =============================================================================
# 1. FUNÇÕES DE APOIO E BANCO DE DADOS (IEGM - I-FISCAL)
# =============================================================================

def get_connection():
    # Conecta no banco de dados isolado e específico do I-FISCAL
    return sqlite3.connect("dados_ifiscal.db", check_same_thread=False)

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
        
        # 2. PRAGMA para checar quais colunas realmente existem no arquivo físico do banco do I-FISCAL
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
            st.error(f"Erro operacional no banco do I-FISCAL: {e}")
    except Exception as e:
        st.error(f"Erro ao salvar {qid}: {e}")

def bloco_comentarios(questao_id, res_data, sufixo="fiscal"):
    """
    Gera o diálogo interno avançado com histórico retrátil, status em realtime
    e controle individual de remoção por lixeira para o módulo I-FISCAL.
    """
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
# 2. GERADOR DO RELATÓRIO PDF
# =============================================================================

def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=30, 
        leftMargin=30, 
        topMargin=30, 
        bottomMargin=50
    )
    elements = []
    styles = getSampleStyleSheet()

    style_titulo_capa = ParagraphStyle(
        'TituloCapa', 
        parent=styles['Normal'], 
        fontName='Helvetica-Bold', 
        fontSize=24, 
        leading=28, 
        textColor=colors.HexColor("#001A4D"), 
        alignment=1
    )

    # FOLHA 1: CAPA
    elements.append(Spacer(1, 100))
    try:
        logo = Image("iegm.png", width=380, height=180)
        logo.hAlign = 'CENTER'
        elements.append(logo)
    except Exception:
        elements.append(Paragraph("[Logo: i-Fiscal / IEGM]", styles["Title"]))
        
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("Relatório do i-fiscal", style_titulo_capa))
    elements.append(Spacer(1, 15))
    
    style_ano_capa = ParagraphStyle('AnoCapa', parent=styles['Normal'], fontName='Helvetica', fontSize=16, textColor=colors.HexColor("#7f8c8d"), alignment=1)
    elements.append(Paragraph(f"{ano}", style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO (Exatamente no seu padrão original de 6 itens)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor("#1b4f72"), alignment=2)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030 (ODS)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("6. Série Histórica do I-Fiscal", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
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

    # -------------------------------------------------------------------------
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS 
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS </b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    reincidencias_detectadas = []
    
    # IMPORTANTE: Use o dicionário PONTUACOES_MAX definido globalmente no seu sistema i-Fiscal
    # para validar os tetos oficiais de cada quesito de nota real.
    tetos_referencia = PONTUACOES_MAX if 'PONTUACOES_MAX' in globals() else {}
    
    for qid, info_atual in dados.items():
        # Ignora comentários e chaves que não sejam dicionários válidos
        if qid.startswith("COM_") or not isinstance(info_atual, dict): 
            continue
            
        # Só avalia se o quesito pertencer à lista de pontuações oficiais do i-Fiscal
        if qid not in tetos_referencia:
            continue
            
        pts_maximo = float(tetos_referencia[qid])
        pts_obtidos_atual = float(info_atual.get("pontos", 0.0))
        
        # Só analisa se o teto for válido e se houve falha real no ano atual (eficiência menor que 50%)
        if pts_maximo > 0 and (pts_obtidos_atual / pts_maximo) * 100 < 50.0:
            # Busca o mesmo quesito no ano anterior
            info_ant = dados_ano_anterior.get(qid, {}) if isinstance(dados_ano_anterior, dict) else {}
            pts_obtidos_ant = float(info_ant.get("pontos", 0.0)) if isinstance(info_ant, dict) else 0.0
            
            # Se também falhou no ano anterior (eficiência menor que 50%), temos uma Reincidência Crônica
            if (pts_obtidos_ant / pts_maximo) * 100 < 50.0:
                # Define a categoria dinamicamente com base no perfil do quesito no i-Fiscal
                qid_str = str(qid).strip().upper()
                if qid_str.startswith("7") or qid_str.startswith("8") or qid_str.startswith("9"):
                    origem = "Gestão Orçamentária"
                elif qid_str.startswith("10") or qid_str.startswith("12") or qid_str.startswith("16"):
                    origem = "Planejamento e Execução"
                elif qid_str.startswith("F"):
                    origem = "Controle Fiscal / Receita"
                else:
                    origem = "Administração Financeira"
                    
                reincidencias_detectadas.append({
                    "qid": qid,
                    "tipo": origem,
                    "detalhe": "Ineficiência Crônica de Desempenho (Abaixo de 50% por 2 anos)",
                    "ant": f"{pts_obtidos_ant:.1f} pts",
                    "atual": f"{pts_obtidos_atual:.1f} pts"
                })

    if reincidencias_detectadas:
        data_reinc = [["Quesito", "Origem da Falha", "Impacto Histórico", "Exercício Anterior", "Exercício Atual"]]
        
        # Ordenação segura para o i-Fiscal (suporta quesitos numéricos como '7.2' e alfanuméricos como 'F6')
        def extrair_chave_ordenacao(item):
            partes = []
            for p in item["qid"].split('.'):
                if p.isdigit():
                    partes.append(int(p))
                else:
                    # Se for letra (ex: 'F6'), converte para ordinais para ordenar corretamente
                    partes.append(sum(ord(char) for char in p))
            return partes

        for reinc in sorted(reincidencias_detectadas, key=extrair_chave_ordenacao): 
            data_reinc.append([
                reinc["qid"], 
                reinc["tipo"], 
                Paragraph(f"<b>{reinc['detalhe']}</b>", styles["Normal"]), 
                reinc["ant"], 
                reinc["atual"]
            ])
            
        tabela_reinc = Table(data_reinc, colWidths=[65, 125, 160, 75, 65])
        tabela_reinc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")), 
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), 
            ("ALIGN", (0, 0), (-1, 0), "CENTER"), 
            ("ALIGN", (0, 1), (1, -1), "CENTER"), 
            ("ALIGN", (3, 1), (-1, -1), "CENTER"), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c0392b")), 
            ("FONTSIZE", (0, 0), (-1, -1), 9), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_reinc)
    else: 
        elements.append(Paragraph("<font color='#28a745'><b>✅ Nenhuma reincidência ativa detectada. O município corrigiu ou mitigou os gargalos fiscais do ano anterior.</b></font>", styles["Normal"]))
        
    elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # --- TÓPICO 5: ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU) ---
    # -------------------------------------------------------------------------
    import reportlab.lib.colors as rl_colors

    elements.append(Paragraph("<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    # 🛠️ CORREÇÃO: Adicionado o parâmetro ignorar_filtros para aceitar qualquer resposta no 9.5
    def calcular_percentual_checklist(resposta_bruta, total_itens, ignorar_filtros=False):
        if not resposta_bruta: 
            return 0.0
        
        if str(resposta_bruta).startswith("["):
            try:
                import ast
                itens_lista = ast.literal_eval(str(resposta_bruta))
                if isinstance(itens_lista, list):
                    if ignorar_filtros:
                        itens_validos = [str(i).strip() for i in itens_lista if i]
                    else:
                        itens_validos = [str(i).strip().lower() for i in itens_lista if i and "outros" not in str(i).lower() and "não" not in str(i).lower()]
                    return min((len(itens_validos) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0
            except Exception:
                pass
                
        itens = [i.strip() for i in str(resposta_bruta).split(",") if i.strip()]
        if not ignorar_filtros:
            itens = [i for i in itens if "outros" not in i.lower() and "não" not in i.lower()]
        return min((len(itens) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0

    # Dicionário parametrizado atualizado com as metas ODS do i-Fiscal
    REGRAS_ODS = {
        "1.0": {"metas": "17.1", "total_chk": 0},
        "1.1": {"metas": "17.1", "total_chk": 0},
        "1.3": {"metas": "17.1", "total_chk": 0},
        "1.4": {"metas": "16.5, 17.1", "total_chk": 0},
        "1.5": {"metas": "16.5", "total_chk": 0},         
        "1.5.1": {"metas": "16.5", "total_chk": 0},       
        "2.0": {"metas": "16.5", "total_chk": 0},         
        "3.0": {"metas": "17.1", "total_chk": 0},
        "3.1": {"metas": "17.1", "total_chk": 8},   
        "4.0": {"metas": "17.1", "total_chk": 0},
        "5.0": {"metas": "17.1", "total_chk": 0},
        "7.0": {"metas": "17.1", "total_chk": 0},
        "7.3": {"metas": "10.4, 17.1", "total_chk": 5}, 
        "8.0": {"metas": "17.1", "total_chk": 0},
        "8.1": {"metas": "17.1", "total_chk": 0},
        "8.2": {"metas": "17.1", "total_chk": 0},
        "8.3": {"metas": "16.6, 16.10", "total_chk": 0},  
        "9.0": {"metas": "17.1", "total_chk": 0},
        "9.3": {"metas": "17.1", "total_chk": 0},         
        "9.4": {"metas": "17.1", "total_chk": 0},
        "9.5": {"metas": "17.1", "total_chk": 3},   # Múltipla escolha (3 opções)
        "9.6": {"metas": "10.4, 17.1", "total_chk": 0},
        "10.0": {"metas": "17.1", "total_chk": 0},
        "10.3": {"metas": "17.1", "total_chk": 0},
        "11.0": {"metas": "17.1", "total_chk": 0},
        "12.0": {"metas": "10.4, 16.6, 17.1", "total_chk": 0},
        "13.0": {"metas": "16.6, 16.7, 17.1", "total_chk": 0},
        "16": {"metas": "16.6, 17.1", "total_chk": 0},
        "17.0": {"metas": "17.1", "total_chk": 0},
        "18.0": {"metas": "16.6, 16.10", "total_chk": 0}, 
        "21.0": {"metas": "16.5, 16.6", "total_chk": 0},  
        "22.0": {"metas": "16.5, 16.6", "total_chk": 0},  
        "23.0": {"metas": "17.1", "total_chk": 0},
        "25.0": {"metas": "17.1", "total_chk": 0}
    }

    analise_ods = []
    
    dados_reference = None
    for nome_var in ['dados', 'res_data', 'respostas', 'dados_municipio']:
        if nome_var in locals():
            dados_reference = locals()[nome_var]
            break

    if dados_reference is None:
        try: dados_reference = dados
        except NameError:
            try: dados_reference = res_data
            except NameError: dados_reference = {}

    for qid, config in REGRAS_ODS.items():
        info = dados_reference.get(qid, {}) if isinstance(dados_reference, dict) else {"valor": "Não Respondido"}
        if not isinstance(info, dict):
            info = {"valor": str(info)}
            
        resp = str(info.get("valor", "")).strip()
        resp_l = resp.lower()
        
        if not resp or resp_l == "não respondido" or resp == "[]": 
            continue
            
        # Avaliação do status e cálculo de percentual
        if config["total_chk"] > 0 or qid == "9.5":
            total_opcoes = 3 if qid == "9.5" else config["total_chk"]
            # 🛠️ CORREÇÃO: Passa ignorar_filtros=True se for o quesito 9.5
            is_95 = (qid == "9.5")
            pct = calcular_percentual_checklist(resp, total_opcoes, ignorar_filtros=is_95)
            status = f"{pct:.1f}% Atendido"
        else:
            # Regras de avaliação lógica customizadas para cada cenário do i-Fiscal
            if qid in ["9.6", "12.0"]:
                if "não" in resp_l:
                    status = "Atendido"
                else:
                    status = "Não Atendido"
            elif qid == "8.2":
                if "sistema automatizado" in resp_l or "manualmente" in resp_l:
                    status = "Atendido"
                else:
                    status = "Não Atendido"
            elif qid == "8.3":
                if "sim, sem restrição" in resp_l or "sem restrição - 00" in resp_l:
                    status = "Atendido"
                else:
                    status = "Não Atendido"
            elif qid == "9.3":
                opcoes_validas = ["site da prefeitura", "órgão fazendário", "orgao fazendario", "cartório autorizado", "cartorio autorizado", "outros"]
                if any(opc in resp_l for opc in opcoes_validas):
                    status = "Atendido"
                else:
                    status = "Não Atendido"
            elif qid == "17.0":
                if "todas as ações" in resp_l:
                    status = "Atendido"
                else:
                    status = "Não Atendido"
            elif qid == "23.0":
                if "dentro do prazo" in resp_l:
                    status = "Atendido"
                else:
                    status = "Não Atendido"
            else:
                if "sim" in resp_l or "parcialmente" in resp_l or "integralmente" in resp_l:
                    status = "Atendido"
                else:
                    status = "Não Atendido"

        exibicao_resp = resp
        if exibicao_resp.startswith("["):
            exibicao_resp = exibicao_resp.replace("[", "").replace("]", "").replace("'", "").replace('"', '')

        analise_ods.append({
            "qid": qid,
            "status": status,
            "metas": config["metas"],
            "resp": exibicao_resp[:45] + "..." if len(exibicao_resp) > 45 else exibicao_resp
        })

    if analise_ods:
        data_ods = [["Quesito", "Resposta Informada", "Vínculo Metas ODS", "Status de Cumprimento"]]
        style_td_ods = ParagraphStyle('TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        
        def chave_ordenacao_ods(item):
            partes = []
            for p in item["qid"].split('.'):
                if p.isdigit():
                    partes.append(int(p))
                else:
                    partes.append(sum(ord(char) for char in p))
            return partes
        
        for item in sorted(analise_ods, key=chave_ordenacao_ods):
            st_txt = item["status"]
            
            if "Não Atendido" in st_txt:
                st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif "Atendido" in st_txt and "%" not in st_txt:
                st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else:
                st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)
                
            data_ods.append([
                item["qid"], 
                Paragraph(item["resp"], styles["Normal"]), 
                item["metas"], 
                st_p
            ])
            
        tabela_ods = Table(data_ods, colWidths=[60, 200, 115, 110])
        tabela_ods.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#0f9d58")), 
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.whitesmoke), 
            ("ALIGN", (0, 0), (0, -1), "CENTER"), 
            ("ALIGN", (2, 0), (3, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#0f9d58")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_ods)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 📊 6. SÉRIE HISTÓRICA DO I-FISCAL (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    # IMPORTS LOCAIS SEGUROS (Evita conflitos de escopo global no ReportLab)
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    import reportlab.lib.colors as rl_colors

    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>6. SÉRIE HISTÓRICA DO I-FISCAL (CONSOLIDADO FINAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []
    
    # 🕵️‍♂️ Captura dinâmica do ANO para evitar conflito de nomenclatura
    ano_reference = None
    for nome_var in ['ano_sel', 'ano_atual', 'ano', 'exercicio']:
        if nome_var in locals():
            ano_reference = locals()[nome_var]
            break
    if ano_reference is None:
        ano_reference = 2026

    # 🕵️‍♂️ Captura dinâmica da NOTA ATUAL DO COMPILADOR
    nota_reference = 0.0
    for nome_var in ['total_pts', 'nota_atual', 'pontuacao_final']:
        if nome_var in locals():
            try:
                nota_reference = float(locals()[nome_var])
                break
            except (ValueError, TypeError):
                continue

    import streamlit as st

    # Função auxiliar interna para calcular a nota líquida real (Pontos Positivos + Penalidades Negativas)
    def calcular_nota_liquida_fiscal(dicionario_dados):
        if not dicionario_dados or not isinstance(dicionario_dados, dict):
            return 0.0
        soma_positivos = 0.0
        soma_penalidades = 0.0
        for qid_h, info_h in dicionario_dados.items():
            if isinstance(info_h, dict) and not qid_h.startswith("COM_"):
                try:
                    val = float(info_h.get("pontos", 0.0))
                    if val > 0:
                        soma_positivos += val
                    else:
                        soma_penalidades += val  # Acumula as penalidades do Tópico 3
                except (ValueError, TypeError):
                    continue
        # A nota final do i-Fiscal é a composição de suas entregas mitigada pelo impacto do risco
        return max(0.0, min(soma_positivos + soma_penalidades, 1000.0))

    # Montagem dos dados do gráfico integrando as fontes do i-Fiscal
    for a in anos_serie:
        # 1. Se for o ano selecionado atualmente no formulário
        if a == ano_reference: 
            if nota_reference > 0.0:
                valores_serie.append(min(nota_reference, 1000.0))
            elif 'dados_reference' in locals() and dados_reference:
                valores_serie.append(calcular_nota_liquida_fiscal(dados_reference))
            else:
                valores_serie.append(0.0)
                
        # 2. Se o ano estiver salvo no dicionário "all_data" passado por parâmetro
        elif 'all_data' in locals() and all_data and a in all_data:
            dados_ano = all_data[a]
            if isinstance(dados_ano, dict):
                valores_serie.append(calcular_nota_liquida_fiscal(dados_ano))
            else:
                valores_serie.append(min(max(float(dados_ano), 0.0), 1000.0))

        # 3. Fallback: Se o ano estiver salvo no histórico do session_state do Streamlit
        elif hasattr(st, 'session_state') and 'all_data' in st.session_state and a in st.session_state.all_data:
            dados_ano = st.session_state.all_data[a]
            if isinstance(dados_ano, dict):
                valores_serie.append(calcular_nota_liquida_fiscal(dados_ano))
            else:
                valores_serie.append(min(max(float(dados_ano), 0.0), 1000.0))
                
        # 4. Se não encontrar o histórico do exercício, deixa zerado
        else: 
            valores_serie.append(0.0)

    # Configuração da Área de Desenho do Gráfico
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
    
    # Escala baseada nas regras de pontuação do i-Fiscal (0 a 1000 pontos)
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = 1000
    bc.valueAxis.valueStep = 200
    bc.valueAxis.labels.fontSize = 8
    
    # 🔥 ATIVAÇÃO DOS RÓTULOS (EXIBE A PONTUAÇÃO EXATA SOBRE CADA BARRA)
    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'
    
    # Customização visual alinhada à paleta corporativa de auditoria do i-Fiscal
    bc.bars[0].fillColor = rl_colors.HexColor("#1b4f72")
    bc.bars[0].strokeColor = rl_colors.HexColor("#2c3e50")
    bc.bars[0].strokeWidth = 0.5

    # Título do Gráfico
    desenho_grafico.add(String(240, 150, "Série Histórica do Desempenho i-Fiscal", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=rl_colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)
    elements.append(Spacer(1, 15))

    # =============================================================================
    # --- FECHAMENTO E RETORNO SEGURO DO RELATÓRIO (FIM DA FUNÇÃO) ---
    # =============================================================================
    doc.build(elements)
    buffer.seek(0)
    return buffer

# =============================================================================
# 3. INTERFACE E PAINEL LATERAL (STREAMLIT)
# =============================================================================

def render_sidebar():
    st.sidebar.title("🛠️ Painel i-Fiscal")
    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    
    if "reset_ctr" not in st.session_state:
        st.session_state["reset_ctr"] = 0
        
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos, key="ano_referencia_global")
    res_data = load_respostas(ano_sel)
    
    total_pts = sum(float(item.get("pontos", 0)) for k, item in res_data.items() if not k.startswith("COM_") and float(item.get("pontos", 0)) > -100)
    rebaixar = any(float(item.get("pontos", 0)) <= -100 for item in res_data.values())
    
    if total_pts <= 499:     faixa, cor = "C",  "#ef4444"
    elif total_pts <= 599:   faixa, cor = "C+", "#f97316"
    elif total_pts <= 749:   faixa, cor = "B",  "#eab308"
    elif total_pts <= 899:   faixa, cor = "B+", "#22c55e"
    else:                    faixa, cor = "A",  "#16a34a"

    if rebaixar:
        faixas_ordem = ["C", "C+", "B", "B+", "A"]
        idx_f = faixas_ordem.index(faixa)
        faixa = faixas_ordem[max(0, idx_f - 1)]
        cor = FAIXA_CORES[faixa]
        st.sidebar.warning("⚠️ Faixa rebaixada por critério eliminatório.")

    st.sidebar.metric("Pontuação Total", f"{total_pts:.1f} pts")
    st.sidebar.markdown(f"**Faixa:** <span style='color:{cor}; font-size:20px; font-weight:bold;'>{faixa}</span>", unsafe_allow_html=True)
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("📄 Relatórios")
    
    try:
        dados_historicos_brutos = get_all_years_data()
    except Exception:
        dados_historicos_brutos = {}
        
    historico_tratado = {}
    if isinstance(dados_historicos_brutos, dict):
        for ano_chave, valor_ano in dados_historicos_brutos.items():
            try:
                ano_int = int(str(ano_chave).strip()[:4])
                historico_tratado[ano_int] = valor_ano
            except (ValueError, TypeError):
                continue

    st.session_state.all_data = historico_tratado

    pdf_buffer = gerar_relatorio_pdf(res_data, ano_sel, total_pts, faixa, historico_tratado)
    
    st.sidebar.download_button(
        label="📥Relatório PDF i-Fiscal",
        data=pdf_buffer.getvalue(),
        file_name=f"Relatorio_i-Fiscal_{ano_sel}.pdf",
        mime="application/pdf"
    )
    
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Zerar Questionário"):
        with get_connection() as conn:
            conn.execute("DELETE FROM respostas WHERE ano = ?", (ano_sel,))
            conn.commit()
            
        chaves_para_preservar = ["ano_referencia_global", "reset_ctr", "current_page", "selected_dimension"]
        for k in list(st.session_state.keys()):
            if k in chaves_para_preservar or any(termo in k.lower() for termo in ["login", "auth", "user"]):
                continue
            del st.session_state[k]
            
        st.session_state["reset_ctr"] += 1
        st.sidebar.success("Dados zerados com sucesso!")
        st.rerun()
        
    return total_pts, res_data, ano_sel

# =============================================================================
# 4. INTERFACE PRINCIPAL E FORMULÁRIO DINÂMICO (STREAMLIT)
# =============================================================================
def mostrar_formulario_ifiscal():
    init_db()
    total_pts, res_data, ano_sel = render_sidebar()
    
    # 🔍 Definição do CTR estático para as chaves do formulário
    ctr = "fiscal"
    
    # Estilização CSS mantendo o padrão i-Fiscal
    st.markdown("""
        <style>
        .quesito-card { 
            background-color: #f8f9fa;
            padding: 18px;
            border-left: 6px solid #001A4D;
            border-radius: 6px;
            margin-bottom: 15px;
            border: 1px solid #e0e0e0;
        }
        .section-header h3 {
            color: #001A4D;
            margin-top: 10px;
            margin-bottom: 15px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title(f"📋 Painel de Auditoria i-Fiscal - {ano_sel}")
    
    # 📑 Criação das abas estruturadas (Questionário e Gráficos)
    aba_quest, aba_graf = st.tabs(["📋 Questionário", "📈 Gráficos"])
    
    # --- CONTEÚDO DA ABA QUESTIONÁRIO ---
    with aba_quest:
        # -------------------------------------------------------------------------
        # SEÇÃO 1: ADMINISTRAÇÃO TRIBUTÁRIA
        # -------------------------------------------------------------------------
        st.markdown('<div class="section-header"><h3>1. Administração Tributária</h3></div>', unsafe_allow_html=True)
        
        # Insira abaixo os seus quesitos da Seção 1 (ex: Quesito 1.0, 1.1, etc.)
        # with st.container(border=True):
        #     ...

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 1 (TODOS TOTALMENTE INDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
            modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_1_1_{ano_sel}", False):
            modal_aviso_link("1.1", st.session_state.get(f"links_pendentes_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
            modal_aviso_link("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_1_3_{ano_sel}", False):
            modal_aviso_link("1.3", st.session_state.get(f"links_pendentes_1_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = False

# =============================================================================
        # QUESITO 1.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 1.0 - Estrutura Administrativa", expanded=True):
                st.subheader("1.0 • Administração Tributária")
                st.write("**Há estrutura administrativa voltada para a administração tributária?**")
                
                d10 = res_data.get("1.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc10 = ["Selecione...", "Sim", "Não"]
                v_salvo_10 = d10.get("valor", "Selecione...")
                if v_salvo_10 not in opc10: v_salvo_10 = "Selecione..."
                evidencia_10_salva = d10.get("link", "")

                def cb_10():
                    lnk = st.session_state.get(f"l10_in_{ano_sel}_fiscal", evidencia_10_salva).strip()
                    val = st.session_state.get(f"r10_in_{ano_sel}_fiscal", v_salvo_10)
                    
                    save_resp("1.0", val, 0.0, lnk)
                    res_data["1.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_10_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_10_salva or ""):
                        st.session_state[f"links_pendentes_1_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (1.0):", options=opc10, index=opc10.index(v_salvo_10), key=f"r10_in_{ano_sel}_fiscal", on_change=cb_10)
                with col2:
                    lk10 = st.text_area("Link/Evidência (1.0):", value=evidencia_10_salva, key=f"l10_in_{ano_sel}_fiscal", on_change=cb_10, height=100)
                    if lk10: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk10 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.0", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 1.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 1.1 - Lei da Estrutura Organizacional", expanded=True):
                st.subheader("1.1 • Estrutura Organizacional por Lei")
                st.write("**O Município possui lei que defina a estrutura organizacional da Administração Tributária?**")
                
                d11 = res_data.get("1.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc11 = ["Selecione...", "Sim – 0,5", "Não – 00"]
                v_salvo_11 = d11.get("valor", "Selecione...")
                if v_salvo_11 not in opc11: v_salvo_11 = "Selecione..."
                evidencia_11_salva = d11.get("link", "")

                def cb_11():
                    lnk = st.session_state.get(f"l11_in_{ano_sel}_fiscal", evidencia_11_salva).strip()
                    val = st.session_state.get(f"r11_in_{ano_sel}_fiscal", v_salvo_11)
                    pts = 0.5 if "Sim" in val else 0.0
                    
                    save_resp("1.1", val, float(pts), lnk)
                    res_data["1.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_11_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_11_salva or ""):
                        st.session_state[f"links_pendentes_1_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (1.1):", options=opc11, index=opc11.index(v_salvo_11), key=f"r11_in_{ano_sel}_fiscal", on_change=cb_11)
                with col2:
                    lk11 = st.text_area("Link/Evidência (1.1):", value=evidencia_11_salva, key=f"l11_in_{ano_sel}_fiscal", on_change=cb_11, height=100)
                    if lk11: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk11 or "")]))

                v_f11 = st.session_state.get(f"r11_in_{ano_sel}", v_salvo_11)
                pts_exibido_11 = 0.5 if "Sim" in v_f11 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.1: {pts_exibido_11:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 1.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 1.2 - Quadro de Fiscais e Auditores", expanded=True):
                st.subheader("1.2 • Cargos Preenchidos")
                st.write("**Qual o número de cargos de fiscais/auditores tributários preenchidos?**")
                st.caption("Critério: Se efetivos > 0 E comissão = 0 E terceirizados = 0 ➔ 1,5 ponto. Caso contrário ➔ 0 ponto.")
                
                d12 = res_data.get("1.2", {"valor": "0/0/0", "pontos": 0.0, "link": ""}) or {"valor": "0/0/0", "pontos": 0.0, "link": ""}
                evidencia_12_salva = d12.get("link", "")
                
                try:
                    ef, com, terc = map(int, d12.get("valor", "0/0/0").split("/"))
                except Exception:
                    ef, com, terc = 0, 0, 0

                def cb_12():
                    v_ef = st.session_state.get(f"num_12_ef_{ano_sel}_fiscal", ef)
                    v_com = st.session_state.get(f"num_12_com_{ano_sel}_fiscal", com)
                    v_terc = st.session_state.get(f"num_12_terc_{ano_sel}_fiscal", terc)
                    lnk = st.session_state.get(f"l12_in_{ano_sel}_fiscal", evidencia_12_salva).strip()
                    
                    val = f"{v_ef}/{v_com}/{v_terc}"
                    pts = 1.5 if v_ef > 0 and v_com == 0 and v_terc == 0 else 0.0
                    
                    save_resp("1.2", val, float(pts), lnk)
                    res_data["1.2"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_12_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_12_salva or ""):
                        st.session_state[f"links_pendentes_1_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.number_input("Efetivos:", value=ef, min_value=0, key=f"num_12_ef_{ano_sel}_fiscal", on_change=cb_12)
                    st.number_input("Em comissão:", value=com, min_value=0, key=f"num_12_com_{ano_sel}_fiscal", on_change=cb_12)
                    st.number_input("Terceirizados:", value=terc, min_value=0, key=f"num_12_terc_{ano_sel}_fiscal", on_change=cb_12)
                with col2:
                    lk12 = st.text_area("Link/Evidência (1.2):", value=evidencia_12_salva, key=f"l12_in_{ano_sel}_fiscal", on_change=cb_12, height=150)
                    if lk12: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk12 or "")]))

                f_ef = st.session_state.get(f"num_12_ef_{ano_sel}_fiscal", ef)
                f_com = st.session_state.get(f"num_12_com_{ano_sel}_fiscal", com)
                f_terc = st.session_state.get(f"num_12_terc_{ano_sel}_fiscal", terc)
                pts_exibido_12 = 1.5 if f_ef > 0 and f_com == 0 and f_terc == 0 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.2: {pts_exibido_12:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.2", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 1.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 1.3 - Capacitação Periódica", expanded=True):
                st.subheader("1.3 • Treinamento de Fiscais")
                st.write("**Os fiscais tributários recebem treinamento específico para execução das atividades inerentes ao cargo?**")
                st.caption("Exigência: Treinamento periódico pelo menos 1 vez ao ano.")
                
                d13 = res_data.get("1.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc13 = ["Selecione...", "Sim – 10", "Não – 00"]
                v_salvo_13 = d13.get("valor", "Selecione...")
                if v_salvo_13 not in opc13: v_salvo_13 = "Selecione..."
                evidencia_13_salva = d13.get("link", "")

                def cb_13():
                    lnk = st.session_state.get(f"l13_in_{ano_sel}_fiscal", evidencia_13_salva).strip()
                    val = st.session_state.get(f"r13_in_{ano_sel}_fiscal", v_salvo_13)
                    pts = 10.0 if "Sim" in val else 0.0
                    
                    save_resp("1.3", val, float(pts), lnk)
                    res_data["1.3"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_13_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_13_salva or ""):
                        st.session_state[f"links_pendentes_1_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_1_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (1.3):", options=opc13, index=opc13.index(v_salvo_13), key=f"r13_in_{ano_sel}_fiscal", on_change=cb_13)
                with col2:
                    lk13 = st.text_area("Link/Evidência (1.3):", value=evidencia_13_salva, key=f"l13_in_{ano_sel}_fiscal", on_change=cb_13, height=100)
                    if lk13: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk13 or "")]))

                v_f13 = st.session_state.get(f"r13_in_{ano_sel}", v_salvo_13)
                pts_exibido_13 = 10.0 if "Sim" in v_f13 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.3: {pts_exibido_13:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.3", res_data, sufixo="fiscal")

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 1.4 A 1.5.1 (INDEDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_1_4_{ano_sel}", False):
            modal_aviso_link("1.4", st.session_state.get(f"links_pendentes_1_4_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_1_4_2_{ano_sel}", False):
            modal_aviso_link("1.4.2", st.session_state.get(f"links_pendentes_1_4_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_4_2_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_1_5_{ano_sel}", False):
            modal_aviso_link("1.5", st.session_state.get(f"links_pendentes_1_5_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_5_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_1_5_1_{ano_sel}", False):
            modal_aviso_link("1.5.1", st.session_state.get(f"links_pendentes_1_5_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_5_1_{ano_sel}"] = False

    # =============================================================================
        # QUESITO 1.4 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_4_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 1.4 - Plano de Cargos e Salários", expanded=True):
                st.subheader("1.4 • PCCS Específico")
                st.write("**O Município possui Plano de Cargos e Salários específico para seus fiscais tributários?**")
                st.caption("⚠️ *Atenção: PCCS geral dos servidores públicos não é considerado PCCS específico.*")
                
                d14 = res_data.get("1.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc14 = ["Selecione...", "Sim – 03", "Não – 00"]
                v_salvo_14 = d14.get("valor", "Selecione...")
                if v_salvo_14 not in opc14: v_salvo_14 = "Selecione..."
                evidencia_14_salva = d14.get("link", "")

                def cb_14():
                    lnk = st.session_state.get(f"l14_in_{ano_sel}_fiscal", evidencia_14_salva).strip()
                    val = st.session_state.get(f"r14_in_{ano_sel}_fiscal", v_salvo_14)
                    pts = 3.0 if "Sim" in val else 0.0
                    
                    save_resp("1.4", val, float(pts), lnk)
                    res_data["1.4"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_14_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_14_salva or ""):
                        st.session_state[f"links_pendentes_1_4_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_1_4_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (1.4):", options=opc14, index=opc14.index(v_salvo_14), key=f"r14_in_{ano_sel}_fiscal", on_change=cb_14)
                with col2:
                    lk14 = st.text_area("Link/Evidência Geral (1.4):", value=evidencia_14_salva, key=f"l14_in_{ano_sel}_fiscal", on_change=cb_14, height=100)
                    if lk14: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk14 or "")]))

                v_f14 = st.session_state.get(f"r14_in_{ano_sel}_fiscal", v_salvo_14)
                pts_exibido_14 = 3.0 if "Sim" in v_f14 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.4: {pts_exibido_14:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.4", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 1.4.1 • TOTALMENTE INDEPENDENTE (SEM CONDICIONAL)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_4_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 1.4.1 - Regulamentação do PCCS", expanded=True):
                st.subheader("1.4.1 • Instrumento Normativo")
                st.write("**Informe o instrumento normativo de regulamentação do Plano de Cargos e Salários específico para seus fiscais tributários, Número e Data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar conforme Instrução de Preenchimento (IP).*")
                
                d141 = res_data.get("1.4.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_141 = d141.get("valor", "")
                
                def cb_141():
                    val = st.session_state.get(f"t141_in_{ano_sel}_fiscal", v_salvo_141).strip()
                    save_resp("1.4.1", val, 0.0, "")
                    res_data["1.4.1"] = {"valor": val, "pontos": 0.0, "link": ""}

                st.text_input("Número e Data da publicação (Ex: Lei nº 1.234 de 10/05/2020):", value=v_salvo_141, key=f"t141_in_{ano_sel}_fiscal", on_change=cb_141)
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.4.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.4.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 1.4.2 • TOTALMENTE INDEPENDENTE (SEM CONDICIONAL)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_4_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 1.4.2 - Divulgação Eletrônica do PCCS", expanded=True):
                st.subheader("1.4.2 • Página Eletrônica do PCCS")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do Plano de Cargos e Salários específico para os fiscais tributários:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                d142 = res_data.get("1.4.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_142 = d142.get("valor", "")

                def cb_142():
                    val = st.session_state.get(f"t142_in_{ano_sel}_fiscal", v_salvo_142).strip()
                    save_resp("1.4.2", val, 0.0, "")
                    res_data["1.4.2"] = {"valor": val, "pontos": 0.0, "link": ""}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', val or "")
                    if val != v_salvo_142 and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', v_salvo_142 or ""):
                        st.session_state[f"links_pendentes_1_4_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_1_4_2_{ano_sel}"] = True

                v_txt_142 = st.text_input("Página eletrônica (ou XYZ):", value=v_salvo_142, key=f"t142_in_{ano_sel}_fiscal", on_change=cb_142)
                lk_detec_142 = re.findall(r'(https?://[^\s]+)', v_txt_142 or "")
                if lk_detec_142: 
                    st.markdown("**🔗 Links detectados no campo:** " + " | ".join([f"[{u}]({u})" for u in lk_detec_142]))
                
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.4.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.4.2", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 1.5 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_5_{ano_sel}_segregacao", border=True):
            with st.expander("📌 Quesito 1.5 - Segregação de Funções", expanded=True):
                st.subheader("1.5 • Segregação de Funções Administrativas")
                st.write("**Há segregação de funções entre os setores de lançadoria, arrecadação, fiscalização e contabilidade?**")
                
                d15 = res_data.get("1.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc15 = ["Selecione...", "Sim – 05", "Não – 00"]
                v_salvo_15 = d15.get("valor", "Selecione...")
                if v_salvo_15 not in opc15: v_salvo_15 = "Selecione..."
                evidencia_15_salva = d15.get("link", "")

                def cb_15():
                    lnk = st.session_state.get(f"l15_in_{ano_sel}_segregacao", evidencia_15_salva).strip()
                    val = st.session_state.get(f"r15_in_{ano_sel}_segregacao", v_salvo_15)
                    pts = 5.0 if "Sim" in val else 0.0
                    
                    save_resp("1.5", val, float(pts), lnk)
                    res_data["1.5"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_15_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_15_salva or ""):
                        st.session_state[f"links_pendentes_1_5_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_1_5_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (1.5):", options=opc15, index=opc15.index(v_salvo_15), key=f"r15_in_{ano_sel}_segregacao", on_change=cb_15)
                with col2:
                    lk15 = st.text_area("Link/Evidência (1.5):", value=evidencia_15_salva, key=f"l15_in_{ano_sel}_segregacao", on_change=cb_15, height=100)
                    if lk15: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk15 or "")]))

                v_f15 = st.session_state.get(f"r15_in_{ano_sel}_segregacao", v_salvo_15)
                pts_exibido_15 = 5.0 if "Sim" in v_f15 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.5: {pts_exibido_15:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.5", res_data, sufixo="segregacao")

        # =============================================================================
        # QUESITO 1.5.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q1_5_1_{ano_sel}_permissao", border=True):
            with st.expander("📌 Quesito 1.5.1 - Permissões do Sistema", expanded=True):
                st.subheader("1.5.1 • Permissões de Acesso e Auditoria")
                st.write("**Há segregação nas permissões de acesso do sistema, com identificação do usuário e registro das transações efetuadas?**")
                
                d151 = res_data.get("1.5.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc151 = [
                    "Selecione...",
                    "Sim – 05", 
                    "Não – 00", 
                    "para lançamento, arrecadação ou fiscalização dos tributos – -03(perde 03 pontos)"
                ]
                v_salvo_151 = d151.get("valor", "Selecione...")
                if v_salvo_151 not in opc151: v_salvo_151 = "Selecione..."
                evidencia_151_salva = d151.get("link", "")

                def cb_151():
                    lnk = st.session_state.get(f"l151_in_{ano_sel}_permissao", evidencia_151_salva).strip()
                    val = st.session_state.get(f"r151_in_{ano_sel}_permissao", v_salvo_151)
                    
                    if "Sim" in val:
                        pts = 5.0
                    elif "-03" in val:
                        pts = -3.0
                    else:
                        pts = 0.0
                    
                    save_resp("1.5.1", val, float(pts), lnk)
                    res_data["1.5.1"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_151_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_151_salva or ""):
                        st.session_state[f"links_pendentes_1_5_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_1_5_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (1.5.1):", options=opc151, index=opc151.index(v_salvo_151), key=f"r151_in_{ano_sel}_permissao", on_change=cb_151)
                with col2:
                    lk151 = st.text_area("Link/Evidência (1.5.1):", value=evidencia_151_salva, key=f"l151_in_{ano_sel}_permissao", on_change=cb_151, height=100)
                    if lk151: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk151 or "")]))

                v_f151 = st.session_state.get(f"r151_in_{ano_sel}_permissao", v_salvo_151)
                pts_exibido_151 = 5.0 if "Sim" in v_f151 else (-3.0 if "-03" in v_f151 else 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 1.5.1: {pts_exibido_151:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("1.5.1", res_data, sufixo="permissao")

        # =============================================================================
        # GATILHO DO MODAL AUTOMÁTICO • GRUPO 2.0 (TOTALMENTE INDEPENDENTE)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_2_0_{ano_sel}", False):
            modal_aviso_link("2.0", st.session_state.get(f"links_pendentes_2_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 2.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q2_0_{ano_sel}_contab", border=True):
            with st.expander("📌 Quesito 2.0 - Responsável pela Contabilidade", expanded=True):
                st.subheader("2.0 • Provimento do Cargo de Contabilidade")
                st.write("**O servidor responsável pela contabilidade do município é ocupante de cargo de provimento efetivo?**")
                
                d20 = res_data.get("2.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc20 = ["Selecione...", "Sim – 04", "Não – 00"]
                v_salvo_20 = d20.get("valor", "Selecione...")
                if v_salvo_20 not in opc20: v_salvo_20 = "Selecione..."
                evidencia_20_salva = d20.get("link", "")

                def cb_20():
                    lnk = st.session_state.get(f"l20_in_{ano_sel}_contab", evidencia_20_salva).strip()
                    val = st.session_state.get(f"r20_in_{ano_sel}_contab", v_salvo_20)
                    pts = 4.0 if "Sim" in val else 0.0
                    
                    save_resp("2.0", val, float(pts), lnk)
                    res_data["2.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_20_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_20_salva or ""):
                        st.session_state[f"links_pendentes_2_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_2_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (2.0):", options=opc20, index=opc20.index(v_salvo_20), key=f"r20_in_{ano_sel}_contab", on_change=cb_20)
                with col2:
                    lk20 = st.text_area("Link/Evidência (2.0):", value=evidencia_20_salva, key=f"l20_in_{ano_sel}_contab", on_change=cb_20, height=100)
                    if lk20: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk20 or "")]))

                v_f20 = st.session_state.get(f"r20_in_{ano_sel}_contab", v_salvo_20)
                pts_exibido_20 = 4.0 if "Sim" in v_f20 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 2.0: {pts_exibido_20:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("2.0", res_data, sufixo="contab")

        # -------------------------------------------------------------------------
        # SEÇÃO 2: MEDIDAS DE ARRECADAÇÃO
        # -------------------------------------------------------------------------
        st.markdown('<div class="section-header"><h3>2. Medidas de Arrecadação</h3></div>', unsafe_allow_html=True)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 3.0 e 3.1 (TOTALMENTE INDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_3_0_{ano_sel}", False):
            modal_aviso_link("3.0", st.session_state.get(f"links_pendentes_3_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_3_1_{ano_sel}", False):
            modal_aviso_link("3.1", st.session_state.get(f"links_pendentes_3_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = False
        # =============================================================================
        # QUESITO 3.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q3_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 3.0 - Medidas de Arrecadação", expanded=True):
                st.subheader("3.0 • Efetividade na Arrecadação")
                st.write("**O Município adotou medidas efetivas para aumento da arrecadação?**")
                
                d30 = res_data.get("3.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc30 = ["Selecione...", "Sim – 30", "Não – 00"]
                v_salvo_30 = d30.get("valor", "Selecione...")
                if v_salvo_30 not in opc30: v_salvo_30 = "Selecione..."
                evidencia_30_salva = d30.get("link", "")

                def cb_30():
                    lnk = st.session_state.get(f"l30_in_{ano_sel}_fiscal", evidencia_30_salva).strip()
                    val = st.session_state.get(f"r30_in_{ano_sel}_fiscal", v_salvo_30)
                    pts = 30.0 if "Sim" in val else 0.0
                    
                    save_resp("3.0", val, float(pts), lnk)
                    res_data["3.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_30_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_30_salva or ""):
                        st.session_state[f"links_pendentes_3_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_3_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (3.0):", options=opc30, index=opc30.index(v_salvo_30), key=f"r30_in_{ano_sel}_fiscal", on_change=cb_30)
                with col2:
                    lk30 = st.text_area("Link/Evidência Geral (3.0):", value=evidencia_30_salva, key=f"l30_in_{ano_sel}_fiscal", on_change=cb_30, height=100)
                    if lk30: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk30 or "")]))

                v_f30 = st.session_state.get(f"r30_in_{ano_sel}_fiscal", v_salvo_30)
                pts_exibido_30 = 30.0 if "Sim" in v_f30 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 3.0: {pts_exibido_30:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("3.0", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 3.1 • TOTALMENTE INDEPENDENTE (COM CAMPO DE EVIDÊNCIA PRÓPRIO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q3_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 3.1 - Detalhamento das Medidas (Checklist)", expanded=True):
                st.subheader("3.1 • Medidas Implementadas")
                st.write("**Assinale as medidas implementadas para o aumento da arrecadação:**")
                
                d31 = res_data.get("3.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_31_salva = d31.get("link", "")
                
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
                
                try:
                    sel31 = json.loads(d31["valor"].replace("'", '"'))
                    if not isinstance(sel31, list): sel31 = []
                except:
                    sel31 = []

                # Callback para quando qualquer checkbox for alterado
                def cb_checklist_31():
                    lista_atualizada = []
                    for idx_opcao, texto_opcao in enumerate(opc31):
                        if st.session_state.get(f"chk_31_{idx_opcao}_{ano_sel}_fiscal", False):
                            lista_atualizada.append(texto_opcao)
                    
                    json_str = json.dumps(lista_atualizada)
                    lnk_atual = st.session_state.get(f"l31_in_{ano_sel}_fiscal", evidencia_31_salva).strip()
                    
                    save_resp("3.1", json_str, 0.0, lnk_atual)
                    res_data["3.1"] = {"valor": json_str, "pontos": 0.0, "link": lnk_atual}

                # Callback específico para o campo de texto de Evidências/Links
                def cb_link_31():
                    lnk = st.session_state.get(f"l31_in_{ano_sel}_fiscal", evidencia_31_salva).strip()
                    val_atual = res_data.get("3.1", {}).get("valor", "[]")
                    
                    save_resp("3.1", val_atual, 0.0, lnk)
                    res_data["3.1"] = {"valor": val_atual, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_31_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_31_salva or ""):
                        st.session_state[f"links_pendentes_3_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_3_1_{ano_sel}"] = True

                # Renderização dos Checkboxes (Divididos em 2 colunas)
                col_chk1, col_chk2 = st.columns(2)
                for i, opcao in enumerate(opc31):
                    target_col = col_chk1 if i % 2 == 0 else col_chk2
                    with target_col:
                        ja_checado = opcao in sel31
                        st.checkbox(opcao, value=ja_checado, key=f"chk_31_{i}_{ano_sel}_fiscal", on_change=cb_checklist_31)
                
                st.markdown("---")
                
                # Renderização do Campo de Texto para Link/Evidência
                lk31 = st.text_area(
                    "Link/Evidência Específica (3.1):", 
                    value=evidencia_31_salva, 
                    key=f"l31_in_{ano_sel}_fiscal", 
                    on_change=cb_link_31, 
                    height=100
                )
                if lk31: 
                    st.markdown("**🔗 Ativos (3.1):** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk31 or "")]))
                
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 3.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("3.1", res_data, sufixo="fiscal")

        # -------------------------------------------------------------------------
        # SEÇÃO 3: CADASTRO E PGV
        # -------------------------------------------------------------------------
        st.markdown('<div class="section-header"><h3>3. Cadastro Imobiliário e PGV</h3></div>', unsafe_allow_html=True)

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 4.0 a 4.3 (TOTALMENTE INDEPENDENTES)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_4_0_{ano_sel}", False):
            modal_aviso_link("4.0", st.session_state.get(f"links_pendentes_4_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_4_1_{ano_sel}", False):
            modal_aviso_link("4.1", st.session_state.get(f"links_pendentes_4_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = False

        if st.session_state.get(f"gatilho_modal_4_3_{ano_sel}", False):
            modal_aviso_link("4.3", st.session_state.get(f"links_pendentes_4_3_{ano_sel}", []))
            st.session_state[f"gatilho_modal_4_3_{ano_sel}"] = False

# =============================================================================
        # QUESITO 4.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q4_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 4.0 - Procedimento de Revisão do Cadastro Imobiliário", expanded=True):
                st.subheader("4.0 • Instituição de Revisão Periódica")
                st.write("**Foi instituído procedimento de revisão do cadastro imobiliário estabelecendo a sua periodicidade?**")
                st.caption("⚠️ **Obs.:** *A mera atualização cadastral por solicitação do contribuinte realizada de forma pontual e esporádica, sem qualquer convocação ou iniciativa por parte da Prefeitura Municipal, não será considerada na questão como revisão periódica e geral do Cadastro imobiliário.*")
                
                d40 = res_data.get("4.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc40 = ["Selecione...", "Sim", "Não"]
                v_salvo_40 = d40.get("valor", "Selecione...")
                if v_salvo_40 not in opc40: v_salvo_40 = "Selecione..."
                evidencia_40_salva = d40.get("link", "")

                def cb_40():
                    lnk = st.session_state.get(f"l40_in_{ano_sel}_fiscal", evidencia_40_salva).strip()
                    val = st.session_state.get(f"r40_in_{ano_sel}_fiscal", v_salvo_40)
                    
                    save_resp("4.0", val, 0.0, lnk)
                    res_data["4.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_40_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_40_salva or ""):
                        st.session_state[f"links_pendentes_4_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_4_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (4.0):", options=opc40, index=opc40.index(v_salvo_40), key=f"r40_in_{ano_sel}_fiscal", on_change=cb_40)
                with col2:
                    lk40 = st.text_area("Link/Evidência Geral (4.0):", value=evidencia_40_salva, key=f"l40_in_{ano_sel}_fiscal", on_change=cb_40, height=100)
                    if lk40: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk40 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 4.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("4.0", res_data, sufixo="fiscal")

# =============================================================================
        # QUESITO 4.1 • TOTALMENTE INDEPENDENTE (COM CAMPO DE EVIDÊNCIA PRÓPRIO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q4_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 4.1 - Detalhamento Normativo e Divulgação", expanded=True):
                st.subheader("4.1 • Instrumento Normativo e Endereço Eletrônico")
                st.write("**Informe o instrumento normativo (número e data da aprovação) e endereço eletrônico de divulgação do procedimento de revisão do cadastro imobiliário:**")
                
                d41 = res_data.get("4.1", {"valor": " | ", "pontos": 0.0, "link": ""}) or {"valor": " | ", "pontos": 0.0, "link": ""}
                evidencia_41_salva = d41.get("link", "")
                
                try: 
                    normativo_salvo, link_salvo = d41["valor"].split(" | ", 1)
                except: 
                    normativo_salvo, link_salvo = "", ""
                
                # Callback para os campos de texto do valor normativo/link divulgação
                def cb_41():
                    norm = st.session_state.get(f"t41_norm_{ano_sel}_fiscal", normativo_salvo).strip()
                    lnk_fld = st.session_state.get(f"t41_link_{ano_sel}_fiscal", link_salvo).strip()
                    novo_val = f"{norm} | {lnk_fld}"
                    lnk_evid = st.session_state.get(f"l41_in_{ano_sel}_fiscal", evidencia_41_salva).strip()
                    
                    save_resp("4.1", novo_val, 0.0, lnk_evid)
                    res_data["4.1"] = {"valor": novo_val, "pontos": 0.0, "link": lnk_evid}

                # Callback exclusivo para o campo de Evidência Geral do 4.1
                def cb_evidencia_41():
                    norm = st.session_state.get(f"t41_norm_{ano_sel}_fiscal", normativo_salvo).strip()
                    lnk_fld = st.session_state.get(f"t41_link_{ano_sel}_fiscal", link_salvo).strip()
                    novo_val = f"{norm} | {lnk_fld}"
                    lnk = st.session_state.get(f"l41_in_{ano_sel}_fiscal", evidencia_41_salva).strip()
                    
                    save_resp("4.1", novo_val, 0.0, lnk)
                    res_data["4.1"] = {"valor": novo_val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_41_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_41_salva or ""):
                        st.session_state[f"links_pendentes_4_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_4_1_{ano_sel}"] = True

                st.text_input("Instrumento Normativo (Número e Data):", value=normativo_salvo, key=f"t41_norm_{ano_sel}_fiscal", on_change=cb_41)
                v_lk_41 = st.text_input("Endereço Eletrônico de Divulgação (Campo do Quesito):", value=link_salvo, key=f"t41_link_{ano_sel}_fiscal", on_change=cb_41)
                
                lk_detec_41 = re.findall(r'(https?://[^\s]+)', v_lk_41 or "")
                if lk_detec_41: 
                    st.markdown("**🔗 Links detectados no campo normativo:** " + " | ".join([f"[{u}]({u})" for u in lk_detec_41]))
                
                st.markdown("---")
                # Novo Campo de Evidência Geral para o 4.1
                lk41_evid = st.text_area("Link/Evidência Geral (4.1):", value=evidencia_41_salva, key=f"l41_in_{ano_sel}_fiscal", on_change=cb_evidencia_41, height=100)
                if lk41_evid: st.markdown("**🔗 Ativos (Evidência 4.1):** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk41_evid or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 4.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("4.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 4.2 • TOTALMENTE INDEPENDENTE (COM CAMPO DE EVIDÊNCIA PRÓPRIO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q4_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 4.2 - Periodicidade da Revisão", expanded=True):
                st.subheader("4.2 • Janela Temporal de Revisão")
                st.write("**Qual a periodicidade da revisão geral do Cadastro Imobiliário?**")
                
                d42 = res_data.get("4.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                evidencia_42_salva = d42.get("link", "")
                opc42 = [
                    "Selecione...",
                    "Menor ou igual a 1 ano", 
                    "Maior que 1 e menor ou igual a 4 anos", 
                    "Maior que 4 e menor ou igual a 8 anos", 
                    "Maior que 8 anos"
                ]
                v_salvo_42 = d42.get("valor", "Selecione...")
                if v_salvo_42 not in opc42: v_salvo_42 = "Selecione..."

                # Callback para o botão de rádio
                def cb_42():
                    val = st.session_state.get(f"r42_in_{ano_sel}_fiscal", v_salvo_42)
                    lnk_atual = st.session_state.get(f"l42_in_{ano_sel}_fiscal", evidencia_42_salva).strip()
                    save_resp("4.2", val, 0.0, lnk_atual)
                    res_data["4.2"] = {"valor": val, "pontos": 0.0, "link": lnk_atual}

                # Callback para o campo de Evidência Geral do 4.2
                def cb_evidencia_42():
                    val_atual = st.session_state.get(f"r42_in_{ano_sel}_fiscal", v_salvo_42)
                    lnk = st.session_state.get(f"l42_in_{ano_sel}_fiscal", evidencia_42_salva).strip()
                    
                    save_resp("4.2", val_atual, 0.0, lnk)
                    res_data["4.2"] = {"valor": val_atual, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_42_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_42_salva or ""):
                        st.session_state[f"links_pendentes_4_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_4_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione a periodicidade (4.2):", options=opc42, index=opc42.index(v_salvo_42), key=f"r42_in_{ano_sel}_fiscal", on_change=cb_42)
                with col2:
                    lk42 = st.text_area("Link/Evidência Geral (4.2):", value=evidencia_42_salva, key=f"l42_in_{ano_sel}_fiscal", on_change=cb_evidencia_42, height=100)
                    if lk42: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk42 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 4.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("4.2", res_data, sufixo="fiscal")


        # =============================================================================
        # QUESITO 4.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q4_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 4.3 - Status de Atualização do Cadastro", expanded=True):
                st.subheader("4.3 • Revisão Atualizada")
                st.write("**O cadastro imobiliário está com a revisão periódica ou geral atualizada?**")
                st.caption("⚠️ **Obs.:** *A mera atualização cadastral por solicitação do contribuinte realizada de forma pontual e esporádica, sem qualquer convocação ou iniciativa por parte da Prefeitura Municipal, não será considerada na questão como revisão periódica e geral do Cadastro imobiliário.*")
                
                d43 = res_data.get("4.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc43 = ["Selecione...", "Sim – 05", "Não – 00"]
                v_salvo_43 = d43.get("valor", "Selecione...")
                if v_salvo_43 not in opc43: v_salvo_43 = "Selecione..."
                evidencia_43_salva = d43.get("link", "")

                def cb_43():
                    lnk = st.session_state.get(f"l43_in_{ano_sel}_fiscal", evidencia_43_salva).strip()
                    val = st.session_state.get(f"r43_in_{ano_sel}_fiscal", v_salvo_43)
                    pts = 5.0 if "Sim" in val else 0.0
                    
                    save_resp("4.3", val, float(pts), lnk)
                    res_data["4.3"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_43_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_43_salva or ""):
                        st.session_state[f"links_pendentes_4_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_4_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (4.3):", options=opc43, index=opc43.index(v_salvo_43), key=f"r43_in_{ano_sel}_fiscal", on_change=cb_43)
                with col2:
                    lk43 = st.text_area("Link/Evidência (4.3):", value=evidencia_43_salva, key=f"l43_in_{ano_sel}_fiscal", on_change=cb_43, height=100)
                    if lk43: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk43 or "")]))

                v_f43 = st.session_state.get(f"r43_in_{ano_sel}_fiscal", v_salvo_43)
                pts_exibido_43 = 5.0 if "Sim" in v_f43 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 4.3: {pts_exibido_43:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("4.3", res_data, sufixo="fiscal")

        # =============================================================================
        # GATILHOS DOS MODAIS AUTOMÁTICOS • GRUPO 5.0 a 5.4 (TOTALMENTE INDEPENDENTES)
        # =============================================================================
        for q_id in ["5.0", "5.1", "5.2", "5.3", "5.3.1", "5.3.2", "5.3.3", "5.3.4", "5.4"]:
            if st.session_state.get(f"gatilho_modal_{q_id.replace('.', '_')}_{ano_sel}", False):
                modal_aviso_link(q_id, st.session_state.get(f"links_pendentes_{q_id.replace('.', '_')}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{q_id.replace('.', '_')}_{ano_sel}"] = False

# =============================================================================
        # QUESITO 5.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.0 - Aprovação da PGV por Lei", expanded=True):
                st.subheader("5.0 • Aprovação Legal da PGV")
                st.write("**O instrumento da Planta Genérica de Valores (PGV) foi aprovado por lei, conforme previsto no Código Tributário Nacional (CTN)?**")
                
                d50 = res_data.get("5.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc50 = ["Selecione...", "Sim – 03", "Não – 00"]
                v_salvo_50 = d50.get("valor", "Selecione...")
                if v_salvo_50 not in opc50: v_salvo_50 = "Selecione..."
                evidencia_50_salva = d50.get("link", "")

                def cb_50():
                    lnk = st.session_state.get(f"l50_in_{ano_sel}_fiscal", evidencia_50_salva).strip()
                    val = st.session_state.get(f"r50_in_{ano_sel}_fiscal", v_salvo_50)
                    pts = 3.0 if "Sim" in val else 0.0
                    
                    save_resp("5.0", val, float(pts), lnk)
                    res_data["5.0"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_50_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_50_salva or ""):
                        st.session_state[f"links_pendentes_5_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (5.0):", options=opc50, index=opc50.index(v_salvo_50), key=f"r50_in_{ano_sel}_fiscal", on_change=cb_50)
                with col2:
                    lk50 = st.text_area("Link/Evidência Geral (5.0):", value=evidencia_50_salva, key=f"l50_in_{ano_sel}_fiscal", on_change=cb_50, height=100)
                    if lk50: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk50 or "")]))

                v_f50 = st.session_state.get(f"r50_in_{ano_sel}_fiscal", v_salvo_50)
                pts_exibido_50 = 3.0 if "Sim" in v_f50 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.0: {pts_exibido_50:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.0", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 5.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.1 - Instrumento Normativo da PGV", expanded=True):
                st.subheader("5.1 • Detalhamento Normativo")
                st.write("**Informe o Instrumento normativo de aprovação da Planta Genérica de Valores (PGV), Número e Data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")
                
                d51 = res_data.get("5.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_51 = d51.get("valor", "")
                evidencia_51_salva = d51.get("link", "")

                def cb_51():
                    val = st.session_state.get(f"t51_val_{ano_sel}_fiscal", v_salvo_51).strip()
                    lnk = st.session_state.get(f"l51_in_{ano_sel}_fiscal", evidencia_51_salva).strip()
                    
                    save_resp("5.1", val, 0.0, lnk)
                    res_data["5.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_51_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_51_salva or ""):
                        st.session_state[f"links_pendentes_5_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_input("Instrumento normativo de aprovação (Nº e Data):", value=v_salvo_51, key=f"t51_val_{ano_sel}_fiscal", on_change=cb_51)
                with col2:
                    lk51 = st.text_area("Link/Evidência (5.1):", value=evidencia_51_salva, key=f"l51_in_{ano_sel}_fiscal", on_change=cb_51, height=100)
                    if lk51: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk51 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 5.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.2 - Página de Divulgação da PGV", expanded=True):
                st.subheader("5.2 • Divulgação Eletrônica")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do Instrumento Normativo de aprovação da Planta Genérica de Valores (PGV):**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                d52 = res_data.get("5.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_52 = d52.get("valor", "")
                evidencia_52_salva = d52.get("link", "")

                def cb_52():
                    val = st.session_state.get(f"t52_val_{ano_sel}_fiscal", v_salvo_52).strip()
                    lnk = st.session_state.get(f"l52_in_{ano_sel}_fiscal", evidencia_52_salva).strip()
                    
                    save_resp("5.2", val, 0.0, lnk)
                    res_data["5.2"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_52_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_52_salva or ""):
                        st.session_state[f"links_pendentes_5_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    v_input_52 = st.text_input("Link de divulgação do instrumento (ou XYZ):", value=v_salvo_52, key=f"t52_val_{ano_sel}_fiscal", on_change=cb_52)
                    lk_detec_52 = re.findall(r'(https?://[^\s]+)', v_input_52 or "")
                    if lk_detec_52: st.markdown("**🔗 Detectado no campo:** " + " | ".join([f"[{u}]({u})" for u in lk_detec_52]))
                with col2:
                    lk52 = st.text_area("Link/Evidência Geral (5.2):", value=evidencia_52_salva, key=f"l52_in_{ano_sel}_fiscal", on_change=cb_52, height=100)
                    if lk52: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk52 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.2", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 5.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.3 - Previsão de Revisão Obrigatória da PGV", expanded=True):
                st.subheader("5.3 • Previsão de Revisão Periódica")
                st.write("**O Código Tributário Municipal ou Lei específica que tenha instituído o IPTU prevê a revisão periódica obrigatória da Planta Genérica de Valores (PGV)?**")
                
                d53 = res_data.get("5.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc53 = ["Selecione...", "Sim – 03", "Não – 00"]
                v_salvo_53 = d53.get("valor", "Selecione...")
                if v_salvo_53 not in opc53: v_salvo_53 = "Selecione..."
                evidencia_53_salva = d53.get("link", "")

                def cb_53():
                    lnk = st.session_state.get(f"l53_in_{ano_sel}_fiscal", evidencia_53_salva).strip()
                    val = st.session_state.get(f"r53_in_{ano_sel}_fiscal", v_salvo_53)
                    pts = 3.0 if "Sim" in val else 0.0
                    
                    save_resp("5.3", val, float(pts), lnk)
                    res_data["5.3"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_53_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_53_salva or ""):
                        st.session_state[f"links_pendentes_5_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (5.3):", options=opc53, index=opc53.index(v_salvo_53), key=f"r53_in_{ano_sel}_fiscal", on_change=cb_53)
                with col2:
                    lk53 = st.text_area("Link/Evidência (5.3):", value=evidencia_53_salva, key=f"l53_in_{ano_sel}_fiscal", on_change=cb_53, height=100)
                    if lk53: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk53 or "")]))

                v_f53 = st.session_state.get(f"r53_in_{ano_sel}_fiscal", v_salvo_53)
                pts_exibido_53 = 3.0 if "Sim" in v_f53 else 0.0
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.3: {pts_exibido_53:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.3", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 5.3.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_3_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.3.1 - Instrumento Normativo de Revisão da PGV", expanded=True):
                st.subheader("5.3.1 • Instrumento de Revisão")
                st.write("**Informe o instrumento normativo de revisão da Planta Genérica de Valores (PGV), Número e Data da publicação:**")
                
                d531 = res_data.get("5.3.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_531 = d531.get("valor", "")
                evidencia_531_salva = d531.get("link", "")

                def cb_531():
                    val = st.session_state.get(f"t531_{ano_sel}_fiscal", v_salvo_531).strip()
                    lnk = st.session_state.get(f"l531_in_{ano_sel}_fiscal", evidencia_531_salva).strip()
                    
                    save_resp("5.3.1", val, 0.0, lnk)
                    res_data["5.3.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_531_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_531_salva or ""):
                        st.session_state[f"links_pendentes_5_3_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_3_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_input("Instrumento normativo de revisão (Nº e Data):", value=v_salvo_531, key=f"t531_{ano_sel}_fiscal", on_change=cb_531)
                with col2:
                    lk531 = st.text_area("Link/Evidência (5.3.1):", value=evidencia_531_salva, key=f"l531_in_{ano_sel}_fiscal", on_change=cb_531, height=100)
                    if lk531: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk531 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.3.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.3.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 5.3.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_3_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.3.2 - Página de Divulgação da Revisão", expanded=True):
                st.subheader("5.3.2 • Divulgação Eletrônica da Revisão")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do Instrumento normativo de revisão da Planta Genérica de Valores (PGV):**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                d532 = res_data.get("5.3.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_532 = d532.get("valor", "")
                evidencia_532_salva = d532.get("link", "")

                def cb_532():
                    val = st.session_state.get(f"t532_{ano_sel}_fiscal", v_salvo_532).strip()
                    lnk = st.session_state.get(f"l532_in_{ano_sel}_fiscal", evidencia_532_salva).strip()
                    
                    save_resp("5.3.2", val, 0.0, lnk)
                    res_data["5.3.2"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_532_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_532_salva or ""):
                        st.session_state[f"links_pendentes_5_3_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_3_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    v_input_532 = st.text_input("Link de divulgação da revisão (ou XYZ):", value=v_salvo_532, key=f"t532_{ano_sel}_fiscal", on_change=cb_532)
                    lk_detec_532 = re.findall(r'(https?://[^\s]+)', v_input_532 or "")
                    if lk_detec_532: st.markdown("**🔗 Detectado no campo:** " + " | ".join([f"[{u}]({u})" for u in lk_detec_532]))
                with col2:
                    lk532 = st.text_area("Link/Evidência Geral (5.3.2):", value=evidencia_532_salva, key=f"l532_in_{ano_sel}_fiscal", on_change=cb_532, height=100)
                    if lk532: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk532 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.3.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.3.2", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 5.3.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_3_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.3.3 - Data da Última Revisão", expanded=True):
                st.subheader("5.3.3 • Cronologia da Última Revisão")
                st.write("**Informe a data da última revisão da PGV:**")
                
                d533 = res_data.get("5.3.3", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_533 = d533.get("valor", "")
                evidencia_533_salva = d533.get("link", "")

                def cb_533():
                    val = st.session_state.get(f"t533_{ano_sel}_fiscal", v_salvo_533).strip()
                    lnk = st.session_state.get(f"l533_in_{ano_sel}_fiscal", evidencia_533_salva).strip()
                    
                    save_resp("5.3.3", val, 0.0, lnk)
                    res_data["5.3.3"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_533_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_533_salva or ""):
                        st.session_state[f"links_pendentes_5_3_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_3_3_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_input("Data da última revisão (Ex: DD/MM/AAAA):", value=v_salvo_533, key=f"t533_{ano_sel}_fiscal", on_change=cb_533)
                with col2:
                    lk533 = st.text_area("Link/Evidência (5.3.3):", value=evidencia_533_salva, key=f"l533_in_{ano_sel}_fiscal", on_change=cb_533, height=100)
                    if lk533: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk533 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.3.3: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.3.3", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 5.3.4 • TOTALMENTE INDEPENDENTE (CORRIGIDO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_3_4_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.3.4 - Periodicidade em Anos", expanded=True):
                st.subheader("5.3.4 • Periodicidade Estabelecida")
                st.write("**Informe a periodicidade de revisão da PGV:**")
                
                d534 = res_data.get("5.3.4", {"valor": "0", "pontos": 0.0, "link": ""}) or {"valor": "0", "pontos": 0.0, "link": ""}
                evidencia_534_salva = d534.get("link", "")  # <-- Declaração correta aqui
                try: periodicidade_inicial = int(d534["valor"])
                except: periodicidade_inicial = 0

                def cb_534():
                    val_num = st.session_state.get(f"num_534_{ano_sel}_fiscal", periodicidade_inicial)
                    lnk = st.session_state.get(f"l534_in_{ano_sel}_fiscal", evidencia_534_salva).strip() # <-- Corrigido aqui dentro também
                    
                    save_resp("5.3.4", str(val_num), 0.0, lnk)
                    res_data["5.3.4"] = {"valor": str(val_num), "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_534_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_534_salva or ""):
                        st.session_state[f"links_pendentes_5_3_4_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_3_4_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.number_input("Periodicidade em anos:", value=periodicidade_inicial, min_value=0, key=f"num_534_{ano_sel}_fiscal", on_change=cb_534)
                with col2:
                    # Linha que gerou o erro corrigida usando a variável certa do 534:
                    lk534 = st.text_area("Link/Evidência (5.3.4):", value=evidencia_534_salva, key=f"l534_in_{ano_sel}_fiscal", on_change=cb_534, height=100)
                    if lk534: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk534 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.3.4: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.3.4", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 5.4 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q5_4_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 5.4 - Integração com Base do IPTU", expanded=True):
                st.subheader("5.4 • Atualização da Base de Cálculo")
                st.write("**Os dados da Planta Genérica de Valores (PGV) e do Cadastro Imobiliário atualizam a base de cálculo do IPTU?**")
                
                d54 = res_data.get("5.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc54 = [
                    "Selecione...",
                    "Sim, de forma automática no sistema – 06",
                    "Sim, de forma manual – 02",
                    "Não – 00"
                ]
                v_salvo_54 = d54.get("valor", "Selecione...")
                if v_salvo_54 not in opc54: v_salvo_54 = "Selecione..."
                evidencia_54_salva = d54.get("link", "")

                def cb_54():
                    lnk = st.session_state.get(f"l54_in_{ano_sel}_fiscal", evidencia_54_salva).strip()
                    val = st.session_state.get(f"r54_in_{ano_sel}_fiscal", v_salvo_54)
                    
                    if "automática" in val: pts = 6.0
                    elif "manual" in val: pts = 2.0
                    else: pts = 0.0
                    
                    save_resp("5.4", val, float(pts), lnk)
                    res_data["5.4"] = {"valor": val, "pontos": float(pts), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_54_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_54_salva or ""):
                        st.session_state[f"links_pendentes_5_4_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_5_4_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (5.4):", options=opc54, index=opc54.index(v_salvo_54), key=f"r54_in_{ano_sel}_fiscal", on_change=cb_54)
                with col2:
                    lk54 = st.text_area("Link/Evidência (5.4):", value=evidencia_54_salva, key=f"l54_in_{ano_sel}_fiscal", on_change=cb_54, height=100)
                    if lk54: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk54 or "")]))

                v_f54 = st.session_state.get(f"r54_in_{ano_sel}_fiscal", v_salvo_54)
                pts_exibido_54 = 6.0 if "automática" in v_f54 else (2.0 if "manual" in v_f54 else 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 5.4: {pts_exibido_54:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("5.4", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 6.0 • FORMATO CHECKLIST OTIMIZADO COM LÓGICA ASYNC POR CALLBACKS
        # =============================================================================
        with st.container(key=f"bloco_isolado_q6_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 6.0 - Critérios de Alíquota do IPTU", expanded=True):
                st.subheader("6.0 • Critérios de Cobrança do IPTU")
                st.write("**Sobre a alíquota do IPTU, quais critérios o município instituiu para a cobrança do imposto? (Checklist)**")
                
                # Busca e sanitiza dados anteriores do banco
                d60 = res_data.get("6.0", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_60_salva = d60.get("link", "")
                
                try:
                    val_banco = d60["valor"].replace("'", '"')
                    sel60 = json.loads(val_banco)
                    if not isinstance(sel60, list): sel60 = []
                except:
                    sel60 = []

                opcoes_tela = [
                    "Alíquotas progressivas em razão do valor do imóvel – 01",
                    "Alíquotas diferenciadas em razão da localização do imóvel – 0,5",
                    "Alíquotas diferenciadas em razão do uso do imóvel – 0,5",
                    "Outros – 00",
                    "Não há diferenciação nas alíquotas dos imóveis – -01 (perde 01 ponto)"
                ]

                # Callback Centralizado para os Checkboxes e Campo de Evidência
                def cb_60():
                    # Coleta dinamicamente os valores atuais de todos os checkboxes baseados nos seus estados em session_state
                    res60_atual = []
                    for idx_c, opc_c in enumerate(opcoes_tela):
                        if st.session_state.get(f"chk_60_{idx_c}_{ano_sel}_fiscal", opc_c in sel60):
                            res60_atual.append(opc_c)
                    
                    # Aplicação rigorosa da lógica excludente (se a opção de penalidade for marcada)
                    if any("Não há diferenciação" in item for item in res60_atual):
                        res60_atual = ["Não há diferenciação nas alíquotas dos imóveis – -01 (perde 01 ponto)"]
                    
                    # Cálculo de Pontuação
                    pts60_nova = 0.0
                    if "Não há diferenciação nas alíquotas dos imóveis – -01 (perde 01 ponto)" in res60_atual:
                        pts60_nova = -1.0
                    else:
                        for item in res60_atual:
                            if "progressivas" in item: pts60_nova += 1.0
                            elif "localização" in item: pts60_nova += 0.5
                            elif "uso" in item: pts60_nova += 0.5

                    lnk = st.session_state.get(f"txt_60_{ano_sel}_fiscal", evidencia_60_salva).strip()
                    
                    # Persistência atômica nos estados locais e banco
                    save_resp("6.0", json.dumps(res60_atual), float(pts60_nova), lnk)
                    res_data["6.0"] = {"valor": json.dumps(res60_atual), "pontos": float(pts60_nova), "link": lnk}
                    
                    # Validação reativa e isolada de novos links de evidência externa
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_60_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_60_salva or ""):
                        st.session_state[f"links_pendentes_6_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = True

                # Layout de exibição dos Checkboxes (Duas colunas)
                c1, c2 = st.columns([1, 1])
                for idx, opcao in enumerate(opcoes_tela):
                    target_col = c1 if idx % 2 == 0 else c2
                    with target_col:
                        pode_marcar = opcao in sel60
                        st.checkbox(opcao, value=pode_marcar, key=f"chk_60_{idx}_{ano_sel}_fiscal", on_change=cb_60)

                st.markdown("---")
                
                # Campo de entrada de Texto/Evidência integrado ao callback centralizado
                l60 = st.text_area("Link/Evidência (Legislação das Alíquotas do IPTU - 6.0):", value=evidencia_60_salva, key=f"txt_60_{ano_sel}_fiscal", on_change=cb_60, height=100)
                
                # Renderizador de Links ativos detectados em tempo de execução
                links_60_atuais = re.findall(r'(https?://[^\s]+)', l60) if l60 else []
                if links_60_atuais:
                    st.markdown("**🔗 Ativos (Evidência 6.0):** " + " | ".join([f"[{u}]({u})" for u in links_60_atuais]))

                # Exibição reativa e segura do balanço atual de pontos
                pts_exibido_60 = d60.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 6.0: {pts_exibido_60:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("6.0", res_data, sufixo="fiscal")

        # =============================================================================
        # ESCUTA DO GATILHO DO MODAL (INLINE)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_6_0_{ano_sel}", False):
            modal_aviso_link("6.0", st.session_state.get(f"links_pendentes_6_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_6_0_{ano_sel}"] = False

# =============================================================================
        # QUESITO 7.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q7_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 7.0 - Programa de Isenção do IPTU", expanded=True):
                st.subheader("7.0 • Programa de Isenção")
                st.write("**O município adotou programa de isenção do IPTU?**")
                
                d70 = res_data.get("7.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc70 = ["Selecione...", "Sim", "Não"]
                v_salvo_70 = d70.get("valor", "Selecione...")
                if v_salvo_70 not in opc70: v_salvo_70 = "Selecione..."
                evidencia_70_salva = d70.get("link", "")

                def cb_70():
                    lnk = st.session_state.get(f"l70_in_{ano_sel}_fiscal", evidencia_70_salva).strip()
                    val = st.session_state.get(f"r70_in_{ano_sel}_fiscal", v_salvo_70)
                    
                    save_resp("7.0", val, 0.0, lnk)
                    res_data["7.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_70_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_70_salva or ""):
                        st.session_state[f"links_pendentes_7_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_7_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.radio("Selecione uma opção (7.0):", options=opc70, index=opc70.index(v_salvo_70), key=f"r70_in_{ano_sel}_fiscal", on_change=cb_70)
                with col2:
                    lk70 = st.text_area("Link/Evidência Geral (7.0):", value=evidencia_70_salva, key=f"l70_in_{ano_sel}_fiscal", on_change=cb_70, height=100)
                    if lk70: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk70 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 7.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("7.0", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 7.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q7_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 7.1 - Regulamentação do Programa de Isenção", expanded=True):
                st.subheader("7.1 • Instrumento de Regulamentação")
                st.write("**Informe o instrumento normativo de regulamentação do programa de isenção do IPTU, Número e Data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")
                
                d71 = res_data.get("7.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_71 = d71.get("valor", "")
                evidencia_71_salva = d71.get("link", "")

                def cb_71():
                    val = st.session_state.get(f"txt_71_val_{ano_sel}_fiscal", v_salvo_71).strip()
                    lnk = st.session_state.get(f"l71_in_{ano_sel}_fiscal", evidencia_71_salva).strip()
                    
                    save_resp("7.1", val, 0.0, lnk)
                    res_data["7.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_71_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_71_salva or ""):
                        st.session_state[f"links_pendentes_7_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_7_1_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.text_input("Instrumento normativo (Nº e Data):", value=v_salvo_71, key=f"txt_71_val_{ano_sel}_fiscal", on_change=cb_71)
                with col2:
                    lk71 = st.text_area("Link/Evidência (7.1):", value=evidencia_71_salva, key=f"l71_in_{ano_sel}_fiscal", on_change=cb_71, height=100)
                    if lk71: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk71 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 7.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("7.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 7.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q7_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 7.2 - Página de Divulgação da Isenção", expanded=True):
                st.subheader("7.2 • Divulgação Eletrônica da Regulamentação")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do Instrumento normativo de regulamentação do programa de isenção do IPTU:**")
                st.caption("⚠️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                d72 = res_data.get("7.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_72 = d72.get("valor", "")
                evidencia_72_salva = d72.get("link", "")

                def cb_72():
                    val = st.session_state.get(f"txt_72_val_{ano_sel}_fiscal", v_salvo_72).strip()
                    lnk = st.session_state.get(f"l72_in_{ano_sel}_fiscal", evidencia_72_salva).strip()
                    pts72_nova = -3.0 if val.upper() == "XYZ" else 0.0
                    
                    save_resp("7.2", val, float(pts72_nova), lnk)
                    res_data["7.2"] = {"valor": val, "pontos": float(pts72_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_72_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_72_salva or ""):
                        st.session_state[f"links_pendentes_7_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_7_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    v_input_72 = st.text_input("Link de divulgação da isenção (ou XYZ):", value=v_salvo_72, key=f"txt_72_val_{ano_sel}_fiscal", on_change=cb_72)
                    lk_detec_72 = re.findall(r'(https?://[^\s]+)', v_input_72 or "")
                    if lk_detec_72: st.markdown("**🔗 Detectado no campo:** " + " | ".join([f"[{u}]({u})" for u in lk_detec_72]))
                with col2:
                    lk72 = st.text_area("Link/Evidência Geral (7.2):", value=evidencia_72_salva, key=f"l72_in_{ano_sel}_fiscal", on_change=cb_72, height=100)
                    if lk72: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk72 or "")]))

                pts_exibido_72 = d72.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_72 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 7.2: {pts_exibido_72:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("7.2", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 7.3 • TOTALMENTE INDEPENDENTE (CHECKLIST)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q7_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 7.3 - Critérios Estabelecidos para Isenção", expanded=True):
                st.subheader("7.3 • Critérios de Concessão de Isenção")
                st.write("**Assinale os critérios estabelecidos para a concessão de isenção total ou parcial do IPTU: (Checklist)**")
                
                d73 = res_data.get("7.3", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_73_salva = d73.get("link", "")
                
                try:
                    val_banco73 = d73["valor"].replace("'", '"')
                    sel73 = json.loads(val_banco73)
                    if not isinstance(sel73, list): sel73 = []
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

                def cb_73():
                    res73_atual = []
                    for idx_c, opc_c in enumerate(opc73):
                        if st.session_state.get(f"chk_73_{idx_c}_{ano_sel}_fiscal", opc_c in sel73):
                            res73_atual.append(opc_c)
                    
                    lnk = st.session_state.get(f"l73_in_{ano_sel}_fiscal", evidencia_73_salva).strip()
                    
                    save_resp("7.3", json.dumps(res73_atual), 0.0, lnk)
                    res_data["7.3"] = {"valor": json.dumps(res73_atual), "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_73_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_73_salva or ""):
                        st.session_state[f"links_pendentes_7_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_7_3_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                for idx, opcao in enumerate(opc73):
                    target_col = c3 if idx % 2 == 0 else c4
                    with target_col:
                        st.checkbox(opcao, value=(opcao in sel73), key=f"chk_73_{idx}_{ano_sel}_fiscal", on_change=cb_73)

                st.markdown("---")
                lk73 = st.text_area("Link/Evidência (7.3):", value=evidencia_73_salva, key=f"l73_in_{ano_sel}_fiscal", on_change=cb_73, height=100)
                if lk73: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk73 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 7.3: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("7.3", res_data, sufixo="fiscal")

        # =============================================================================
        # ESCUTA DOS GATILHOS DOS MODAIS (INLINE)
        # =============================================================================
        for q_id in ["7.0", "7.1", "7.2", "7.3"]:
            chv = q_id.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{chv}_{ano_sel}", False):
                modal_aviso_link(q_id, st.session_state.get(f"links_pendentes_{chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{chv}_{ano_sel}"] = False

        # -------------------------------------------------------------------------
        # SEÇÃO 4: ISSQN E ITBI
        # -------------------------------------------------------------------------
        st.markdown("### 4. ISSQN e ITBI")

        # =============================================================================
        # QUESITO 8.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 8.0 - Instituição do ISSQN", expanded=True):
                st.subheader("8.0 • Instituição do ISSQN")
                st.write("**O Imposto sobre Serviços de Qualquer Natureza (ISSQN) foi instituído no município?**")
                
                d80 = res_data.get("8.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc80 = ["Selecione...", "Sim – 01", "Não – 00"]
                v_salvo_80 = d80.get("valor", "Selecione...")
                if v_salvo_80 not in opc80: v_salvo_80 = "Selecione..."
                evidencia_80_salva = d80.get("link", "")

                def cb_80():
                    val = st.session_state.get(f"rad_80_{ano_sel}_fiscal", v_salvo_80)
                    lnk = st.session_state.get(f"txt_80_{ano_sel}_fiscal", evidencia_80_salva).strip()
                    pts80_nova = 1.0 if "Sim" in val else 0.0
                    
                    save_resp("8.0", val, float(pts80_nova), lnk)
                    res_data["8.0"] = {"valor": val, "pontos": float(pts80_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_80_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_80_salva or ""):
                        st.session_state[f"links_pendentes_8_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_8_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio("Selecione 8.0:", opc80, index=opc80.index(v_salvo_80), key=f"rad_80_{ano_sel}_fiscal", on_change=cb_80)
                with c2: 
                    lk80 = st.text_area("Link/Evidência (8.0):", value=evidencia_80_salva, key=f"txt_80_{ano_sel}_fiscal", on_change=cb_80, height=100)
                    if lk80: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk80 or "")]))
                        
                pts_exibido_80 = d80.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 8.0: {pts_exibido_80:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("8.0", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 8.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 8.1 - Atualização da Legislação do ISSQN", expanded=True):
                st.subheader("8.1 • Atualização Normativa (LC 157/2016)")
                st.write("**O Município atualizou sua legislação conforme as novas hipóteses de incidência de ISS (LC 157/2016)?**")
                
                d81 = res_data.get("8.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc81 = ["Selecione...", "Sim – 02", "Não – 00"]
                v_salvo_81 = d81.get("valor", "Selecione...")
                if v_salvo_81 not in opc81: v_salvo_81 = "Selecione..."
                evidencia_81_salva = d81.get("link", "")

                def cb_81():
                    val = st.session_state.get(f"rad_81_{ano_sel}_fiscal", v_salvo_81)
                    lnk = st.session_state.get(f"txt_81_{ano_sel}_fiscal", evidencia_81_salva).strip()
                    pts81_nova = 2.0 if "Sim" in val else 0.0
                    
                    save_resp("8.1", val, float(pts81_nova), lnk)
                    res_data["8.1"] = {"valor": val, "pontos": float(pts81_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_81_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_81_salva or ""):
                        st.session_state[f"links_pendentes_8_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_8_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio("Selecione 8.1:", opc81, index=opc81.index(v_salvo_81), key=f"rad_81_{ano_sel}_fiscal", on_change=cb_81)
                with c2: 
                    lk81 = st.text_area("Link/Evidência (8.1):", value=evidencia_81_salva, key=f"txt_81_{ano_sel}_fiscal", on_change=cb_81, height=100)
                    if lk81: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk81 or "")]))
                        
                pts_exibido_81 = d81.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 8.1: {pts_exibido_81:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("8.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 8.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 8.2 - Rotina de Fiscalização do ISSQN", expanded=True):
                st.subheader("8.2 • Mecanismos de Combate à Sonegação")
                st.write("**Houve rotina de fiscalização para detectar contribuintes que deixaram de emitir a Nota Fiscal de Serviços por determinado período ou que apresentaram queda acentuada em suas operações, a fim de detectar o fim das atividades ou a sonegação do ISSQN?**")
                
                d82 = res_data.get("8.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc82 = ["Selecione...", "Sim por meio de sistema automatizado – 15", "Sim, manualmente – 08", "Não – 00"]
                v_salvo_82 = d82.get("valor", "Selecione...")
                if v_salvo_82 not in opc82: v_salvo_82 = "Selecione..."
                evidencia_82_salva = d82.get("link", "")

                def cb_82():
                    val = st.session_state.get(f"rad_82_{ano_sel}_fiscal", v_salvo_82)
                    lnk = st.session_state.get(f"txt_82_{ano_sel}_fiscal", evidencia_82_salva).strip()
                    pts82_nova = 15.0 if "automatizado" in val else (8.0 if "manualmente" in val else 0.0)
                    
                    save_resp("8.2", val, float(pts82_nova), lnk)
                    res_data["8.2"] = {"valor": val, "pontos": float(pts82_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_82_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_82_salva or ""):
                        st.session_state[f"links_pendentes_8_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_8_2_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio("Selecione 8.2:", opc82, index=opc82.index(v_salvo_82), key=f"rad_82_{ano_sel}_fiscal", on_change=cb_82)
                with c2: 
                    lk82 = st.text_area("Link/Evidência (8.2):", value=evidencia_82_salva, key=f"txt_82_{ano_sel}_fiscal", on_change=cb_82, height=100)
                    if lk82: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk82 or "")]))
                        
                pts_exibido_82 = d82.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 8.2: {pts_exibido_82:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("8.2", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 8.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q8_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 8.3 - Autenticidade de Notas Fiscais", expanded=True):
                st.subheader("8.3 • Acesso Público à Consulta de NFS-e")
                st.write("**A pesquisa de autenticidade de notas fiscais eletrônicas está disponível ao público?**")
                
                d83 = res_data.get("8.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc83 = [
                    "Selecione...",
                    "Sim, sem restrição – 00", 
                    "Sim, com restrição (Ex.: há necessidade de cadastro para acessar o resultado da pesquisa) – -09 (perde 09 pontos)", 
                    "Serviço não disponibilizado – -15", 
                    "Não implantou a NFS-e – -15"
                ]
                v_salvo_83 = d83.get("valor", "Selecione...")
                if v_salvo_83 not in opc83: v_salvo_83 = "Selecione..."
                evidencia_83_salva = d83.get("link", "")

                def cb_83():
                    val = st.session_state.get(f"rad_83_{ano_sel}_fiscal", v_salvo_83)
                    lnk = st.session_state.get(f"txt_83_{ano_sel}_fiscal", evidencia_83_salva).strip()
                    
                    if val == "Sim, sem restrição – 00":
                        pts83_nova = 0.0
                    elif "com restrição" in val:
                        pts83_nova = -9.0
                    elif val == "Selecione...":
                        pts83_nova = 0.0
                    else:
                        pts83_nova = -15.0
                    
                    save_resp("8.3", val, float(pts83_nova), lnk)
                    res_data["8.3"] = {"valor": val, "pontos": float(pts83_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_83_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_83_salva or ""):
                        st.session_state[f"links_pendentes_8_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_8_3_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio("Selecione 8.3:", opc83, index=opc83.index(v_salvo_83), key=f"rad_83_{ano_sel}_fiscal", on_change=cb_83)
                with c2: 
                    lk83 = st.text_area("Link/Evidência (8.3):", value=evidencia_83_salva, key=f"txt_83_{ano_sel}_fiscal", on_change=cb_83, height=100)
                    if lk83: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk83 or "")]))
                        
                pts_exibido_83 = d83.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_83 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 8.3: {pts_exibido_83:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("8.3", res_data, sufixo="fiscal")

        # =============================================================================
        # ESCUTA DOS GATILHOS DOS MODAIS (INLINE)
        # =============================================================================
        for q_id in ["8.0", "8.1", "8.2", "8.3"]:
            chv = q_id.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{chv}_{ano_sel}", False):
                modal_aviso_link(q_id, st.session_state.get(f"links_pendentes_{chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{chv}_{ano_sel}"] = False

# =============================================================================
        # QUESITO 9.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.0 - Regulamentação do ITBI", expanded=True):
                st.subheader("9.0 • Regulamentação do ITBI")
                st.write("**O Imposto sobre Transmissão de Bens Imóveis (ITBI) foi regulamentado?**")
                
                d90 = res_data.get("9.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc90 = ["Selecione...", "Sim", "Não"]
                v_salvo_90 = d90.get("valor", "Selecione...")
                if v_salvo_90 not in opc90: v_salvo_90 = "Selecione..."
                evidencia_90_salva = d90.get("link", "")

                def cb_90():
                    val = st.session_state.get(f"rad_90_{ano_sel}_fiscal", v_salvo_90)
                    lnk = st.session_state.get(f"txt_90_{ano_sel}_fiscal", evidencia_90_salva).strip()
                    
                    save_resp("9.0", val, 0.0, lnk)
                    res_data["9.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_90_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_90_salva or ""):
                        st.session_state[f"links_pendentes_9_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_9_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 9.0:", opc90, index=opc90.index(v_salvo_90), key=f"rad_90_{ano_sel}_fiscal", on_change=cb_90)
                with c2:
                    lk90 = st.text_area("Link/Evidência Geral (9.0):", value=evidencia_90_salva, key=f"txt_90_{ano_sel}_fiscal", on_change=cb_90, height=100)
                    if lk90: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk90 or "")]))
            
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 9.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("9.0", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 9.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.1 - Instrumento Normativo do ITBI", expanded=True):
                st.subheader("9.1 • Instrumento de Regulamentação")
                st.write("**Informe o instrumento normativo de regulamentação do ITBI, Número e Data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")
                
                d91 = res_data.get("9.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_91 = d91.get("valor", "")
                evidencia_91_salva = d91.get("link", "")

                def cb_91():
                    val = st.session_state.get(f"txt_91_val_{ano_sel}_fiscal", v_salvo_91).strip()
                    lnk = st.session_state.get(f"l91_in_{ano_sel}_fiscal", evidencia_91_salva).strip()
                    
                    save_resp("9.1", val, 0.0, lnk)
                    res_data["9.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_91_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_91_salva or ""):
                        st.session_state[f"links_pendentes_9_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_9_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input("Instrumento normativo do ITBI (Nº e Data):", value=v_salvo_91, key=f"txt_91_val_{ano_sel}_fiscal", on_change=cb_91)
                with c2:
                    lk91 = st.text_area("Link/Evidência (9.1):", value=evidencia_91_salva, key=f"l91_in_{ano_sel}_fiscal", on_change=cb_91, height=100)
                    if lk91: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk91 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 9.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("9.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 9.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.2 - Página de Divulgação do ITBI", expanded=True):
                st.subheader("9.2 • Divulgação Eletrônica da Regulamentação")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da regulamentação do ITBI:**")
                st.caption("⚠️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                d92 = res_data.get("9.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_92 = d92.get("valor", "")
                evidencia_92_salva = d92.get("link", "")

                def cb_92():
                    val = st.session_state.get(f"txt_92_val_{ano_sel}_fiscal", v_salvo_92).strip()
                    lnk = st.session_state.get(f"l92_in_{ano_sel}_fiscal", evidencia_92_salva).strip()
                    pts92_nova = -3.0 if val.upper() == "XYZ" else 0.0
                    
                    save_resp("9.2", val, float(pts92_nova), lnk)
                    res_data["9.2"] = {"valor": val, "pontos": float(pts92_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_92_salva& lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_92_salva or ""):
                        st.session_state[f"links_pendentes_9_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_9_2_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    v_input_92 = st.text_input("Link de divulgação do ITBI (ou XYZ):", value=v_salvo_92, key=f"txt_92_val_{ano_sel}_fiscal", on_change=cb_92)
                    lk_detec_92 = re.findall(r'(https?://[^\s]+)', v_input_92 or "")
                    if lk_detec_92: st.markdown("**🔗 Detectado no campo:** " + " | ".join([f"[{u}]({u})" for u in lk_detec_92]))
                with c2:
                    lk92 = st.text_area("Link/Evidência Geral (9.2):", value=evidencia_92_salva, key=f"l92_in_{ano_sel}_fiscal", on_change=cb_92, height=100)
                    if lk92: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk92 or "")]))

                pts_exibido_92 = d92.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_92 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 9.2: {pts_exibido_92:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("9.2", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 9.3 • TOTALMENTE INDEPENDENTE (CHECKLIST)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.3 - Registro e Emissão da Guia do ITBI", expanded=True):
                st.subheader("9.3 • Emissão de Guia de Recolhimento")
                st.write("**Assinale a forma de registro e emissão da guia de recolhimento do ITBI: (Checklist)**")
                st.caption("🚨 *Nota: A mera impressão da guia de recolhimento do ITBI não é considerada forma de emissão.*")
                
                d93 = res_data.get("9.3", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_73_salva_ou_93 = d93.get("link", "")
                
                try:
                    val_banco93 = d93["valor"].replace("'", '"')
                    sel93 = json.loads(val_banco93)
                    if not isinstance(sel93, list): sel93 = []
                except:
                    sel93 = []

                opc93 = ["Site da Prefeitura", "Órgão Fazendário", "Cartório autorizado", "Outros"]

                def cb_93():
                    res93_atual = []
                    for idx_c, opc_c in enumerate(opc93):
                        if st.session_state.get(f"chk_93_{idx_c}_{ano_sel}_fiscal", opc_c in sel93):
                            res93_atual.append(opc_c)
                    
                    lnk = st.session_state.get(f"l93_in_{ano_sel}_fiscal", evidencia_73_salva_ou_93).strip()
                    
                    save_resp("9.3", json.dumps(res93_atual), 0.0, lnk)
                    res_data["9.3"] = {"valor": json.dumps(res93_atual), "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_73_salva_ou_93 and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_73_salva_ou_93 or ""):
                        st.session_state[f"links_pendentes_9_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_9_3_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                for idx, opcao in enumerate(opc93):
                    target_col = c3 if idx % 2 == 0 else c4
                    with target_col:
                        st.checkbox(opcao, value=(opcao in sel93), key=f"chk_93_{idx}_{ano_sel}_fiscal", on_change=cb_93)

                st.markdown("---")
                lk93 = st.text_area("Link/Evidência (9.3):", value=evidencia_73_salva_ou_93, key=f"l93_in_{ano_sel}_fiscal", on_change=cb_93, height=100)
                if lk93: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk93 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 9.3: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("9.3", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 9.4 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_4_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.4 - Informações de Transmissões Imobiliárias", expanded=True):
                st.subheader("9.4 • Obrigatoriedade dos Cartórios de Registro")
                st.write("**O município instituiu normativo que obrigue o(s) Cartório(s) de Registro de Imóveis e Distribuidor(es) a informar periodicamente as transmissões imobiliárias realizadas no seu território, para fins de incidência do ITBI?**")
                
                d94 = res_data.get("9.4", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc94 = ["Selecione...", "Sim – 02", "Não – 00"]
                v_salvo_94 = d94.get("valor", "Selecione...")
                if v_salvo_94 not in opc94: v_salvo_94 = "Selecione..."
                evidencia_94_salva = d94.get("link", "")

                def cb_94():
                    val = st.session_state.get(f"rad_94_{ano_sel}_fiscal", v_salvo_94)
                    lnk = st.session_state.get(f"txt_94_{ano_sel}_fiscal", evidencia_94_salva).strip()
                    pts94_nova = 2.0 if "Sim" in val else 0.0
                    
                    save_resp("9.4", val, float(pts94_nova), lnk)
                    res_data["9.4"] = {"valor": val, "pontos": float(pts94_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_94_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_94_salva or ""):
                        st.session_state[f"links_pendentes_9_4_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_9_4_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio("Selecione 9.4:", opc94, index=opc94.index(v_salvo_94), key=f"rad_94_{ano_sel}_fiscal", on_change=cb_94)
                with c2: 
                    lk94 = st.text_area("Link/Evidência (9.4):", value=evidencia_94_salva, key=f"txt_94_{ano_sel}_fiscal", on_change=cb_94, height=100)
                    if lk94: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk94 or "")]))
                        
                pts_exibido_94 = d94.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 9.4: {pts_exibido_94:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("9.4", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 9.4.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_4_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.4.1 - Aplicação de Penalidades aos Cartórios", expanded=True):
                st.subheader("9.4.1 • Aplicação de Penalidade/Multas")
                st.write("**O município aplica penalidade ou multa aos Cartórios, quando não cumpridos os termos da lei mencionada na resposta do item anterior?**")
                
                d941 = res_data.get("9.4.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc941 = ["Selecione...", "Sim – 03", "Não – 00"]
                v_salvo_941 = d941.get("valor", "Selecione...")
                if v_salvo_941 not in opc941: v_salvo_941 = "Selecione..."
                evidencia_941_salva = d941.get("link", "")

                def cb_941():
                    val = st.session_state.get(f"rad_941_{ano_sel}_fiscal", v_salvo_941)
                    lnk = st.session_state.get(f"txt_941_{ano_sel}_fiscal", evidencia_941_salva).strip()
                    pts941_nova = 3.0 if "Sim" in val else 0.0
                    
                    save_resp("9.4.1", val, float(pts941_nova), lnk)
                    res_data["9.4.1"] = {"valor": val, "pontos": float(pts941_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_941_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_941_salva or ""):
                        st.session_state[f"links_pendentes_9_4_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_9_4_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio("Selecione 9.4.1:", opc941, index=opc941.index(v_salvo_941), key=f"rad_941_{ano_sel}_fiscal", on_change=cb_941)
                with c2: 
                    lk941 = st.text_area("Link/Evidência (9.4.1):", value=evidencia_941_salva, key=f"txt_941_{ano_sel}_fiscal", on_change=cb_941, height=100)
                    if lk941: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk941 or "")]))
                        
                pts_exibido_941 = d941.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 9.4.1: {pts_exibido_941:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("9.4.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 9.5 • TOTALMENTE INDEPENDENTE (FORMULÁRIO MULTI-CHECK DOS MEIOS DE PAGAMENTO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_5_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.5 - Forma de Recolhimento da Guia", expanded=True):
                st.subheader("9.5 • Meios de Recolhimento do ITBI")
                st.write("**Assinale a forma de recolhimento da guia do ITBI:**")
                
                d95 = res_data.get("9.5", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                valor_salvo_95 = d95.get("valor", "") or ""
                evidencia_95_salva = d95.get("link", "")

                def cb_95():
                    lista_selecionados = []
                    if st.session_state.get(f"chk_95_banco_{ano_sel}_fiscal", "Sistema Bancário" in valor_salvo_95): lista_selecionados.append("Sistema Bancário")
                    if st.session_state.get(f"chk_95_caixa_{ano_sel}_fiscal", "Diretamente no Caixa da Prefeitura" in valor_salvo_95): lista_selecionados.append("Diretamente no Caixa da Prefeitura")
                    if st.session_state.get(f"chk_95_loterica_{ano_sel}_fiscal", "Lotérica" in valor_salvo_95): lista_selecionados.append("Lotérica")
                    if st.session_state.get(f"chk_95_outros_{ano_sel}_fiscal", "Outros" in valor_salvo_95): lista_selecionados.append("Outros")
                    
                    str_resultado = "/".join(lista_selecionados) if lista_selecionados else "Nenhuma"
                    lnk = st.session_state.get(f"txt_95_{ano_sel}_fiscal", evidencia_95_salva).strip()
                    
                    save_resp("9.5", str_resultado, 0.0, lnk)
                    res_data["9.5"] = {"valor": str_resultado, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_95_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_95_salva or ""):
                        st.session_state[f"links_pendentes_9_5_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_9_5_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.write("*Selecione todas as opções aplicáveis:*")
                    st.checkbox("Sistema Bancário", value=("Sistema Bancário" in valor_salvo_95), key=f"chk_95_banco_{ano_sel}_fiscal", on_change=cb_95)
                    st.checkbox("Diretamente no Caixa da Prefeitura", value=("Diretamente no Caixa da Prefeitura" in valor_salvo_95), key=f"chk_95_caixa_{ano_sel}_fiscal", on_change=cb_95)
                    st.checkbox("Lotérica", value=("Lotérica" in valor_salvo_95), key=f"chk_95_loterica_{ano_sel}_fiscal", on_change=cb_95)
                    st.checkbox("Outros", value=("Outros" in valor_salvo_95), key=f"chk_95_outros_{ano_sel}_fiscal", on_change=cb_95)
                with c2:
                    lk95 = st.text_area("Link/Evidência (9.5):", value=evidencia_95_salva, key=f"txt_95_{ano_sel}_fiscal", on_change=cb_95, height=150)
                    if lk95: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk95 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 9.5: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("9.5", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 9.6 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q9_6_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 9.6 - Progressividade do ITBI (Súmula 656 STF)", expanded=True):
                st.subheader("9.6 • Alíquotas Progressivas Venais")
                st.write("**O município estabelece alíquotas progressivas para o ITBI, com base no valor venal? Súmula 656, do Supremo Tribunal Federal**")
                
                d96 = res_data.get("9.6", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc96 = ["Selecione...", "Sim – -30", "Não – 00"]
                v_salvo_96 = d96.get("valor", "Selecione...")
                if v_salvo_96 not in opc96: v_salvo_96 = "Selecione..."
                evidencia_96_salva = d96.get("link", "")

                def cb_96():
                    val = st.session_state.get(f"rad_96_{ano_sel}_fiscal", v_salvo_96)
                    lnk = st.session_state.get(f"txt_96_{ano_sel}_fiscal", evidencia_96_salva).strip()
                    pts96_nova = -30.0 if "Sim" in val else 0.0
                    
                    save_resp("9.6", val, float(pts96_nova), lnk)
                    res_data["9.6"] = {"valor": val, "pontos": float(pts96_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_96_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_96_salva or ""):
                        st.session_state[f"links_pendentes_9_6_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_9_6_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio("Selecione 9.6:", opc96, index=opc96.index(v_salvo_96), key=f"rad_96_{ano_sel}_fiscal", on_change=cb_96)
                with c2: 
                    lk96 = st.text_area("Link/Evidência (9.6):", value=evidencia_96_salva, key=f"txt_96_{ano_sel}_fiscal", on_change=cb_96, height=100)
                    if lk96: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk96 or "")]))
                        
                pts_exibido_96 = d96.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_96 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 9.6: {pts_exibido_96:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("9.6", res_data, sufixo="fiscal")

        # =============================================================================
        # ESCUTA DOS GATILHOS DOS MODAIS (INLINE)
        # =============================================================================
        for q_id in ["9.0", "9.1", "9.2", "9.3", "9.4", "9.4.1", "9.5", "9.6"]:
            chv = q_id.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{chv}_{ano_sel}", False):
                modal_aviso_link(q_id, st.session_state.get(f"links_pendentes_{chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{chv}_{ano_sel}"] = False

        # -------------------------------------------------------------------------
        # SEÇÃO 5: CIP, IRRF E RENÚNCIA
        # -------------------------------------------------------------------------
        st.markdown("### 5. CIP, IRRF e Renúncia de Receita")

        # =============================================================================
        # QUESITO 10.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 10.0 - Instituição da CIP", expanded=True):
                st.subheader("10.0 • Instituição da CIP")
                st.write("**A Contribuição para Custeio do Serviço de Iluminação Pública (CIP) foi instituída?**")
                
                d100 = res_data.get("10.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc100 = ["Selecione...", "Sim", "Não"]
                v_salvo_100 = d100.get("valor", "Selecione...")
                if v_salvo_100 not in opc100: v_salvo_100 = "Selecione..."
                evidencia_100_salva = d100.get("link", "")

                def cb_100():
                    val = st.session_state.get(f"rad_100_{ano_sel}_fiscal", v_salvo_100)
                    lnk = st.session_state.get(f"txt_100_{ano_sel}_fiscal", evidencia_100_salva).strip()
                    
                    save_resp("10.0", val, 0.0, lnk)
                    res_data["10.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_100_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_100_salva or ""):
                        st.session_state[f"links_pendentes_10_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_10_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 10.0:", opc100, index=opc100.index(v_salvo_100), key=f"rad_100_{ano_sel}_fiscal", on_change=cb_100)
                with c2:
                    lk100 = st.text_area("Link/Evidência Geral (10.0):", value=evidencia_100_salva, key=f"txt_100_{ano_sel}_fiscal", on_change=cb_100, height=100)
                    if lk100: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk100 or "")]))
            
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 10.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("10.0", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 10.1 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 10.1 - Instrumento Normativo da CIP", expanded=True):
                st.subheader("10.1 • Instrumento de Regulamentação")
                st.write("**Informe o instrumento normativo de instituição da Contribuição para Custeio do Serviço de Iluminação Pública (CIP), número e data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")
                
                d101 = res_data.get("10.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_101 = d101.get("valor", "")
                evidencia_101_salva = d101.get("link", "")

                def cb_101():
                    val = st.session_state.get(f"txt_101_val_{ano_sel}_fiscal", v_salvo_101).strip()
                    lnk = st.session_state.get(f"l101_in_{ano_sel}_fiscal", evidencia_101_salva).strip()
                    
                    save_resp("10.1", val, 0.0, lnk)
                    res_data["10.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_101_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_101_salva or ""):
                        st.session_state[f"links_pendentes_10_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_10_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input("Instrumento normativo da CIP (Nº e Data):", value=v_salvo_101, key=f"txt_101_val_{ano_sel}_fiscal", on_change=cb_101)
                with c2:
                    lk101 = st.text_area("Link/Evidência (10.1):", value=evidencia_101_salva, key=f"l101_in_{ano_sel}_fiscal", on_change=cb_101, height=100)
                    if lk101: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk101 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 10.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("10.1", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 10.2 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 10.2 - Página de Divulgação da CIP", expanded=True):
                st.subheader("10.2 • Divulgação Eletrônica do Normativo")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do instrumento normativo de instituição da CIP:**")
                st.caption("⚠️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                d102 = res_data.get("10.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_102 = d102.get("valor", "")
                evidencia_102_salva = d102.get("link", "")

                def cb_102():
                    val = st.session_state.get(f"txt_102_val_{ano_sel}_fiscal", v_salvo_102).strip()
                    lnk = st.session_state.get(f"l102_in_{ano_sel}_fiscal", evidencia_102_salva).strip()
                    pts102_nova = -3.0 if val.upper() == "XYZ" else 0.0
                    
                    save_resp("10.2", val, float(pts102_nova), lnk)
                    res_data["10.2"] = {"valor": val, "pontos": float(pts102_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_102_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_102_salva or ""):
                        st.session_state[f"links_pendentes_10_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_10_2_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    v_input_102 = st.text_input("Link de divulgação da CIP (ou XYZ):", value=v_salvo_102, key=f"txt_102_val_{ano_sel}_fiscal", on_change=cb_102)
                    lk_detec_102 = re.findall(r'(https?://[^\s]+)', v_input_102 or "")
                    if lk_detec_102: st.markdown("**🔗 Detectado no campo:** " + " | ".join([f"[{u}]({u})" for u in lk_detec_102]))
                with c2:
                    lk102 = st.text_area("Link/Evidência Geral (10.2):", value=evidencia_102_salva, key=f"l102_in_{ano_sel}_fiscal", on_change=cb_102, height=100)
                    if lk102: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk102 or "")]))

                pts_exibido_102 = d102.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_102 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 10.2: {pts_exibido_102:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("10.2", res_data, sufixo="fiscal")

        # =============================================================================
        # QUESITO 10.3 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q10_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 10.3 - Movimentação em Contas Específicas", expanded=True):
                st.subheader("10.3 • Exclusividade de Contas Bancárias")
                st.write("**Os recursos da Contribuição para Custeio do Serviço de Iluminação Pública (CIP) foram movimentados em contas específicas?**")
                
                d103 = res_data.get("10.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc103 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                v_salvo_103 = d103.get("valor", "Selecione...")
                if v_salvo_103 not in opc103: v_salvo_103 = "Selecione..."
                evidencia_103_salva = d103.get("link", "")

                def cb_103():
                    val = st.session_state.get(f"rad_103_{ano_sel}_fiscal", v_salvo_103)
                    lnk = st.session_state.get(f"txt_103_{ano_sel}_fiscal", evidencia_103_salva).strip()
                    pts103_nova = -5.0 if "Não" in val else 0.0
                    
                    save_resp("10.3", val, float(pts103_nova), lnk)
                    res_data["10.3"] = {"valor": val, "pontos": float(pts103_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_103_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_103_salva or ""):
                        st.session_state[f"links_pendentes_10_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_10_3_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio("Selecione 10.3:", opc103, index=opc103.index(v_salvo_103), key=f"rad_103_{ano_sel}_fiscal", on_change=cb_103)
                with c4:
                    l103 = st.text_area("Link/Evidência de Conta Bancária Exclusiva (10.3):", value=evidencia_103_salva, key=f"txt_103_{ano_sel}_fiscal", on_change=cb_103, height=100)
                    if l103: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', l103 or "")]))

                pts_exibido_103 = d103.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_103 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 10.3: {pts_exibido_103:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("10.3", res_data, sufixo="fiscal")

        # =============================================================================
        # ESCUTA DOS GATILHOS DOS MODAIS (INLINE)
        # =============================================================================
        for q_id in ["10.0", "10.1", "10.2", "10.3"]:
            chv = q_id.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{chv}_{ano_sel}", False):
                modal_aviso_link(q_id, st.session_state.get(f"links_pendentes_{chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{chv}_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 11.0 • TOTALMENTE INDEPENDENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q11_0_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 11.0 - Regulamentação do IRRF", expanded=True):
                st.subheader("11.0 • Retenção de IRRF nas Contratações Municipais")
                st.write("**Houve regulamentação sobre a retenção de IRRF das contratações efetuadas pelo município nas compras de bens e serviços?**")
                
                d110 = res_data.get("11.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc110 = ["Selecione...", "Sim – 03", "Não – 00"]
                v_salvo_110 = d110.get("valor", "Selecione...")
                if v_salvo_110 not in opc110: v_salvo_110 = "Selecione..."
                evidencia_110_salva = d110.get("link", "")

                def cb_110():
                    val = st.session_state.get(f"rad_110_{ano_sel}_fiscal", v_salvo_110)
                    lnk = st.session_state.get(f"txt_110_{ano_sel}_fiscal", evidencia_110_salva).strip()
                    pts110_nova = 3.0 if "Sim" in val else 0.0
                    
                    save_resp("11.0", val, float(pts110_nova), lnk)
                    res_data["11.0"] = {"valor": val, "pontos": float(pts110_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_110_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_110_salva or ""):
                        st.session_state[f"links_pendentes_11_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1: 
                    st.radio("Selecione 11.0:", opc110, index=opc110.index(v_salvo_110), key=f"rad_110_{ano_sel}_fiscal", on_change=cb_110)
                with c2: 
                    lk110 = st.text_area("Link/Evidência (11.0):", value=evidencia_110_salva, key=f"txt_110_{ano_sel}_fiscal", on_change=cb_110, height=100)
                    if lk110: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk110 or "")]))
                        
                pts_exibido_110 = d110.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 11.0: {pts_exibido_110:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("11.0", res_data, sufixo="fiscal")

        # =============================================================================
        # ESCUTA DO GATILHO DO MODAL (INLINE)
        # =============================================================================
        if st.session_state.get(f"gatilho_modal_11_0_{ano_sel}", False):
            modal_aviso_link("11.0", st.session_state.get(f"links_pendentes_11_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_11_0_{ano_sel}"] = False

   # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.0 • REGISTRO DA RENÚNCIA DE RECEITAS
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 12.0 - Renúncia de Receitas ({ano_sel})", expanded=True):
                st.subheader("12.0 • Concessão de Benefícios / Incentivos")
                st.write(f"**No exercício de {ano_sel}, foram concedidos benefícios e incentivos de natureza tributária, financeira e creditícia da qual decorram em renúncia de receitas?**")
                
                d120 = res_data.get("12.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc120 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_120 = d120.get("valor", "Selecione...").split(" | ")[0] if d120.get("valor") else "Selecione..."
                if valor_limpo_120 not in opc120: valor_limpo_120 = "Selecione..."
                evidencia_120_salva = d120.get("link", "")

                def cb_120():
                    val_cru = st.session_state.get(f"rad_120_{ano_sel}_fiscal", valor_limpo_120)
                    lnk = st.session_state.get(f"txt_120_{ano_sel}_fiscal", evidencia_120_salva).strip()
                    val_com_ano = f"{val_cru} | Exercício Ref: {ano_sel}" if val_cru != "Selecione..." else "Selecione..."
                    
                    save_resp("12.0", val_com_ano, 0.0, lnk)
                    res_data["12.0"] = {"valor": val_com_ano, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_120_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_120_salva or ""):
                        st.session_state[f"links_pendentes_12_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 12.0:", opc120, index=opc120.index(valor_limpo_120), key=f"rad_120_{ano_sel}_fiscal", on_change=cb_120)
                with c2:
                    lk120 = st.text_area(f"Link/Evidência Geral ({ano_sel}):", value=evidencia_120_salva, key=f"txt_120_{ano_sel}_fiscal", on_change=cb_120, height=100)
                    if lk120: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk120 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 12.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.1 • NORMAS E PROCEDIMENTOS
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.1 - Normas de Renúncia", expanded=True):
                st.subheader("12.1 • Existência de Normas Regulamentares")
                st.write("**Há normas e procedures relativos à renúncia de receita?**")
                
                d121 = res_data.get("12.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc121 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                v_salvo_121 = d121.get("valor", "Selecione...")
                if v_salvo_121 not in opc121: v_salvo_121 = "Selecione..."
                evidencia_121_salva = d121.get("link", "")

                def cb_121():
                    val = st.session_state.get(f"rad_121_{ano_sel}_fiscal", v_salvo_121)
                    lnk = st.session_state.get(f"txt_121_{ano_sel}_fiscal", evidencia_121_salva).strip()
                    pts121_nova = -10.0 if "Não" in val else 0.0
                    
                    save_resp("12.1", val, float(pts121_nova), lnk)
                    res_data["12.1"] = {"valor": val, "pontos": float(pts121_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_121_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_121_salva or ""):
                        st.session_state[f"links_pendentes_12_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 12.1:", opc121, index=opc121.index(v_salvo_121), key=f"rad_121_{ano_sel}_fiscal", on_change=cb_121)
                with c2:
                    lk121 = st.text_area("Link/Evidência Normativa (12.1):", value=evidencia_121_salva, key=f"txt_121_{ano_sel}_fiscal", on_change=cb_121, height=100)
                    if lk121: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk121 or "")]))

                pts_exibido_121 = d121.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_121 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 12.1: {pts_exibido_121:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.1.1 • INSTRUMENTO NORMATIVO DO 12.1
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_1_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.1.1 - Identificação do Normativo", expanded=True):
                st.subheader("12.1.1 • Detalhes do Instrumento Legal")
                st.write("**Informe o instrumento normativo de regulamentação dos procedimentos relativos à renúncia de receita, Número e Data da publicação:**")
                
                d1211 = res_data.get("12.1.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_1211 = d1211.get("valor", "")
                evidencia_1211_salva = d1211.get("link", "")

                def cb_1211():
                    val = st.session_state.get(f"txt_1211_{ano_sel}_fiscal", v_salvo_1211).strip()
                    lnk = st.session_state.get(f"txt_lnk_1211_{ano_sel}_fiscal", evidencia_1211_salva).strip()
                    
                    save_resp("12.1.1", val, 0.0, lnk)
                    res_data["12.1.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1211_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1211_salva or ""):
                        st.session_state[f"links_pendentes_12_1_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_1_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input("Instrumento normativo (Nº e Data):", value=v_salvo_1211, key=f"txt_1211_{ano_sel}_fiscal", on_change=cb_1211)
                with c2:
                    lk1211 = st.text_area("Link/Evidência da Publicação (12.1.1):", value=evidencia_1211_salva, key=f"txt_lnk_1211_{ano_sel}_fiscal", on_change=cb_1211, height=100)
                    if lk1211: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1211 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 12.1.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.1.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.1.2 • URL DO NORMATIVO (TRAVA XYZ)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_1_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.1.2 - URL de Divulgação", expanded=True):
                st.subheader("12.1.2 • Endereço Eletrônico da Norma")
                st.write("**Informe a página eletrônica (link na internet) de divulgação do instrumento normativo de regulamentação:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                d1212 = res_data.get("12.1.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_1212 = d1212.get("valor", "")
                evidencia_1212_salva = d1212.get("link", "")

                def cb_1212():
                    val = st.session_state.get(f"txt_1212_{ano_sel}_fiscal", v_salvo_1212).strip()
                    lnk = st.session_state.get(f"txt_lnk_1212_{ano_sel}_fiscal", evidencia_1212_salva).strip()
                    pts1212_nova = -3.0 if val.upper() == "XYZ" else 0.0
                    
                    save_resp("12.1.2", val, float(pts1212_nova), lnk)
                    res_data["12.1.2"] = {"valor": val, "pontos": float(pts1212_nova), "link": lnk}
                    
                    lk_combinados = re.findall(r'(https?://[^\s]+)', f"{val} {lnk}")
                    lk_antigos = re.findall(r'(https?://[^\s]+)', f"{v_salvo_1212} {evidencia_1212_salva}")
                    if lk_combinados and lk_combinados != lk_antigos:
                        st.session_state[f"links_pendentes_12_1_2_{ano_sel}"] = lk_combinados
                        st.session_state[f"gatilho_modal_12_1_2_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    v1212_input = st.text_input("Página eletrônica (ou XYZ) - 12.1.2:", value=v_salvo_1212, key=f"txt_1212_{ano_sel}_fiscal", on_change=cb_1212)
                    if v1212_input and not v1212_input.upper() == "XYZ": st.markdown("**🔗 URL Informada:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', v1212_input or "")]))
                with c2:
                    lk1212 = st.text_area("Evidência Adicional (12.1.2):", value=evidencia_1212_salva, key=f"txt_lnk_1212_{ano_sel}_fiscal", on_change=cb_1212, height=100)
                    if lk1212: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1212 or "")]))

                pts_exibido_1212 = d1212.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_1212 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 12.1.2: {pts_exibido_1212:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.1.2", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.2 • ACOMPANHAMENTO E AVALIAÇÃO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.2 - Avaliação Periódica", expanded=True):
                st.subheader("12.2 • Monitoramento das Renúncias")
                st.write("**A Prefeitura Municipal realizou acompanhamento e (re)avaliação das renúncias de receita?**")
                
                d122 = res_data.get("12.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc122 = [
                    "Selecione...",
                    "Sim, de todas as renúncias de receita – 00",
                    "Sim, de parte das renúncias de receita – -02 (perde 02 pontos)",
                    "Não – -05 (perde 05 pontos)"
                ]
                v_salvo_122 = d122.get("valor", "Selecione...")
                if v_salvo_122 not in opc122: v_salvo_122 = "Selecione..."
                evidencia_122_salva = d122.get("link", "")

                def cb_122():
                    val = st.session_state.get(f"rad_122_{ano_sel}_fiscal", v_salvo_122)
                    lnk = st.session_state.get(f"txt_122_{ano_sel}_fiscal", evidencia_122_salva).strip()
                    
                    if "todas" in val: pts122_nova = 0.0
                    elif "parte" in val: pts122_nova = -2.0
                    elif val == "Selecione...": pts122_nova = 0.0
                    else: pts122_nova = -5.0
                    
                    save_resp("12.2", val, float(pts122_nova), lnk)
                    res_data["12.2"] = {"valor": val, "pontos": float(pts122_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_122_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_122_salva or ""):
                        st.session_state[f"links_pendentes_12_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_2_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio("Selecione 12.2:", opc122, index=opc122.index(v_salvo_122), key=f"rad_122_{ano_sel}_fiscal", on_change=cb_122)
                with c4:
                    lk122 = st.text_area("Link/Evidência do Acompanhamento (12.2):", value=evidencia_122_salva, key=f"txt_122_{ano_sel}_fiscal", on_change=cb_122, height=100)
                    if lk122: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk122 or "")]))

                pts_exibido_122 = d122.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_122 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 12.2: {pts_exibido_122:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.2", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.3 • DEMONSTRATIVO NA LDO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.3 - Demonstrativo AMF / LDO", expanded=True):
                st.subheader("12.3 • Previsão no Anexo de Metas Fiscais")
                st.write("**O Anexo de Metas Fiscais, que integra a LDO, contém demonstrativo da estimativa e compensação da renúncia de receita para o respectivo exercício orçamentário?**")
                
                d123 = res_data.get("12.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc123 = [
                    "Selecione...",
                    "Todas as renúncias concedidas estão contidas no demonstrativo – 00",
                    "A maior parte das renúncias concedidas estão contidas no demonstrativo – -01 (perde 01 ponto)",
                    "A menor parte das renúncias concedidas estão contidas no demonstrativo – -03 (perde 03 pontos)",
                    "Não há demonstrativo – -05 (perde 05 pontos)"
                ]
                v_salvo_123 = d123.get("valor", "Selecione...")
                if v_salvo_123 not in opc123: v_salvo_123 = "Selecione..."
                evidencia_123_salva = d123.get("link", "")

                def cb_123():
                    val = st.session_state.get(f"rad_123_{ano_sel}_fiscal", v_salvo_123)
                    lnk = st.session_state.get(f"txt_123_{ano_sel}_fiscal", evidencia_123_salva).strip()
                    
                    if "Todas" in val: pts123_nova = 0.0
                    elif "maior" in val: pts123_nova = -1.0
                    elif "menor" in val: pts123_nova = -3.0
                    elif val == "Selecione...": pts123_nova = 0.0
                    else: pts123_nova = -5.0
                    
                    save_resp("12.3", val, float(pts123_nova), lnk)
                    res_data["12.3"] = {"valor": val, "pontos": float(pts123_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_123_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_123_salva or ""):
                        st.session_state[f"links_pendentes_12_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_3_{ano_sel}"] = True

                c5, c6 = st.columns([1, 1])
                with c5:
                    st.radio("Selecione 12.3:", opc123, index=opc123.index(v_salvo_123), key=f"rad_123_{ano_sel}_fiscal", on_change=cb_123)
                with c6:
                    lk123 = st.text_area("Link/Evidência do AMF da LDO (12.3):", value=evidencia_123_salva, key=f"txt_123_{ano_sel}_fiscal", on_change=cb_123, height=100)
                    if lk123: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk123 or "")]))

                pts_exibido_123 = d123.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_123 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 12.3: {pts_exibido_123:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.3", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.3.1 • COMPATIBILIDADE DE VALORES
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_3_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.3.1 - Conformidade Orçamentária", expanded=True):
                st.subheader("12.3.1 • Compatibilidade Fiscal das Estimativas")
                st.write(f"**O valor da renúncia de receita de {ano_sel} está compatível com a estimativa constante no Anexo de Metas Fiscais da Lei de Diretrizes Orçamentárias?**")
                
                d1231 = res_data.get("12.3.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc1231 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                v_salvo_1231 = d1231.get("valor", "Selecione...")
                if v_salvo_1231 not in opc1231: v_salvo_1231 = "Selecione..."
                evidencia_1231_salva = d1231.get("link", "")

                def cb_1231():
                    val = st.session_state.get(f"rad_1231_{ano_sel}_fiscal", v_salvo_1231)
                    lnk = st.session_state.get(f"txt_1231_{ano_sel}_fiscal", evidencia_1231_salva).strip()
                    pts1231_nova = -5.0 if "Não" in val else 0.0
                    
                    save_resp("12.3.1", val, float(pts1231_nova), lnk)
                    res_data["12.3.1"] = {"valor": val, "pontos": float(pts1231_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1231_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1231_salva or ""):
                        st.session_state[f"links_pendentes_12_3_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_3_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 12.3.1:", opc1231, index=opc1231.index(v_salvo_1231), key=f"rad_1231_{ano_sel}_fiscal", on_change=cb_1231)
                with c2:
                    lk1231 = st.text_area("Link/Evidência de Compatibilidade (12.3.1):", value=evidencia_1231_salva, key=f"txt_1231_{ano_sel}_fiscal", on_change=cb_1231, height=100)
                    if lk1231: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1231 or "")]))

                pts_exibido_1231 = d1231.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_1231 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 12.3.1: {pts_exibido_1231:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.3.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.4 • MENSURAÇÃO FINANCEIRA (MONETÁRIO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_4_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.4 - Valor Total da Renúncia", expanded=True):
                st.subheader("12.4 • Montante Financeiro Estimado")
                st.write(f"**Informe o valor das renúncias no exercício de {ano_sel}:**")
                
                d124 = res_data.get("12.4", {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}) or {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}
                val_inicial = d124.get("valor", "R$ 0,00")
                if not val_inicial.startswith("R$"): val_inicial = f"R$ {val_inicial}"
                evidencia_124_salva = d124.get("link", "")

                def cb_124():
                    v_cru = st.session_state.get(f"txt_124_dinamico_{ano_sel}_fiscal", val_inicial)
                    lnk = st.session_state.get(f"txt_lnk_124_{ano_sel}_fiscal", evidencia_124_salva).strip()
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
                        v124_salvar = val_inicial  # Reverte em caso de falha de parsing numérico
                        
                    save_resp("12.4", v124_salvar, 0.0, lnk)
                    res_data["12.4"] = {"valor": v124_salvar, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_124_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_124_salva or ""):
                        st.session_state[f"links_pendentes_12_4_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_4_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input("Informe o Valor Total (R$):", value=val_inicial, placeholder="Ex: 100.000,00", key=f"txt_124_dinamico_{ano_sel}_fiscal", on_change=cb_124)
                with c2:
                    lk124 = st.text_area("Link/Evidência da Memória de Cálculo (12.4):", value=evidencia_124_salva, key=f"txt_lnk_124_{ano_sel}_fiscal", on_change=cb_124, height=100)
                    if lk124: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk124 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 12.4: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.4", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.5 • TRANSPARÊNCIA E PUBLICIDADE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_5_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.5 - Publicidade e Controle Social", expanded=True):
                st.subheader("12.5 • Divulgação dos Benefícios")
                st.write(f"**Houve publicidade e transparência dos benefícios concedidos por Renúncia de Receitas em {ano_sel}?**")
                
                d125 = res_data.get("12.5", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc125 = ["Selecione...", "Sim – 00", "Não – -10 (perde 10 pontos)"]
                v_salvo_125 = d125.get("valor", "Selecione...")
                if v_salvo_125 not in opc125: v_salvo_125 = "Selecione..."
                evidencia_125_salva = d125.get("link", "")

                def cb_125():
                    val = st.session_state.get(f"rad_125_{ano_sel}_fiscal", v_salvo_125)
                    lnk = st.session_state.get(f"txt_125_{ano_sel}_fiscal", evidencia_125_salva).strip()
                    pts125_nova = -10.0 if "Não" in val else 0.0
                    
                    save_resp("12.5", val, float(pts125_nova), lnk)
                    res_data["12.5"] = {"valor": val, "pontos": float(pts125_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_125_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_125_salva or ""):
                        st.session_state[f"links_pendentes_12_5_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_5_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 12.5:", opc125, index=opc125.index(v_salvo_125), key=f"rad_125_{ano_sel}_fiscal", on_change=cb_125)
                with c2:
                    lk125 = st.text_area("Link/Evidência de Publicidade Geral (12.5):", value=evidencia_125_salva, key=f"txt_125_{ano_sel}_fiscal", on_change=cb_125, height=100)
                    if lk125: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk125 or "")]))

                pts_exibido_125 = d125.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_125 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 12.5: {pts_exibido_125:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.5", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.5.1 • CHECKLIST DE CONTEÚDO EXIBIDO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_5_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.5.1 - Escopo da Transparência", expanded=True):
                st.subheader("12.5.1 • Elementos Informativos Disponibilizados")
                st.write(f"**Assinale as informações divulgadas referente aos benefícios concedidos por Renúncia de Receitas em {ano_sel}: (Checklist)**")
                
                d1251 = res_data.get("12.5.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                try:
                    sel1251 = json.loads(d1251.get("valor", "[]").replace("'", '"'))
                    if not isinstance(sel1251, list): sel1251 = []
                except:
                    sel1251 = []
                evidencia_1251_salva = d1251.get("link", "")

                opc1251 = [
                    "Valor dos benefícios concedidos",
                    "Público beneficiado",
                    "Métodos utilizados na sua mensuração",
                    "Resultados socioeconômicos alcançados com a renúncia",
                    "Outros"
                ]

                def cb_1251(opcao_alvo=None, idx_alvo=None, is_link_change=False):
                    estado_atual_lista = list(sel1251)
                    lnk = st.session_state.get(f"txt_lnk_1251_{ano_sel}_fiscal", evidencia_1251_salva).strip()
                    
                    if not is_link_change and opcao_alvo is not None and idx_alvo is not None:
                        caixa_marcada = st.session_state.get(f"chk_1251_{idx_alvo}_{ano_sel}_fiscal", False)
                        if caixa_marcada and opcao_alvo not in estado_atual_lista:
                            estado_atual_lista.append(opcao_alvo)
                        elif not caixa_marcada and opcao_alvo in estado_atual_lista:
                            estado_atual_lista.remove(opcao_alvo)
                        
                    v_json = json.dumps(estado_atual_lista)
                    save_resp("12.5.1", v_json, 0.0, lnk)
                    res_data["12.5.1"] = {"valor": v_json, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_1251_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_1251_salva or ""):
                        st.session_state[f"links_pendentes_12_5_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_12_5_1_{ano_sel}"] = True

                c7, c8 = st.columns([1, 1])
                with c7:
                    for idx, opcao in enumerate(opc1251):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel1251), 
                            key=f"chk_1251_{idx}_{ano_sel}_fiscal", 
                            on_change=cb_1251, 
                            kwargs={"opcao_alvo": opcao, "idx_alvo": idx, "is_link_change": False}
                        )
                with c8:
                    lk1251 = st.text_area("Link/Evidência dos Itens Declarados (12.5.1):", value=evidencia_1251_salva, key=f"txt_lnk_1251_{ano_sel}_fiscal", on_change=cb_1251, kwargs={"is_link_change": True}, height=120)
                    if lk1251: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1251 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 12.5.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.5.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 12.5.2 • LINK DE DIVULGAÇÃO (TRAVA XYZ)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q12_5_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 12.5.2 - Link da Transparência", expanded=True):
                st.subheader("12.5.2 • Localizador na Rede Mundial")
                st.write(f"**Informe a página eletrônica (link na internet) de divulgação das informações referente aos benefícios concedidos por Renúncia de Receitas em {ano_sel}:**")
                st.caption("⚠️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ** (Aplica penalidade de -03 pontos).*")
                
                d1252 = res_data.get("12.5.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_1252 = d1252.get("valor", "")
                evidencia_1252_salva = d1252.get("link", "")

                def cb_1252():
                    val = st.session_state.get(f"txt_1252_{ano_sel}_fiscal", v_salvo_1252).strip()
                    lnk = st.session_state.get(f"txt_lnk_1252_{ano_sel}_fiscal", evidencia_1252_salva).strip()
                    pts1252_nova = -3.0 if val.upper() == "XYZ" else 0.0
                    
                    save_resp("12.5.2", val, float(pts1252_nova), lnk)
                    res_data["12.5.2"] = {"valor": val, "pontos": float(pts1252_nova), "link": lnk}
                    
                    lk_combinados = re.findall(r'(https?://[^\s]+)', f"{val} {lnk}")
                    lk_antigos = re.findall(r'(https?://[^\s]+)', f"{v_salvo_1252} {evidencia_1252_salva}")
                    if lk_combinados and lk_combinados != lk_antigos:
                        st.session_state[f"links_pendentes_12_5_2_{ano_sel}"] = lk_combinados
                        st.session_state[f"gatilho_modal_12_5_2_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    v1252_input = st.text_input("Página eletrônica (ou XYZ) - 12.5.2:", value=v_salvo_1252, key=f"txt_1252_{ano_sel}_fiscal", on_change=cb_1252)
                    if v1252_input and not v1252_input.upper() == "XYZ": st.markdown("**🔗 URL Informada:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', v1252_input or "")]))
                with c2:
                    lk1252 = st.text_area("Evidência Adicional (12.5.2):", value=evidencia_1252_salva, key=f"txt_lnk_1252_{ano_sel}_fiscal", on_change=cb_1252, height=100)
                    if lk1252: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk1252 or "")]))

                pts_exibido_1252 = d1252.get("pontos", 0.0)
                st.markdown(f"<span style='color:{'#dc3545' if pts_exibido_1252 < 0 else '#28a745'}; font-weight:bold;'>📊 Impacto 12.5.2: {pts_exibido_1252:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("12.5.2", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA)
        # =============================================================================
        for q_ref in ["12.0", "12.1", "12.1.1", "12.1.2", "12.2", "12.3", "12.3.1", "12.4", "12.5", "12.5.1", "12.5.2"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

        # -------------------------------------------------------------------------
        # SEÇÃO 6: DÍVIDA ATIVA
        # -------------------------------------------------------------------------
        st.markdown("### 6. Dívida Ativa")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 13.0 • REGULAMENTAÇÃO SOBRE DÍVIDA ATIVA
        # =============================================================================
        with st.container(key=f"bloco_isolado_q13_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 13.0 - Regulamentação da Dívida Ativa ({ano_sel})", expanded=True):
                st.subheader("13.0 • Dívida Ativa")
                st.write("**O município possui regulamentação sobre dívida ativa?**")
                
                d130 = res_data.get("13.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc130 = ["Selecione...", "Sim – 01", "Não – 00"]
                
                valor_limpo_130 = d130.get("valor", "Selecione...")
                if valor_limpo_130 not in opc130: valor_limpo_130 = "Selecione..."
                evidencia_130_salva = d130.get("link", "")

                def cb_130():
                    val = st.session_state.get(f"rad_130_{ano_sel}_fiscal", valor_limpo_130)
                    lnk = st.session_state.get(f"txt_130_{ano_sel}_fiscal", evidencia_130_salva).strip()
                    pts130_nova = 1.0 if "Sim" in val else 0.0
                    
                    save_resp("13.0", val, float(pts130_nova), lnk)
                    res_data["13.0"] = {"valor": val, "pontos": float(pts130_nova), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_130_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_130_salva or ""):
                        st.session_state[f"links_pendentes_13_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_13_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 13.0:", opc130, index=opc130.index(valor_limpo_130), key=f"rad_130_{ano_sel}_fiscal", on_change=cb_130)
                with c2:
                    lk130 = st.text_area(f"Link/Evidência Geral ({ano_sel}):", value=evidencia_130_salva, key=f"txt_130_{ano_sel}_fiscal", on_change=cb_130, height=100)
                    if lk130: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk130 or "")]))

                pts_exibido_130 = d130.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 13.0: {pts_exibido_130:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("13.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 13.1 • INSTRUMENTO NORMATIVO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q13_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 13.1 - Identificação do Normativo", expanded=True):
                st.subheader("13.1 • Instrumento Normativo da Dívida Ativa")
                st.write("**Instrumento normativo de regulamentação da dívida ativa, Número e Data da publicação:**")
                st.caption("ℹ️ *Caso não esteja disponível na internet, recomendamos anexar o documento no Sistema de Questionários.*")
                
                d131 = res_data.get("13.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_131 = d131.get("valor", "")
                evidencia_131_salva = d131.get("link", "")

                def cb_131():
                    val = st.session_state.get(f"txt_131_{ano_sel}_fiscal", v_salvo_131).strip()
                    lnk = st.session_state.get(f"txt_lnk_131_{ano_sel}_fiscal", evidencia_131_salva).strip()
                    
                    save_resp("13.1", val, 0.0, lnk)
                    res_data["13.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_131_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_131_salva or ""):
                        st.session_state[f"links_pendentes_13_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_13_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input("Instrumento normativo (Nº e Data):", value=v_salvo_131, key=f"txt_131_{ano_sel}_fiscal", on_change=cb_131)
                with c2:
                    lk131 = st.text_area("Link/Evidência da Publicação (13.1):", value=evidencia_131_salva, key=f"txt_lnk_131_{ano_sel}_fiscal", on_change=cb_131, height=100)
                    if lk131: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk131 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 13.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("13.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 13.2 • URL DO NORMATIVO (TRAVA XYZ)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q13_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 13.2 - URL de Divulgação", expanded=True):
                st.subheader("13.2 • Endereço Eletrônico da Norma")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da regulamentação da dívida ativa:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                d132 = res_data.get("13.2", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_132 = d132.get("valor", "")
                evidencia_132_salva = d132.get("link", "")

                def cb_132():
                    val = st.session_state.get(f"txt_132_{ano_sel}_fiscal", v_salvo_132).strip()
                    lnk = st.session_state.get(f"txt_lnk_132_{ano_sel}_fiscal", evidencia_132_salva).strip()
                    pts132_nova = 0.0
                    
                    save_resp("13.2", val, float(pts132_nova), lnk)
                    res_data["13.2"] = {"valor": val, "pontos": float(pts132_nova), "link": lnk}
                    
                    lk_combinados = re.findall(r'(https?://[^\s]+)', f"{val} {lnk}")
                    lk_antigos = re.findall(r'(https?://[^\s]+)', f"{v_salvo_132} {evidencia_132_salva}")
                    if lk_combinados and lk_combinados != lk_antigos:
                        st.session_state[f"links_pendentes_13_2_{ano_sel}"] = lk_combinados
                        st.session_state[f"gatilho_modal_13_2_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    v132_input = st.text_input("Página eletrônica (ou XYZ) - 13.2:", value=v_salvo_132, key=f"txt_132_{ano_sel}_fiscal", on_change=cb_132)
                    if v132_input and not v132_input.upper() == "XYZ": st.markdown("**🔗 URL Informada:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', v132_input or "")]))
                with c2:
                    lk132 = st.text_area("Evidência Adicional (13.2):", value=evidencia_132_salva, key=f"txt_lnk_132_{ano_sel}_fiscal", on_change=cb_132, height=100)
                    if lk132: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk132 or "")]))

                pts_exibido_132 = d132.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 13.2: {pts_exibido_132:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("13.2", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 13.3 • CHECKLIST DE CRITÉRIOS DA LEGISLAÇÃO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q13_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 13.3 - Critérios Estabelecidos (Checklist)", expanded=True):
                st.subheader("13.3 • Critérios da Legislação sobre Dívida Ativa")
                st.write("**Assinale os critérios estabelecidos na legislação sobre dívida ativa:**")
                
                d133 = res_data.get("13.3", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_133_salva = d133.get("link", "")
                
                try:
                    val_banco133 = d133["valor"].replace("'", '"')
                    sel133 = json.loads(val_banco133)
                    if not isinstance(sel133, list): sel133 = []
                except:
                    sel133 = []

                opcoes_133 = [
                    "Cobrança administrativa da dívida ativa – 1,5",
                    "Parcelamento da dívida ativa – 1,5",
                    "Restrição e controle da inadimplência nos parcelamentos da dívida ativa – 1,5",
                    "Início do trâmite da execução judicial da dívida ativa – 1,5",
                    "Anistia – 1,5",
                    "Remissão – 1,5"
                ]

                def cb_133():
                    res133 = []
                    for idx, opcao in enumerate(opcoes_133):
                        if st.session_state.get(f"chk_133_{idx}_{ano_sel}_fiscal", False):
                            res133.append(opcao)
                    
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
                    
                    lnk = st.session_state.get(f"txt_lnk_133_{ano_sel}_fiscal", evidencia_133_salva).strip()
                    
                    save_resp("13.3", json.dumps(res133), float(pts133), lnk)
                    res_data["13.3"] = {"valor": json.dumps(res133), "pontos": float(pts133), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_133_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_133_salva or ""):
                        st.session_state[f"links_pendentes_13_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_13_3_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                for idx, opcao in enumerate(opcoes_133):
                    target_col = c3 if idx % 2 == 0 else c4
                    with target_col:
                        pode_marcar = opcao in sel133
                        st.checkbox(opcao, value=pode_marcar, key=f"chk_133_{idx}_{ano_sel}_fiscal", on_change=cb_133)
                
                st.markdown("---")
                lk133 = st.text_area("Link/Evidência Adicional do Checklist (13.3):", value=evidencia_133_salva, key=f"txt_lnk_133_{ano_sel}_fiscal", on_change=cb_133, height=100)
                if lk133: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk133 or "")]))

                pts_exibido_133 = d133.get("pontos", 0.0)
                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 13.3: {pts_exibido_133:.1f} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("13.3", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 13
        # =============================================================================
        for q_ref in ["13.0", "13.1", "13.2", "13.3"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

# =============================================================================
        # BLOCO ISOLADO: QUESITO 14.0 • DÍVIDA ATIVA JUDICIAL
        # =============================================================================
        with st.container(key=f"bloco_isolado_q14_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 14.0 - Dívida Ativa Judicial ({ano_sel})", expanded=True):
                st.subheader("14.0 • Cobrança Judicial")
                st.write(f"**O開 Município possui dívida ativa executada de forma judicial em {ano_sel}?**")
                
                d140 = res_data.get("14.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc140 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_140 = d140.get("valor", "Selecione...")
                if valor_limpo_140 not in opc140: valor_limpo_140 = "Selecione..."
                evidencia_140_salva = d140.get("link", "")

                def cb_140():
                    val = st.session_state.get(f"rad_140_{ano_sel}_fiscal", valor_limpo_140)
                    lnk = st.session_state.get(f"txt_140_{ano_sel}_fiscal", evidencia_140_salva).strip()
                    
                    save_resp("14.0", val, 0.0, lnk)
                    res_data["14.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_140_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_140_salva or ""):
                        st.session_state[f"links_pendentes_14_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_14_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 14.0:", opc140, index=opc140.index(valor_limpo_140), key=f"rad_140_{ano_sel}_fiscal", on_change=cb_140)
                with c2:
                    lk140 = st.text_area(f"Link/Evidência Geral de Execuções ({ano_sel}):", value=evidencia_140_salva, key=f"txt_140_{ano_sel}_fiscal", on_change=cb_140, height=100)
                    if lk140: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk140 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 14.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("14.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 14.1 • VALOR TOTAL EXECUTADO JUDICIALMENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q14_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 14.1 - Valor Judicial Total", expanded=True):
                st.subheader("14.1 • Mensuração da Dívida Executada")
                st.write(f"**Informe o valor total da dívida ativa executada de forma judicial no exercício de {ano_sel}:**")
                
                d141 = res_data.get("14.1", {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}) or {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}
                v_salvo_141 = d141.get("valor", "R$ 0,00")
                if not v_salvo_141.startswith("R$"): v_salvo_141 = f"R$ {v_salvo_141}"
                evidencia_141_salva = d141.get("link", "")

                def cb_141():
                    raw_input = st.session_state.get(f"txt_141_{ano_sel}_fiscal", v_salvo_141).strip()
                    lnk = st.session_state.get(f"txt_lnk_141_{ano_sel}_fiscal", evidencia_141_salva).strip()
                    
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
                        v141_salvar = v_salvo_141  # Fallback caso digitem texto inválido
                    
                    save_resp("14.1", v141_salvar, 0.0, lnk)
                    res_data["14.1"] = {"valor": v141_salvar, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_141_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_141_salva or ""):
                        st.session_state[f"links_pendentes_14_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_14_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Informe o Valor Judicial Total (R$):", 
                        value=v_salvo_141, 
                        key=f"txt_141_{ano_sel}_fiscal", 
                        on_change=cb_141,
                        placeholder="Ex: 150.000,00"
                    )
                with c2:
                    lk141 = st.text_area("Evidência Adicional (14.1):", value=evidencia_141_salva, key=f"txt_lnk_141_{ano_sel}_fiscal", on_change=cb_141, height=100)
                    if lk141: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk141 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 14.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("14.1", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 14
        # =============================================================================
        for q_ref in ["14.0", "14.1"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

# =============================================================================
        # BLOCO ISOLADO: QUESITO 15.0 • COBRANÇA EXTRAJUDICIAL DA DÍVIDA ATIVA
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 15.0 - Cobrança Extrajudicial ({ano_sel})", expanded=True):
                st.subheader("15.0 • Execução Extrajudicial")
                st.write(f"**A prefeitura realiza cobrança de dívida ativa de forma extrajudicial em {ano_sel}?**")
                
                d150 = res_data.get("15.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc150 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_150 = d150.get("valor", "Selecione...")
                if valor_limpo_150 not in opc150: valor_limpo_150 = "Selecione..."
                evidencia_150_salva = d150.get("link", "")

                def cb_150():
                    val = st.session_state.get(f"rad_150_{ano_sel}_fiscal", valor_limpo_150)
                    lnk = st.session_state.get(f"txt_150_{ano_sel}_fiscal", evidencia_150_salva).strip()
                    
                    save_resp("15.0", val, 0.0, lnk)
                    res_data["15.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_150_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_150_salva or ""):
                        st.session_state[f"links_pendentes_15_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_0_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio("Selecione 15.0:", opc150, index=opc150.index(valor_limpo_150), key=f"rad_150_{ano_sel}_fiscal", on_change=cb_150)
                with c4:
                    lk150 = st.text_area(f"Link/Evidência de Cobranças Protestadas/Notificadas ({ano_sel}):", value=evidencia_150_salva, key=f"txt_150_{ano_sel}_fiscal", on_change=cb_150, height=100)
                    if lk150: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk150 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 15.1 • VALOR TOTAL COBRADO EXTRAJUDICIALMENTE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 15.1 - Valor Extrajudicial Total", expanded=True):
                st.subheader("15.1 • Mensuração da Cobrança Extrajudicial")
                st.write(f"**Informe o valor total da dívida ativa cobrada de forma extrajudicial no exercício de {ano_sel}:**")
                
                d151 = res_data.get("15.1", {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}) or {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}
                v_salvo_151 = d151.get("valor", "R$ 0,00")
                if not v_salvo_151.startswith("R$"): v_salvo_151 = f"R$ {v_salvo_151}"
                evidencia_151_salva = d151.get("link", "")

                def cb_151():
                    raw_input = st.session_state.get(f"txt_151_{ano_sel}_fiscal", v_salvo_151).strip()
                    lnk = st.session_state.get(f"txt_lnk_151_{ano_sel}_fiscal", evidencia_151_salva).strip()
                    
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
                        v151_salvar = v_salvo_151
                    
                    save_resp("15.1", v151_salvar, 0.0, lnk)
                    res_data["15.1"] = {"valor": v151_salvar, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_151_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_151_salva or ""):
                        st.session_state[f"links_pendentes_15_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Informe o Valor Extrajudicial Total (R$):", 
                        value=v_salvo_151, 
                        key=f"txt_151_{ano_sel}_fiscal", 
                        on_change=cb_151,
                        placeholder="Ex: 85.300,50"
                    )
                with c2:
                    lk151 = st.text_area("Evidência Adicional (15.1):", value=evidencia_151_salva, key=f"txt_lnk_151_{ano_sel}_fiscal", on_change=cb_151, height=100)
                    if lk151: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk151 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 15.2 • MODALIDADES DE COBRANÇA EXTRAJUDICIAL
        # =============================================================================
        with st.container(key=f"bloco_isolado_q15_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 15.2 - Modalidades Adotadas", expanded=True):
                st.subheader("15.2 • Modalidades de Cobrança Extrajudicial")
                st.write("**Assinale as modalidades de cobrança extrajudicial da dívida ativa adotadas pelo município:**")
                
                d152 = res_data.get("15.2", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_152_salva = d152.get("link", "")
                
                try:
                    val_banco152 = d152.get("valor", "[]").replace("'", '"')
                    sel152 = json.loads(val_banco152)
                    if not isinstance(sel152, list): sel152 = []
                except:
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

                def cb_152():
                    res152_temp = []
                    for idx_chk, opcao_chk in enumerate(opcoes_152):
                        if st.session_state.get(f"chk_152_{idx_chk}_{ano_sel}_fiscal", False):
                            res152_temp.append(opcao_chk)
                    
                    valor_json = json.dumps(res152_temp)
                    lnk = st.session_state.get(f"txt_152_{ano_sel}_fiscal", evidencia_152_salva).strip()
                    
                    save_resp("15.2", valor_json, 0.0, lnk)
                    res_data["15.2"] = {"valor": valor_json, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_152_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_152_salva or ""):
                        st.session_state[f"links_pendentes_15_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_15_2_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    for idx, opcao in enumerate(opcoes_152):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel152), 
                            key=f"chk_152_{idx}_{ano_sel}_fiscal", 
                            on_change=cb_152
                        )
                with c2:
                    lk152 = st.text_area("Link/Evidência de Legislação/Atos de Cobrança (15.2):", value=evidencia_152_salva, key=f"txt_152_{ano_sel}_fiscal", on_change=cb_152, height=150)
                    if lk152: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk152 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 15.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("15.2", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 15
        # =============================================================================
        for q_ref in ["15.0", "15.1", "15.2"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False
       
    # =============================================================================
        # BLOCO ISOLADO: QUESITO 16.0 • DÍVIDAS PRESCRITAS
        # =============================================================================
        with st.container(key=f"bloco_isolado_q16_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 16.0 - Ocorrência de Prescrições ({ano_sel})", expanded=True):
                st.subheader("16.0 • Dívidas Prescritas")
                st.write(f"**No exercício de {ano_sel} houve dívidas prescritas?**")
                st.caption("ℹ️ *Considerar na prescrição ordinária apenas os valores passíveis de cobrança via judicial, conforme regulamento específico local.*")
                
                d160 = res_data.get("16.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc160 = [
                    "Selecione...",
                    "Sim, houve prescrição ordinária – -10 (perde 10 pontos)",
                    "Sim, houve prescrição intercorrente – 00",
                    f"Não houve prescrição de dívidas em {ano_sel} – 00"
                ]
                
                valor_limpo_160 = d160.get("valor", "Selecione...")
                if valor_limpo_160 not in opc160: valor_limpo_160 = "Selecione..."
                evidencia_160_salva = d160.get("link", "")

                def cb_160():
                    val = st.session_state.get(f"rad_160_{ano_sel}_fiscal", valor_limpo_160)
                    lnk = st.session_state.get(f"txt_160_{ano_sel}_fiscal", evidencia_160_salva).strip()
                    
                    pts = -10.0 if "ordinária" in val else 0.0
                    save_resp("16.0", val, pts, lnk)
                    res_data["16.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_160_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_160_salva or ""):
                        st.session_state[f"links_pendentes_16_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_16_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 16.0:", opc160, index=opc160.index(valor_limpo_160), key=f"rad_160_{ano_sel}_fiscal", on_change=cb_160)
                with c2:
                    lk160 = st.text_area(f"Link/Evidência Geral de Prescrições/Decretos ({ano_sel}):", value=evidencia_160_salva, key=f"txt_160_{ano_sel}_fiscal", on_change=cb_160, height=100)
                    if lk160: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk160 or "")]))

                cor_p160 = "#dc3545" if d160.get("pontos", 0.0) < 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p160}; font-weight:bold;'>📊 Impacto 16.0: {d160.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("16.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 16.1 • VALOR JUDICIAL PRESCRITO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q16_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 16.1 - Valor Prescrito Judicial", expanded=True):
                st.subheader("16.1 • Mensuração do Estoque Judicial Prescrito")
                st.write(f"**Informe o valor da dívida ativa prescrita na execução judicial em {ano_sel}:**")
                
                d161 = res_data.get("16.1", {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}) or {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}
                v_salvo_161 = d161.get("valor", "R$ 0,00")
                if not v_salvo_161.startswith("R$"): v_salvo_161 = f"R$ {v_salvo_161}"
                evidencia_161_salva = d161.get("link", "")

                def cb_161():
                    raw_input = st.session_state.get(f"txt_161_{ano_sel}_fiscal", v_salvo_161).strip()
                    lnk = st.session_state.get(f"txt_lnk_161_{ano_sel}_fiscal", evidencia_161_salva).strip()
                    
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
                        v161_salvar = v_salvo_161
                    
                    save_resp("16.1", v161_salvar, 0.0, lnk)
                    res_data["16.1"] = {"valor": v161_salvar, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_161_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_161_salva or ""):
                        st.session_state[f"links_pendentes_16_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_16_1_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Informe o Valor Prescrito Judicial (R$):", 
                        value=v_salvo_151, 
                        key=f"txt_161_{ano_sel}_fiscal", 
                        on_change=cb_161,
                        placeholder="Ex: 50.000,00"
                    )
                with c2:
                    lk161 = st.text_area("Evidência Adicional (16.1):", value=evidencia_161_salva, key=f"txt_lnk_161_{ano_sel}_fiscal", on_change=cb_161, height=100)
                    if lk161: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk161 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 16.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("16.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 16.2 • VALOR EXTRAJUDICIAL PRESCRITO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q16_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 16.2 - Valor Prescrito Extrajudicial", expanded=True):
                st.subheader("16.2 • Mensuração do Estoque Extrajudicial Prescrito")
                st.write(f"**Informe o valor da dívida ativa cobrada de forma extrajudicial prescrita no exercício de {ano_sel}:**")
                
                d162 = res_data.get("16.2", {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}) or {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}
                v_salvo_162 = d162.get("valor", "R$ 0,00")
                if not v_salvo_162.startswith("R$"): v_salvo_162 = f"R$ {v_salvo_162}"
                evidencia_162_salva = d162.get("link", "")

                def cb_162():
                    raw_input = st.session_state.get(f"txt_162_{ano_sel}_fiscal", v_salvo_162).strip()
                    lnk = st.session_state.get(f"txt_lnk_162_{ano_sel}_fiscal", evidencia_162_salva).strip()
                    
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
                        v162_salvar = v_salvo_162
                    
                    save_resp("16.2", v162_salvar, 0.0, lnk)
                    res_data["16.2"] = {"valor": v162_salvar, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_162_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_162_salva or ""):
                        st.session_state[f"links_pendentes_16_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_16_2_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.text_input(
                        "Informe o Valor Prescrito Extrajudicial (R$):", 
                        value=v_salvo_162, 
                        key=f"txt_162_{ano_sel}_fiscal", 
                        on_change=cb_162,
                        placeholder="Ex: 25.400,00"
                    )
                with c2:
                    lk162 = st.text_area("Evidência Adicional (16.2):", value=evidencia_162_salva, key=f"txt_lnk_162_{ano_sel}_fiscal", on_change=cb_162, height=100)
                    if lk162: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk162 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 16.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("16.2", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 16.3 • PROVISÃO PARA PERDAS (PCASP)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q16_3_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 16.3 - Reconhecimento Contábil de Provisão", expanded=True):
                st.subheader("16.3 • Ajuste de Perdas Estimadas em Dívida Ativa")
                st.write(f"**O montante da dívida ativa prescrita cobrada de forma judicial e extrajudicial estava registrado na conta de Provisão para Perdas de Dívida Ativa?**")
                
                d163 = res_data.get("16.3", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc163 = ["Selecione...", "Sim – 00", "Não – -05 (perde 05 pontos)"]
                
                valor_limpo_163 = d163.get("valor", "Selecione...")
                if valor_limpo_163 not in opc163: valor_limpo_163 = "Selecione..."
                evidencia_163_salva = d163.get("link", "")

                def cb_163():
                    val = st.session_state.get(f"rad_163_{ano_sel}_fiscal", valor_limpo_163)
                    lnk = st.session_state.get(f"txt_163_{ano_sel}_fiscal", evidencia_163_salva).strip()
                    
                    pts = -5.0 if "Não" in val else 0.0
                    save_resp("16.3", val, pts, lnk)
                    res_data["16.3"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_163_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_163_salva or ""):
                        st.session_state[f"links_pendentes_16_3_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_16_3_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio("Selecione 16.3:", opc163, index=opc163.index(valor_limpo_163), key=f"rad_163_{ano_sel}_fiscal", on_change=cb_163)
                with c4:
                    lk163 = st.text_area("Link/Evidência do Balanço Patrimonial / Razão Contábil (16.3):", value=evidencia_163_salva, key=f"txt_163_{ano_sel}_fiscal", on_change=cb_163, height=100)
                    if lk163: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk163 or "")]))

                cor_p163 = "#dc3545" if d163.get("pontos", 0.0) < 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p163}; font-weight:bold;'>📊 Impacto 16.3: {d163.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("16.3", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 16
        # =============================================================================
        for q_ref in ["16.0", "16.1", "16.2", "16.3"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

    # =============================================================================
        # BLOCO ISOLADO: QUESITO 17.0 • CONTROLE DE AÇÕES JUDICIAIS (POLO PASSIVO)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q17_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 17.0 - Controle de Ações Judiciais ({ano_sel})", expanded=True):
                st.subheader("17.0 • Controle do Polo Passivo")
                st.write(f"**A Prefeitura possui controle das ações judiciais em que é parte (polo passivo)?**")
                
                d170 = res_data.get("17.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc170 = [
                    "Selecione...",
                    "Sim, de todas as ações – 00",
                    "Sim, da maior parte das ações – -01 (perde 01 ponto)",
                    "Sim, da menor parte das ações – -03 (perde 03 pontos)",
                    "Não – -05 (perde 05 pontos)"
                ]
                
                valor_limpo_170 = d170.get("valor", "Selecione...")
                if valor_limpo_170 not in opc170: valor_limpo_170 = "Selecione..."
                evidencia_170_salva = d170.get("link", "")

                def cb_170():
                    val = st.session_state.get(f"rad_170_{ano_sel}_fiscal", valor_limpo_170)
                    lnk = st.session_state.get(f"txt_170_{ano_sel}_fiscal", evidencia_170_salva).strip()
                    
                    if "todas" in val: pts = 0.0
                    elif "maior" in val: pts = -1.0
                    elif "menor" in val: pts = -3.0
                    elif "Não" in val: pts = -5.0
                    else: pts = 0.0
                        
                    save_resp("17.0", val, pts, lnk)
                    res_data["17.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_170_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_170_salva or ""):
                        st.session_state[f"links_pendentes_17_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_17_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 17.0:", opc170, index=opc170.index(valor_limpo_170), key=f"rad_170_{ano_sel}_fiscal", on_change=cb_170)
                with c2:
                    lk170 = st.text_area(f"Link/Evidência do Sistema ou Relatório de Controle Legal ({ano_sel}):", value=evidencia_170_salva, key=f"txt_170_{ano_sel}_fiscal", on_change=cb_170, height=100)
                    if lk170: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk170 or "")]))

                cor_p170 = "#dc3545" if d170.get("pontos", 0.0) < 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p170}; font-weight:bold;'>📊 Impacto 17.0: {d170.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("17.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 17.1 • DESCRIÇÃO DA METODOLOGIA DE CONTROLE
        # =============================================================================
        with st.container(key=f"bloco_isolado_q17_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 17.1 - Metodologia de Controle Descritiva", expanded=True):
                st.subheader("17.1 • Metodologia do Polo Passivo")
                st.write("**Descreva de que forma é realizado o controle das ações judiciais em que é parte (polo passivo):**")
                
                d171 = res_data.get("17.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_171 = d171.get("valor", "")
                evidencia_171_salva = d171.get("link", "")

                def cb_171():
                    val = st.session_state.get(f"txt_171_desc_{ano_sel}_fiscal", v_salvo_171).strip()
                    lnk = st.session_state.get(f"txt_lnk_171_{ano_sel}_fiscal", evidencia_171_salva).strip()
                    
                    save_resp("17.1", val, 0.0, lnk)
                    res_data["17.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_171_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_171_salva or ""):
                        st.session_state[f"links_pendentes_17_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_17_1_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.text_area(
                        "Descreva a metodologia/sistema de controle:",
                        value=v_salvo_171,
                        placeholder="Ex: O controle é realizado via sistema informatizado da Procuradoria Geral...",
                        key=f"txt_171_desc_{ano_sel}_fiscal",
                        on_change=cb_171,
                        height=120
                    )
                with c4:
                    lk171 = st.text_area("Evidência Adicional (17.1):", value=evidencia_171_salva, key=f"txt_lnk_171_{ano_sel}_fiscal", on_change=cb_171, height=120)
                    if lk171: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk171 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 17.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("17.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 17.2 • VALOR ATUALIZADO DO POLO PASSIVO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q17_2_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 17.2 - Valor Consolidado do Polo Passivo", expanded=True):
                st.subheader("17.2 • Mensuração Econômica das Ações")
                st.write(f"**Qual o valor atualizado em 31/12/{ano_sel} de todas as ações judiciais em que é parte (polo passivo)?**")
                
                d172 = res_data.get("17.2", {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}) or {"valor": "R$ 0,00", "pontos": 0.0, "link": ""}
                v_salvo_172 = d172.get("valor", "R$ 0,00")
                if not v_salvo_172.startswith("R$"): v_salvo_172 = f"R$ {v_salvo_172}"
                evidencia_172_salva = d172.get("link", "")

                def cb_172():
                    raw_input = st.session_state.get(f"txt_172_{ano_sel}_fiscal", v_salvo_172).strip()
                    lnk = st.session_state.get(f"txt_lnk_172_{ano_sel}_fiscal", evidencia_172_salva).strip()
                    
                    num_limpo = raw_input.replace("R$", "").replace(" ", "")
                    if "." in num_limpo and "," in num_limpo:
                        num_limpo = num_limpo.replace(".", "").replace(",", ".")
                    elif "," in num_limpo:
                        num_limpo = num_limpo.replace(",", ".")
                        
                    try:
                        valor_float = float(num_limpo) if num_limpo else 0.0
                        valor_br = f"{valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        v172_salvar = f"R$ {valor_br}"
                    except ValueError:
                        v172_salvar = v_salvo_172
                    
                    save_resp("17.2", v172_salvar, 0.0, lnk)
                    res_data["17.2"] = {"valor": v172_salvar, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_172_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_172_salva or ""):
                        st.session_state[f"links_pendentes_17_2_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_17_2_{ano_sel}"] = True

                c5, c6 = st.columns([1, 1])
                with c5:
                    st.text_input(
                        "Informe o Valor Total do Polo Passivo (R$):", 
                        value=v_salvo_172, 
                        key=f"txt_172_{ano_sel}_fiscal", 
                        on_change=cb_172,
                        placeholder="Ex: 1.250.000,00"
                    )
                with c6:
                    lk172 = st.text_area("Evidência Adicional (17.2):", value=evidencia_172_salva, key=f"txt_lnk_172_{ano_sel}_fiscal", on_change=cb_172, height=100)
                    if lk172: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk172 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 17.2: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("17.2", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 17
        # =============================================================================
        for q_ref in ["17.0", "17.1", "17.2"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

        # -------------------------------------------------------------------------
        # SEÇÃO 7: TRANSPARÊNCIA E PREVIDÊNCIA
        # -------------------------------------------------------------------------
        st.markdown("### 7. Transparência na Gestão Fiscal") 

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 18.0 • DISPONIBILIDADE DA TRANSPARÊNCIA FISCAL
        # =============================================================================
        with st.container(key=f"bloco_isolado_q18_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 18.0 - Divulgação da Gestão Fiscal ({ano_sel})", expanded=True):
                st.subheader("18.0 • Transparência na Gestão Fiscal")
                st.write(f"**Os dados relativos à transparência na gestão fiscal são divulgados na página eletrônica do Município em {ano_sel}?**")
                
                d180 = res_data.get("18.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc180 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_180 = d180.get("valor", "Selecione...")
                if valor_limpo_180 not in opc180: valor_limpo_180 = "Selecione..."
                evidencia_180_salva = d180.get("link", "")

                def cb_180():
                    val = st.session_state.get(f"rad_180_{ano_sel}_fiscal", valor_limpo_180)
                    lnk = st.session_state.get(f"txt_180_{ano_sel}_fiscal", evidencia_180_salva).strip()
                    
                    save_resp("18.0", val, 0.0, lnk)
                    res_data["18.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_180_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_180_salva or ""):
                        st.session_state[f"links_pendentes_18_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_18_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 18.0:", opc180, index=opc180.index(valor_limpo_180), key=f"rad_180_{ano_sel}_fiscal", on_change=cb_180)
                with c2:
                    lk180 = st.text_area(f"Link do Portal da Transparência / Página Eletrônica ({ano_sel}):", value=evidencia_180_salva, key=f"txt_180_{ano_sel}_fiscal", on_change=cb_180, height=100)
                    if lk180: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk180 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 18.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("18.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 18.1 • CHECKLIST DE DOCUMENTOS DIVULGADOS
        # =============================================================================
        with st.container(key=f"bloco_isolado_q18_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 18.1 - Checklist de Itens Divulgados", expanded=True):
                st.subheader("18.1 • Itens Publicados na Página Eletrônica")
                st.write("**Assinale os itens que são divulgados na página eletrônica do Município (Checklist):**")
                
                d181 = res_data.get("18.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_181_salva = d181.get("link", "")
                
                try:
                    val_banco181 = d181.get("valor", "[]").replace("'", '"')
                    sel181 = json.loads(val_banco181)
                    if not isinstance(sel181, list): sel181 = []
                except:
                    sel181 = []

                opcoes_181 = {
                    "PPA, LDO e LOA – 2,5": 2.5,
                    "Balanços de exercício – 2,5": 2.5,
                    "Prestação de contas do ano anterior – 2,5": 2.5,
                    "Parecer prévio do TCE – 2,5": 2.5,
                    "Relatório de Gestão Fiscal (RGF) – 2,5": 2.5,
                    "Relatório Resumido da Execução Orçamentária (RREO) – 2,5": 2.5
                }

                def cb_181():
                    res181_temp = []
                    pts_acumulados = 0.0
                    for idx_chk, (opcao_chk, pontos_chk) in enumerate(opcoes_181.items()):
                        if st.session_state.get(f"chk_181_{idx_chk}_{ano_sel}_fiscal", False):
                            res181_temp.append(opcao_chk)
                            pts_acumulados += pontos_chk
                    
                    valor_json = json.dumps(res181_temp)
                    lnk = st.session_state.get(f"txt_181_{ano_sel}_fiscal", evidencia_181_salva).strip()
                    
                    save_resp("18.1", valor_json, float(pts_acumulados), lnk)
                    res_data["18.1"] = {"valor": valor_json, "pontos": float(pts_acumulados), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_181_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_181_salva or ""):
                        st.session_state[f"links_pendentes_18_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_18_1_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    for idx, (opcao, _) in enumerate(opcoes_181.items()):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel181), 
                            key=f"chk_181_{idx}_{ano_sel}_fiscal", 
                            on_change=cb_181
                        )
                with c4:
                    lk181 = st.text_area("Link/Evidência dos Documentos Publicados (18.1):", value=evidencia_181_salva, key=f"txt_181_{ano_sel}_fiscal", on_change=cb_181, height=140)
                    if lk181: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk181 or "")]))

                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 18.1: {d181.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("18.1", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 18
        # =============================================================================
        for q_ref in ["18.0", "18.1"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 19.0 • DIVULGAÇÃO DE RECEITAS EM TEMPO REAL
        # =============================================================================
        with st.container(key=f"bloco_isolado_q19_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 19.0 - Receitas em Tempo Real ({ano_sel})", expanded=True):
                st.subheader("19.0 • Divulgação de Receitas em Tempo Real")
                st.write(f"**Houve divulgação das receitas arrecadadas em tempo real em {ano_sel}?**")
                st.caption("ℹ️ *Tempo real é considerado até o 1º dia útil que sucede o do registro contábil.*")
                
                d190 = res_data.get("19.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc190 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                valor_limpo_190 = d190.get("valor", "Selecione...")
                if valor_limpo_190 not in opc190: valor_limpo_190 = "Selecione..."
                evidencia_190_salva = d190.get("link", "")

                def cb_190():
                    val = st.session_state.get(f"rad_190_{ano_sel}_fiscal", valor_limpo_190)
                    lnk = st.session_state.get(f"txt_190_{ano_sel}_fiscal", evidencia_190_salva).strip()
                    
                    pts = 3.0 if "Sim" in val else 0.0
                    save_resp("19.0", val, pts, lnk)
                    res_data["19.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_190_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_190_salva or ""):
                        st.session_state[f"links_pendentes_19_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_19_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 19.0:", opc190, index=opc190.index(valor_limpo_190), key=f"rad_190_{ano_sel}_fiscal", on_change=cb_190)
                with c2:
                    lk190 = st.text_area(f"Link do Portal da Transparência / Tempo Real ({ano_sel}):", value=evidencia_190_salva, key=f"txt_190_{ano_sel}_fiscal", on_change=cb_190, height=100)
                    if lk190: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk190 or "")]))

                cor_p190 = "#28a745" if d190.get("pontos", 0.0) > 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p190}; font-weight:bold;'>📊 Impacto 19.0: {d190.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("19.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 19.1 • CHECKLIST DE ITENS DA RECEITA
        # =============================================================================
        with st.container(key=f"bloco_isolado_q19_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 19.1 - Checklist de Itens da Receita", expanded=True):
                st.subheader("19.1 • Detalhamento das Receitas em Tempo Real")
                st.write("**Assinale os itens da receita divulgados em tempo real (Checklist):**")
                
                d191 = res_data.get("19.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_191_salva = d191.get("link", "")
                
                try:
                    val_banco191 = d191.get("valor", "[]").replace("'", '"')
                    sel191 = json.loads(val_banco191)
                    if not isinstance(sel191, list): sel191 = []
                except:
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

                def cb_191():
                    res191_temp = []
                    pts_acumulados = 0.0
                    for idx_chk, (opcao_chk, pontos_chk) in enumerate(opcoes_191.items()):
                        if st.session_state.get(f"chk_191_{idx_chk}_{ano_sel}_fiscal", False):
                            res191_temp.append(opcao_chk)
                            pts_acumulados += pontos_chk
                    
                    valor_json = json.dumps(res191_temp)
                    lnk = st.session_state.get(f"txt_191_{ano_sel}_fiscal", evidencia_191_salva).strip()
                    
                    save_resp("19.1", valor_json, float(pts_acumulados), lnk)
                    res_data["19.1"] = {"valor": valor_json, "pontos": float(pts_acumulados), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_191_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_191_salva or ""):
                        st.session_state[f"links_pendentes_19_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_19_1_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    for idx, (opcao, _) in enumerate(opcoes_191.items()):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel191), 
                            key=f"chk_191_{idx}_{ano_sel}_fiscal", 
                            on_change=cb_191
                        )
                with c4:
                    lk191 = st.text_area("Link/Evidência dos Itens Demonstrados (19.1):", value=evidencia_191_salva, key=f"txt_191_{ano_sel}_fiscal", on_change=cb_191, height=220)
                    if lk191: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk191 or "")]))

                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 19.1: {d191.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("19.1", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 19
        # =============================================================================
        for q_ref in ["19.0", "19.1"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

   # =============================================================================
        # BLOCO ISOLADO: QUESITO 20.0 • DIVULGAÇÃO DE DESPESAS EM TEMPO REAL
        # =============================================================================
        with st.container(key=f"bloco_isolado_q20_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 20.0 - Despesas em Tempo Real ({ano_sel})", expanded=True):
                st.subheader("20.0 • Divulgação de Despesas em Tempo Real")
                st.write(f"**Houve divulgação das despesas executadas em tempo real em {ano_sel}?**")
                st.caption("ℹ️ *Tempo real é considerado até o 1º dia útil que sucede o do registro contábil.*")
                
                d200 = res_data.get("20.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc200 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                valor_limpo_200 = d200.get("valor", "Selecione...")
                if valor_limpo_200 not in opc200: valor_limpo_200 = "Selecione..."
                evidencia_200_salva = d200.get("link", "")

                def cb_200():
                    val = st.session_state.get(f"rad_200_{ano_sel}_fiscal", valor_limpo_200)
                    lnk = st.session_state.get(f"txt_200_{ano_sel}_fiscal", evidencia_200_salva).strip()
                    
                    pts = 3.0 if "Sim" in val else 0.0
                    save_resp("20.0", val, pts, lnk)
                    res_data["20.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_200_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_200_salva or ""):
                        st.session_state[f"links_pendentes_20_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_20_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 20.0:", opc200, index=opc200.index(valor_limpo_200), key=f"rad_200_{ano_sel}_fiscal", on_change=cb_200)
                with c2:
                    lk200 = st.text_area(f"Link do Portal da Transparência / Despesas Tempo Real ({ano_sel}):", value=evidencia_200_salva, key=f"txt_200_{ano_sel}_fiscal", on_change=cb_200, height=100)
                    if lk200: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk200 or "")]))

                cor_p200 = "#28a745" if d200.get("pontos", 0.0) > 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p200}; font-weight:bold;'>📊 Impacto 20.0: {d200.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("20.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 20.1 • CHECKLIST DE ITENS DA DESPESA
        # =============================================================================
        with st.container(key=f"bloco_isolado_q20_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 20.1 - Checklist de Itens da Despesa", expanded=True):
                st.subheader("20.1 • Detalhamento das Despesas em Tempo Real")
                st.write("**Assinale os itens das despesas divulgados em tempo real (Checklist):**")
                
                d201 = res_data.get("20.1", {"valor": "[]", "pontos": 0.0, "link": ""}) or {"valor": "[]", "pontos": 0.0, "link": ""}
                evidencia_201_salva = d201.get("link", "")
                
                try:
                    val_banco201 = d201.get("valor", "[]").replace("'", '"')
                    sel201 = json.loads(val_banco201)
                    if not isinstance(sel201, list): sel201 = []
                except:
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

                def cb_201():
                    res201_temp = []
                    pts_acumulados = 0.0
                    for idx_chk, (opcao_chk, pontos_chk) in enumerate(opcoes_201.items()):
                        if st.session_state.get(f"chk_201_{idx_chk}_{ano_sel}_fiscal", False):
                            res201_temp.append(opcao_chk)
                            pts_acumulados += pontos_chk
                    
                    valor_json = json.dumps(res201_temp)
                    lnk = st.session_state.get(f"txt_201_{ano_sel}_fiscal", evidencia_201_salva).strip()
                    
                    save_resp("20.1", valor_json, float(pts_acumulados), lnk)
                    res_data["20.1"] = {"valor": valor_json, "pontos": float(pts_acumulados), "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_201_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_201_salva or ""):
                        st.session_state[f"links_pendentes_20_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_20_1_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    for idx, (opcao, _) in enumerate(opcoes_201.items()):
                        st.checkbox(
                            opcao, 
                            value=(opcao in sel201), 
                            key=f"chk_201_{idx}_{ano_sel}_fiscal", 
                            on_change=cb_201
                        )
                with c4:
                    lk201 = st.text_area("Link/Evidência das Despesas (20.1):", value=evidencia_201_salva, key=f"txt_201_{ano_sel}_fiscal", on_change=cb_201, height=320)
                    if lk201: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk201 or "")]))

                st.markdown(f"<span style='color:#28a745; font-weight:bold;'>📊 Impacto 20.1: {d201.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("20.1", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 20
        # =============================================================================
        for q_ref in ["20.0", "20.1"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 21.0 • DIVULGAÇÃO DE REMUNERAÇÃO INDIVIDUALIZADA
        # =============================================================================
        with st.container(key=f"bloco_isolado_q21_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 21.0 - Remuneração Individualizada ({ano_sel})", expanded=True):
                st.subheader("21.0 • Transparência de Remunerações")
                st.write(f"**Houve divulgação de remuneração individualizada por nome do agente público, contendo dados sobre os vencimentos, descontos, indenizações e valor líquido em {ano_sel}?**")
                
                d210 = res_data.get("21.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc210 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                valor_limpo_210 = d210.get("valor", "Selecione...")
                if valor_limpo_210 not in opc210: valor_limpo_210 = "Selecione..."
                evidencia_210_salva = d210.get("link", "")

                def cb_210():
                    val = st.session_state.get(f"rad_210_{ano_sel}_fiscal", valor_limpo_210)
                    lnk = st.session_state.get(f"txt_210_{ano_sel}_fiscal", evidencia_210_salva).strip()
                    
                    pts = 3.0 if "Sim" in val else 0.0
                    save_resp("21.0", val, pts, lnk)
                    res_data["21.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_210_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_210_salva or ""):
                        st.session_state[f"links_pendentes_21_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_21_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 21.0:", opc210, index=opc210.index(valor_limpo_210), key=f"rad_210_{ano_sel}_fiscal", on_change=cb_210)
                with c2:
                    lk210 = st.text_area(f"Link Geral do Portal de Transparência / Pessoal ({ano_sel}):", value=evidencia_210_salva, key=f"txt_210_{ano_sel}_fiscal", on_change=cb_210, height=100)
                    if lk210: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk210 or "")]))

                cor_p210 = "#28a745" if d210.get("pontos", 0.0) > 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p210}; font-weight:bold;'>📊 Impacto 21.0: {d210.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("21.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 21.1 • ENDEREÇO ELETRÔNICO DA FOLHA DE PAGAMENTO
        # =============================================================================
        with st.container(key=f"bloco_isolado_q21_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 21.1 - Endereço Eletrônico de Divulgação", expanded=True):
                st.subheader("21.1 • URL Direta da Folha")
                st.write("**Informe a página eletrônica (link na internet) de divulgação da remuneração individualizada por nome do agente público:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                d211 = res_data.get("21.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_211 = d211.get("valor", "")
                evidencia_211_salva = d211.get("link", "")

                def cb_211():
                    val = st.session_state.get(f"txt_211_val_{ano_sel}_fiscal", v_salvo_211).strip()
                    lnk = st.session_state.get(f"txt_lnk_211_{ano_sel}_fiscal", evidencia_211_salva).strip()
                    
                    save_resp("21.1", val, 0.0, lnk)
                    res_data["21.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    # Varredura do input principal (v211) que atua como link/valor
                    lk_at_val = re.findall(r'(https?://[^\s]+)', val or "")
                    if val != v_salvo_211 and lk_at_val and lk_at_val != re.findall(r'(https?://[^\s]+)', v_salvo_211 or ""):
                        st.session_state[f"links_pendentes_21_1_{ano_sel}"] = lk_at_val
                        st.session_state[f"gatilho_modal_21_1_{ano_sel}"] = True
                        return

                    # Varredura do campo de evidência adicional secundária
                    lk_at_lnk = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_211_salva and lk_at_lnk and lk_at_lnk != re.findall(r'(https?://[^\s]+)', evidencia_211_salva or ""):
                        st.session_state[f"links_pendentes_21_1_{ano_sel}"] = lk_at_lnk
                        st.session_state[f"gatilho_modal_21_1_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.text_input(
                        "Link de divulgação da folha de pagamento (ou XYZ):", 
                        value=v_salvo_211, 
                        key=f"txt_211_val_{ano_sel}_fiscal",
                        on_change=cb_211
                    )
                    lk_val_ativos = re.findall(r'(https?://[^\s]+)', v_salvo_211 or "")
                    if lk_val_ativos: st.markdown("**🔗 Link Informado:** " + " | ".join([f"[{u}]({u})" for u in lk_val_ativos]))
                with c4:
                    lk211 = st.text_area("Evidência Adicional (21.1):", value=evidencia_211_salva, key=f"txt_lnk_211_{ano_sel}_fiscal", on_change=cb_211, height=100)
                    if lk211: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk211 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 21.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("21.1", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 21
        # =============================================================================
        for q_ref in ["21.0", "21.1"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

    # =============================================================================
        # BLOCO ISOLADO: QUESITO 22.0 • DIVULGAÇÃO DE DIÁRIAS E PASSAGENS
        # =============================================================================
        with st.container(key=f"bloco_isolado_q22_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 22.0 - Diárias e Passagens ({ano_sel})", expanded=True):
                st.subheader("22.0 • Transparência de Diárias e Passagens")
                st.write(f"**Houve divulgação de diárias e passagens por nome de favorecido e constando data, destino, cargo e motivo de viagem em {ano_sel}?**")
                
                d220 = res_data.get("22.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc220 = ["Selecione...", "Sim – 03", "Não – 00"]
                
                valor_limpo_220 = d220.get("valor", "Selecione...")
                if valor_limpo_220 not in opc220: valor_limpo_220 = "Selecione..."
                evidencia_220_salva = d220.get("link", "")

                def cb_220():
                    val = st.session_state.get(f"rad_220_{ano_sel}_fiscal", valor_limpo_220)
                    lnk = st.session_state.get(f"txt_220_{ano_sel}_fiscal", evidencia_220_salva).strip()
                    
                    pts = 3.0 if "Sim" in val else 0.0
                    save_resp("22.0", val, pts, lnk)
                    res_data["22.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_220_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_220_salva or ""):
                        st.session_state[f"links_pendentes_22_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_22_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 22.0:", opc220, index=opc220.index(valor_limpo_220), key=f"rad_220_{ano_sel}_fiscal", on_change=cb_220)
                with c2:
                    lk220 = st.text_area(f"Link Geral do Portal de Transparência / Diárias ({ano_sel}):", value=evidencia_220_salva, key=f"txt_220_{ano_sel}_fiscal", on_change=cb_220, height=100)
                    if lk220: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk220 or "")]))

                cor_p220 = "#28a745" if d220.get("pontos", 0.0) > 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p220}; font-weight:bold;'>📊 Impacto 22.0: {d220.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("22.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 22.1 • ENDEREÇO ELETRÔNICO DE DIÁRIAS E PASSAGENS
        # =============================================================================
        with st.container(key=f"bloco_isolado_q22_1_{ano_sel}_fiscal", border=True):
            with st.expander("📌 Quesito 22.1 - Endereço Eletrônico de Divulgação", expanded=True):
                st.subheader("22.1 • URL Direta de Diárias e Passagens")
                st.write("**Informe a página eletrônica (link na internet) de divulgação de diárias e passagens:**")
                st.caption("ℹ️ *Se não estiver disponível na internet, inserir no campo o texto **XYZ***")
                
                d221 = res_data.get("22.1", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_221 = d221.get("valor", "")
                evidencia_221_salva = d221.get("link", "")

                def cb_221():
                    val = st.session_state.get(f"txt_221_val_{ano_sel}_fiscal", v_salvo_221).strip()
                    lnk = st.session_state.get(f"txt_lnk_221_{ano_sel}_fiscal", evidencia_221_salva).strip()
                    
                    save_resp("22.1", val, 0.0, lnk)
                    res_data["22.1"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    # Varredura do input principal que atua como link/valor
                    lk_at_val = re.findall(r'(https?://[^\s]+)', val or "")
                    if val != v_salvo_221 and lk_at_val and lk_at_val != re.findall(r'(https?://[^\s]+)', v_salvo_221 or ""):
                        st.session_state[f"links_pendentes_22_1_{ano_sel}"] = lk_at_val
                        st.session_state[f"gatilho_modal_22_1_{ano_sel}"] = True
                        return

                    # Varredura do campo de evidência adicional secundária
                    lk_at_lnk = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_221_salva and lk_at_lnk and lk_at_lnk != re.findall(r'(https?://[^\s]+)', evidencia_221_salva or ""):
                        st.session_state[f"links_pendentes_22_1_{ano_sel}"] = lk_at_lnk
                        st.session_state[f"gatilho_modal_22_1_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.text_input(
                        "Link de divulgação das diárias e passagens (ou XYZ):", 
                        value=v_salvo_221, 
                        key=f"txt_221_val_{ano_sel}_fiscal",
                        on_change=cb_221
                    )
                    lk_val_ativos = re.findall(r'(https?://[^\s]+)', v_salvo_221 or "")
                    if lk_val_ativos: st.markdown("**🔗 Link Informado:** " + " | ".join([f"[{u}]({u})" for u in lk_val_ativos]))
                with c4:
                    lk221 = st.text_area("Evidência Adicional (22.1):", value=evidencia_221_salva, key=f"txt_lnk_221_{ano_sel}_fiscal", on_change=cb_221, height=100)
                    if lk221: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk221 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 22.1: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("22.1", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 22
        # =============================================================================
        for q_ref in ["22.0", "22.1"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

    # =============================================================================
        # BLOCO ISOLADO: QUESITO 23.0 • REPASSES CORRENTES AO RGPS
        # =============================================================================
        with st.container(key=f"bloco_isolado_q23_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 23.0 - Repasses Correntes RGPS ({ano_sel})", expanded=True):
                st.subheader("23.0 • Repasses Correntes (RGPS)")
                st.write(f"**Os repasses para o Regime Geral de Previdência Social (RGPS) da competência de {ano_sel} foram realizados em qual prazo?**")
                
                d230 = res_data.get("23.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc230 = [
                    "Selecione...",
                    "Todos os repasses foram dentro do prazo legal – 00",
                    "A maior parte dos repasses recolhidos até 30 dias após o vencimento – -04 (perde 04 pontos)",
                    "A maior parte dos repasses recolhidos de 31 a 90 dias do vencimento – -15 (perde 15 pontos)",
                    "A maior parte dos repasses recolhidos acima de 90 dias do vencimento – -21 (perde 21 pontos)",
                    "Os repasses não foram realizados – -30 (perde 30 pontos)"
                ]
                
                valor_limpo_230 = d230.get("valor", "Selecione...")
                if valor_limpo_230 not in opc230: valor_limpo_230 = "Selecione..."
                evidencia_230_salva = d230.get("link", "")

                def cb_230():
                    val = st.session_state.get(f"rad_230_{ano_sel}_fiscal", valor_limpo_230)
                    lnk = st.session_state.get(f"txt_230_{ano_sel}_fiscal", evidencia_230_salva).strip()
                    
                    if "dentro do prazo" in val: pts = 0.0
                    elif "até 30 dias" in val: pts = -4.0
                    elif "31 a 90 dias" in val: pts = -15.0
                    elif "acima de 90 dias" in val: pts = -21.0
                    elif "não foram realizados" in val: pts = -30.0
                    else: pts = 0.0
                        
                    save_resp("23.0", val, pts, lnk)
                    res_data["23.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_230_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_230_salva or ""):
                        st.session_state[f"links_pendentes_23_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_23_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 23.0:", opc230, index=opc230.index(valor_limpo_230), key=f"rad_230_{ano_sel}_fiscal", on_change=cb_230)
                with c2:
                    lk230 = st.text_area(f"Link/Evidência de Comprovantes de Repasse / GFIP / GPS ({ano_sel}):", value=evidencia_230_salva, key=f"txt_230_{ano_sel}_fiscal", on_change=cb_230, height=140)
                    if lk230: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk230 or "")]))

                cor_p230 = "#dc3545" if d230.get("pontos", 0.0) < 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p230}; font-weight:bold;'>📊 Impacto 23.0: {d230.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("23.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 24.0 • ADESÃO A PARCELAMENTOS DE DÉBITOS (RGPS)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q24_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 24.0 - Adesão a Parcelamento RGPS ({ano_sel})", expanded=True):
                st.subheader("24.0 • Identificação de Parcelamentos")
                st.write(f"**A Prefeitura aderiu a algum parcelamento de encargos sociais (Regime Geral de Previdência Social - RGPS)?**")
                
                d240 = res_data.get("24.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc240 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_240 = d240.get("valor", "Selecione...")
                if valor_limpo_240 not in opc240: valor_limpo_240 = "Selecione..."
                evidencia_240_salva = d240.get("link", "")

                def cb_240():
                    val = st.session_state.get(f"rad_240_{ano_sel}_fiscal", valor_limpo_240)
                    lnk = st.session_state.get(f"txt_240_{ano_sel}_fiscal", evidencia_240_salva).strip()
                    
                    save_resp("24.0", val, 0.0, lnk)
                    res_data["24.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_240_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_240_salva or ""):
                        st.session_state[f"links_pendentes_24_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_24_0_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio("Selecione 24.0:", opc240, index=opc240.index(valor_limpo_240), key=f"rad_240_{ano_sel}_fiscal", on_change=cb_240)
                with c4:
                    lk240 = st.text_area(f"Link/Evidência do Termo de Parcelamento / Extrato da RFB ({ano_sel}):", value=evidencia_240_salva, key=f"txt_240_{ano_sel}_fiscal", on_change=cb_240, height=100)
                    if lk240: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk240 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 24.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("24.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 24.1 • SITUAÇÃO DAS PARCELAS DE PARCELAMENTO (RGPS)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q24_1_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 24.1 - Adimplemento das Parcelas RGPS ({ano_sel})", expanded=True):
                st.subheader("24.1 • Regularidade das Parcelas")
                st.write(f"**As parcelas referentes ao parcelamento para o Regime Geral de Previdência Social (RGPS) com vencimento em {ano_sel} foram realizadas em qual prazo?**")
                
                d241 = res_data.get("24.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc241 = [
                    "Selecione...",
                    "Todas as parcelas foram recolhidas dentro do prazo legal – 00",
                    "A maior parte das parcelas recolhidas até 30 dias após o vencimento – -04 (perde 04 pontos)",
                    "A maior parte das parcelas recolhidas de 31 a 90 dias do vencimento – -15 (perde 15 pontos)",
                    "A maior parte das parcelas recolhidas acima de 90 dias do vencimento – -21 (perde 21 pontos)",
                    "As parcelas não foram recolhidas – -30 (perde 30 pontos)"
                ]
                
                valor_limpo_241 = d241.get("valor", "Selecione...")
                if valor_limpo_241 not in opc241: valor_limpo_241 = "Selecione..."
                evidencia_241_salva = d241.get("link", "")

                def cb_241():
                    val = st.session_state.get(f"rad_241_{ano_sel}_fiscal", valor_limpo_241)
                    lnk = st.session_state.get(f"txt_241_{ano_sel}_fiscal", evidencia_241_salva).strip()
                    
                    if "dentro do prazo" in val: pts = 0.0
                    elif "até 30 dias" in val: pts = -4.0
                    elif "31 a 90 dias" in val: pts = -15.0
                    elif "acima de 90 dias" in val: pts = -21.0
                    elif "não foram recolhidas" in val: pts = -30.0
                    else: pts = 0.0
                        
                    save_resp("24.1", val, pts, lnk)
                    res_data["24.1"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_241_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_241_salva or ""):
                        st.session_state[f"links_pendentes_24_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_24_1_{ano_sel}"] = True

                c5, c6 = st.columns([1, 1])
                with c5:
                    st.radio("Selecione 24.1:", opc241, index=opc241.index(valor_limpo_241), key=f"rad_241_{ano_sel}_fiscal", on_change=cb_241)
                with c6:
                    lk241 = st.text_area(f"Link/Evidência de Comprovantes de Pagamento do Parcelamento ({ano_sel}):", value=evidencia_241_salva, key=f"txt_241_{ano_sel}_fiscal", on_change=cb_241, height=140)
                    if lk241: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk241 or "")]))

                cor_p241 = "#dc3545" if d241.get("pontos", 0.0) < 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p241}; font-weight:bold;'>📊 Impacto 24.1: {d241.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("24.1", res_data, sufixo="fiscal")

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - RGPS
        # =============================================================================
        for q_ref in ["23.0", "24.0", "24.1"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

# =============================================================================
        # BLOCO ISOLADO: QUESITO 25.0 • COMPENSAÇÃO DE ENCARGOS SOCIAIS (RFB)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q25_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 25.0 - Compensação de Encargos Sociais ({ano_sel})", expanded=True):
                st.subheader("25.0 • Compensações Junto à RFB")
                st.write(f"**O Município efetuou, no exercício de {ano_sel}, compensação de encargos sociais junto à Receita Federal do Brasil?**")
                
                d250 = res_data.get("25.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc250 = ["Selecione...", "Sim", "Não"]
                
                valor_limpo_250 = d250.get("valor", "Selecione...")
                if valor_limpo_250 not in opc250: valor_limpo_250 = "Selecione..."
                evidencia_250_salva = d250.get("link", "")

                def cb_250():
                    val = st.session_state.get(f"rad_250_{ano_sel}_fiscal", valor_limpo_250)
                    lnk = st.session_state.get(f"txt_250_{ano_sel}_fiscal", evidencia_250_salva).strip()
                    
                    save_resp("25.0", val, 0.0, lnk)
                    res_data["25.0"] = {"valor": val, "pontos": 0.0, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_250_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_250_salva or ""):
                        st.session_state[f"links_pendentes_25_0_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_25_0_{ano_sel}"] = True

                c1, c2 = st.columns([1, 1])
                with c1:
                    st.radio("Selecione 25.0:", opc250, index=opc250.index(valor_limpo_250), key=f"rad_250_{ano_sel}_fiscal", on_change=cb_250)
                with c2:
                    lk250 = st.text_area(f"Link/Evidência da Declaração de Compensação (PER/DCOMP) ({ano_sel}):", value=evidencia_250_salva, key=f"txt_250_{ano_sel}_fiscal", on_change=cb_250, height=100)
                    if lk250: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk250 or "")]))

                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 25.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("25.0", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 25.1 • AUTORIZAÇÃO FORMAL DE COMPENSAÇÃO (RFB)
        # =============================================================================
        with st.container(key=f"bloco_isolado_q25_1_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 25.1 - Lastro Formal das Compensações ({ano_sel})", expanded=True):
                st.subheader("25.1 • Regularidade / Decisão Autorizativa")
                st.write("**Houve autorização formal administrativa da Receita Federal do Brasil (RFB) ou decisão judicial para realizar as compensações?**")
                
                d251 = res_data.get("25.1", {"valor": "Selecione...", "pontos": 0.0, "link": ""}) or {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                opc251 = ["Selecione...", "Sim – 00", "Não – -25 (perde 25 pontos)"]
                
                valor_limpo_251 = d251.get("valor", "Selecione...")
                if valor_limpo_251 not in opc251: valor_limpo_251 = "Selecione..."
                evidencia_251_salva = d251.get("link", "")

                def cb_251():
                    val = st.session_state.get(f"rad_251_{ano_sel}_fiscal", valor_limpo_251)
                    lnk = st.session_state.get(f"txt_251_{ano_sel}_fiscal", evidencia_251_salva).strip()
                    
                    pts = 0.0 if "Sim" in val else (-25.0 if "Não" in val else 0.0)
                    save_resp("25.1", val, pts, lnk)
                    res_data["25.1"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    lk_at = re.findall(r'(https?://[^\s]+)', lnk or "")
                    if lnk != evidencia_251_salva and lk_at and lk_at != re.findall(r'(https?://[^\s]+)', evidencia_251_salva or ""):
                        st.session_state[f"links_pendentes_25_1_{ano_sel}"] = lk_at
                        st.session_state[f"gatilho_modal_25_1_{ano_sel}"] = True

                c3, c4 = st.columns([1, 1])
                with c3:
                    st.radio("Selecione 25.1:", opc251, index=opc251.index(valor_limpo_251), key=f"rad_251_{ano_sel}_fiscal", on_change=cb_251)
                with c4:
                    lk251 = st.text_area(f"Link/Evidência do Ato Autorizativo ou Sentença Judicial ({ano_sel}):", value=evidencia_251_salva, key=f"txt_251_{ano_sel}_fiscal", on_change=cb_251, height=100)
                    if lk251: st.markdown("**🔗 Ativos:** " + " | ".join([f"[{u}]({u})" for u in re.findall(r'(https?://[^\s]+)', lk251 or "")]))

                cor_p251 = "#dc3545" if d251.get("pontos", 0.0) < 0 else "#28a745"
                st.markdown(f"<span style='color:{cor_p251}; font-weight:bold;'>📊 Impacto 25.1: {d251.get('pontos', 0.0)} pontos aplicados</span>", unsafe_allow_html=True)
                bloco_comentarios("25.1", res_data, sufixo="fiscal")

        # =============================================================================
        # BLOCO ISOLADO: QUESITO 26.0 • CONSIDERAÇÕES FINAIS / OUVIDORIA
        # =============================================================================
        with st.container(key=f"bloco_isolado_q26_0_{ano_sel}_fiscal", border=True):
            with st.expander(f"📌 Quesito 26.0 - Impressões Finais ({ano_sel})", expanded=True):
                st.subheader("26.0 • Ouvidoria e Espaço Crítico")
                st.write("**Gostaria de registrar suas impressões, comentários e sugestões a respeito do presente questionário?**")
                st.caption("ℹ️ *Utilize o espaço abaixo de forma livre para documentar observações sobre a usabilidade, críticas ou pontos de melhoria.*")
                
                d260 = res_data.get("26.0", {"valor": "", "pontos": 0.0, "link": ""}) or {"valor": "", "pontos": 0.0, "link": ""}
                v_salvo_260 = d260.get("valor", "")

                def cb_260():
                    val = st.session_state.get(f"txt_260_val_{ano_sel}_fiscal", v_salvo_260)
                    save_resp("26.0", val, 0.0, "")
                    res_data["26.0"] = {"valor": val, "pontos": 0.0, "link": ""}

                st.text_area(
                    "Impressões, comentários e sugestões:", 
                    value=v_salvo_260, 
                    key=f"txt_260_val_{ano_sel}_fiscal", 
                    on_change=cb_260,
                    height=180
                )
                
                st.markdown("<span style='color:#28a745; font-weight:bold;'>📊 Impacto 26.0: 0.0 pontos aplicados</span>", unsafe_allow_html=True)

        # =============================================================================
        # CENTRALIZADOR ASSESTRADO DE SINALIZAÇÃO DE MODAIS (INLINE ESCUTA) - BLOCO 25 E 26
        # =============================================================================
        for q_ref in ["25.0", "25.1"]:
            suf_chv = q_ref.replace('.', '_')
            if st.session_state.get(f"gatilho_modal_{suf_chv}_{ano_sel}", False):
                modal_aviso_link(q_ref, st.session_state.get(f"links_pendentes_{suf_chv}_{ano_sel}", []))
                st.session_state[f"gatilho_modal_{suf_chv}_{ano_sel}"] = False

    # -------------------------------------------------------------------------
    # SEÇÃO 8: INDICADORES FINANCEIROS (F1 A F18)
    # -------------------------------------------------------------------------
    st.markdown('<div class="section-header"><h3>8. Indicadores Financeiros (AUDESP)</h3></div>', unsafe_allow_html=True)

    # F1 • Análise da Receita com Formatação BR, Critérios e Key-Toggle
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
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
    
    # 📝 Inclusão das memórias matemáticas oficiais solicitadas
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regras de Distribuição Proporcional nos Intervalos:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 1,15 e menores que 1,5:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente, demonstrado por: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((Q – 1,5) * (-1) / 0,35) * 75</code> <br><i>Exemplo: se Q = 1,25, a nota do indicador será 53,57 pontos.</i></li>
            <li style="margin-top: 8px;"><b>Para resultados maiores que 0,5 e menores que 0,85:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente, demonstrado por: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((Q – 0,5) / 0,35) * 75</code> <br><i>Exemplo: se Q = 0,75, a nota do indicador será 53,57 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para resetar o cache do Streamlit
    if f"f1_o_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f1_o_key_suffix_{ano_sel}"] = 0
    if f"f1_p_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f1_p_key_suffix_{ano_sel}"] = 0

    dF1 = res_data.get("F1", {"valor": "0.00/1.00", "pontos": 0, "link": ""})
    
    # Faz o parse seguro dos valores salvos no banco para exibição inicial
    try:
        val_salvo_o, val_salvo_p = dF1["valor"].split("/")
        float_o = float(val_salvo_o)
        float_p = float(val_salvo_p)
    except:
        float_o, float_p = 0.0, 1.0

    # Aplica a máscara visual brasileira de R$ para o valor inicial do input
    str_inicial_o = f"R$ {float_o:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_p = f"R$ {float_p:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input Inteligente 1: Receita Arrecadada (O)
        sufixo_o = st.session_state[f"f1_o_key_suffix_{ano_sel}"]
        input_o_str = st.text_input(
            "Receita Arrecadada (O) - R$:",
            value=str_inicial_o,
            placeholder="Ex: 1.500.000,00",
            key=f"txt_f1_o_dinamico_{ano_sel}_{sufixo_o}_{ctr}"
        )
        
        # Input Inteligente 2: Receita Prevista (P)
        sufixo_p = st.session_state[f"f1_p_key_suffix_{ano_sel}"]
        input_p_str = st.text_input(
            "Receita Prevista Atualizada (P) - R$:",
            value=str_inicial_p,
            placeholder="Ex: 1.250.000,00",
            key=f"txt_f1_p_dinamico_{ano_sel}_{sufixo_p}_{ctr}"
        )

        # 🧹 Função interna para limpar a string BR e converter em float puro
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Processamento e reatividade ao alterar os campos textuais
        try:
            v_arr = limpa_conversao_monetaria(input_o_str)
            v_prev = max(limpa_conversao_monetaria(input_p_str), 0.01) # Evita divisão por zero
            
            # Cálculo matemático do Indicador Q
            Q = v_arr / v_prev
            
            # Aplicação estrita da tabela de pontuação e faixas de graduação
            if Q >= 1.5 or Q <= 0.5:
                ptsF1 = 0.0
            elif 0.85 <= Q <= 1.15:
                ptsF1 = 75.0
            elif 1.15 < Q < 1.5:
                ptsF1 = ((Q - 1.5) * (-1) / 0.35) * 75
            else: # Faixa entre 0.5 e 0.85
                ptsF1 = ((Q - 0.5) / 0.35) * 75
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_arr, v_prev, Q, ptsF1 = float_o, float_p, (float_o / max(float_p, 0.01)), float(dF1.get("pontos", 0))

    with c2:
        lF1 = st.text_area("Link/Evidência (F1):", value=dF1.get("link", ""), key=f"txt_f1_{ano_sel}_{ctr}", height=150)

    # Exibição explícita do cálculo do Indicador Q e a Nota Resultante
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Execução:</b> R$ {v_arr:,.2f} / R$ {v_prev:,.2f}<br>
        📊 <b>Resultado do Indicador (Q):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{Q:.4f}</code><br>
        🎯 <b>Pontuação Obtida:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{ptsF1:.2f} pontos</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Identifica se houve mudança de dados para salvar no banco e forçar o Toggle das Chaves
    string_banco_atual = f"{v_arr:.2f}/{v_prev:.2f}"
    string_banco_salva = f"{float_o:.2f}/{float_p:.2f}"

    if string_banco_atual != string_banco_salva or lF1 != dF1["link"]:
        save_resp("F1", string_banco_atual, ptsF1, lF1)
        
        # Se alterou o valor Arrecadado, incrementa o sufixo O
        if f"{v_arr:.2f}" != f"{float_o:.2f}":
            st.session_state[f"f1_o_key_suffix_{ano_sel}"] += 1
        # Se alterou o valor Previsto, incrementa o sufixo P
        if f"{v_prev:.2f}" != f"{float_p:.2f}":
            st.session_state[f"f1_p_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F1", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F2 • Análise da Despesa com Formatação BR, Critérios e Key-Toggle
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
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
    
    # 📝 Inclusão das memórias matemáticas oficiais do indicador F2
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regras de Distribuição Proporcional nos Intervalos (Despesa):</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 1,0 e menores que 1,1:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente, demonstrado por: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((T – 1,1) * (-1) / 0,10) * 75</code> <br><i>Exemplo: se T = 1,05, a nota do indicador será 37,50 pontos.</i></li>
            <li style="margin-top: 8px;"><b>Para resultados maiores que 0,5 e menores que 0,9:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente, demonstrado por: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((T – 0,5) / 0,40) * 75</code> <br><i>Exemplo: se T = 0,75, a nota do indicador será 46,88 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para desvincular o cache do Streamlit
    if f"f2_r_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f2_r_key_suffix_{ano_sel}"] = 0
    if f"f2_s_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f2_s_key_suffix_{ano_sel}"] = 0

    dF2 = res_data.get("F2", {"valor": "0.00/1.00", "pontos": 0, "link": ""})
    
    # Faz o parse seguro dos valores salvos no banco (R / S)
    try:
        val_salvo_r, val_salvo_s = dF2["valor"].split("/")
        float_r = float(val_salvo_r)
        float_s = float(val_salvo_s)
    except:
        float_r, float_s = 0.0, 1.0

    # Aplica a máscara visual brasileira (R$) para a renderização inicial
    str_inicial_r = f"R$ {float_r:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_s = f"R$ {float_s:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input Inteligente 1: Despesa Executada (R)
        sufixo_r = st.session_state[f"f2_r_key_suffix_{ano_sel}"]
        input_r_str = st.text_input(
            "Despesa Executada (R) - R$:",
            value=str_inicial_r,
            placeholder="Ex: 1.050.000,00",
            key=f"txt_f2_r_dinamico_{ano_sel}_{sufixo_r}_{ctr}"
        )
        
        # Input Inteligente 2: Despesa Fixada Final (S)
        sufixo_s = st.session_state[f"f2_s_key_suffix_{ano_sel}"]
        input_s_str = st.text_input(
            "Despesa Fixada Final (S) - R$:",
            value=str_inicial_s,
            placeholder="Ex: 1.000.000,00",
            key=f"txt_f2_s_dinamico_{ano_sel}_{sufixo_s}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Processamento matemático reativo
        try:
            v_exec = limpa_conversao_monetaria(input_r_str)
            v_fix = max(limpa_conversao_monetaria(input_s_str), 0.01) # Evita divisão por zero
            
            # Cálculo matemático do Indicador T
            T = v_exec / v_fix
            
            # Regras de negócio e faixas específicas do indicador T
            if T >= 1.1 or T <= 0.5:
                ptsF2 = 0.0
            elif 0.9 <= T <= 1.0:
                ptsF2 = 75.0
            elif 1.0 < T < 1.1:
                ptsF2 = ((T - 1.1) * (-1) / 0.10) * 75
            else: # Faixa entre 0.5 e 0.9
                ptsF2 = ((T - 0.5) / 0.40) * 75
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_exec, v_fix, T, ptsF2 = float_r, float_s, (float_r / max(float_s, 0.01)), float(dF2.get("pontos", 0))

    with c2:
        lF2 = st.text_area("Link/Evidência (F2):", value=dF2.get("link", ""), key=f"txt_f2_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de resultados matemáticos
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Execução:</b> R$ {v_exec:,.2f} / R$ {v_fix:,.2f}<br>
        📊 <b>Resultado do Indicador (T):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{T:.4f}</code><br>
        🎯 <b>Pontuação Obtida:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{ptsF2:.2f} pontos</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência e invalidação de chaves
    string_banco_atual = f"{v_exec:.2f}/{v_fix:.2f}"
    string_banco_salva = f"{float_r:.2f}/{float_s:.2f}"

    if string_banco_atual != string_banco_salva or lF2 != dF2["link"]:
        save_resp("F2", string_banco_atual, ptsF2, lF2)
        
        # Incrementa individualmente conforme a mudança detectada para não travar o foco
        if f"{v_exec:.2f}" != f"{float_r:.2f}":
            st.session_state[f"f2_r_key_suffix_{ano_sel}"] += 1
        if f"{v_fix:.2f}" != f"{float_s:.2f}":
            st.session_state[f"f2_s_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F2", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F3 • Análise do Resultado da Execução Orçamentária com Formatação BR e Cobertura de Déficit
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
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
    
    # 📝 Inclusão das memórias matemáticas oficiais do indicador F3
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Fórmulas de Distribuição nos Intervalos e Regra de Cobertura ($X$):</b></p>
        <p style="font-size: 13px; margin-bottom: 8px;"><i>Déficit ($V > 1$): O módulo da diferença $|O - R| = X$ é comparado aos créditos abertos por superávit financeiro. Se o crédito for igual ou maior, há cobertura financeira.</i></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Se V está entre 1,1 e 1,2 (Com Cobertura):</b> <code style="background-color: #e2e8f0; padding: 2px 5px;">((V – 1,2) * (-1) / 0,10) * 100</code> <br><i>Exemplo: se V = 1,15, a nota será 50,00 pontos.</i></li>
            <li style="margin-top: 8px;"><b>Se V está entre 0,75 e 0,90:</b> <code style="background-color: #e2e8f0; padding: 2px 5px;">((V – 0,75) / 0,15) * 100</code> <br><i>Exemplo: se V = 0,80, a nota será 33,33 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para desvincular o cache do Streamlit
    if f"f3_r_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f3_r_key_suffix_{ano_sel}"] = 0
    if f"f3_o_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f3_o_key_suffix_{ano_sel}"] = 0
    if f"f3_c_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f3_c_key_suffix_{ano_sel}"] = 0

    # Busca ou inicializa os dados salvos estruturados por barra (R/O/C)
    dF3 = res_data.get("F3", {"valor": "0.00/1.00/0.00", "pontos": 0, "link": ""})
    
    try:
        val_salvo_r, val_salvo_o, val_salvo_c = dF3["valor"].split("/")
        float_r = float(val_salvo_r)
        float_o = float(val_salvo_o)
        float_c = float(val_salvo_c)
    except:
        float_r, float_o, float_c = 0.0, 1.0, 0.0

    # Aplica as máscaras visuais no padrão brasileiro (R$) para os inputs textuais
    str_inicial_r = f"R$ {float_r:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_o = f"R$ {float_o:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_c = f"R$ {float_c:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input 1: Despesa Executada (R)
        sufixo_r = st.session_state[f"f3_r_key_suffix_{ano_sel}"]
        input_r_str = st.text_input(
            "Despesa Executada (R) - R$:",
            value=str_inicial_r,
            key=f"txt_f3_r_dinamico_{ano_sel}_{sufixo_r}_{ctr}"
        )
        
        # Input 2: Receita Arrecadada (O)
        sufixo_o = st.session_state[f"f3_o_key_suffix_{ano_sel}"]
        input_o_str = st.text_input(
            "Receita Arrecadada (O) - R$:",
            value=str_inicial_o,
            key=f"txt_f3_o_dinamico_{ano_sel}_{sufixo_o}_{ctr}"
        )

        # Input 3: Créditos por Superávit Financeiro (C)
        sufixo_c = st.session_state[f"f3_c_key_suffix_{ano_sel}"]
        input_c_str = st.text_input(
            "Créditos por Superávit Financeiro - R$:",
            value=str_inicial_c,
            key=f"txt_f3_c_dinamico_{ano_sel}_{sufixo_c}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Processamento lógico-matemático reativo
        try:
            v_exec = limpa_conversao_monetaria(input_r_str)
            v_arrec = max(limpa_conversao_monetaria(input_o_str), 0.01) # Evita divisão por zero
            v_cred_superavit = limpa_conversao_monetaria(input_c_str)
            
            # Cálculo do Indicador V e do Módulo da Diferença X
            V = v_exec / v_arrec
            X = abs(v_arrec - v_exec)
            
            # Avaliação de Cobertura Financeira do Déficit
            tem_cobertura = v_cred_superavit >= X

            # Motor de Regras de Pontuação Oficial do Indicador V
            if V >= 1.2:
                ptsF3 = 0.0
            elif 1.1 < V < 1.2:
                ptsF3 = ((V - 1.2) * (-1) / 0.10) * 100 if tem_cobertura else 0.0
            elif 1.0 < V <= 1.1:
                ptsF3 = 100.0 if tem_cobertura else 0.0
            elif 0.9 <= V <= 1.0:
                ptsF3 = 100.0
            elif 0.75 < V < 0.9:
                ptsF3 = ((V - 0.75) / 0.15) * 100
            else: # V <= 0.75
                ptsF3 = 0.0
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_exec, v_arrec, v_cred_superavit = float_r, float_o, float_c
            V = float_r / max(float_o, 0.01)
            X = abs(float_o - float_r)
            tem_cobertura = float_c >= X
            ptsF3 = float(dF3.get("pontos", 0))

    with c2:
        lF3 = st.text_area("Link/Evidência (F3):", value=dF3.get("link", ""), key=f"txt_f3_{ano_sel}_{ctr}", height=215)

    # Construção do quadro analítico de resultados contábeis
    status_cobertura = "🟢 Déficit Coberto por Superávit" if tem_cobertura else "🔴 Déficit Não Coberto"
    if V <= 1.0:
        status_cobertura = "🔵 Superávit Orçamentário Corrente"

    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Análise Contábil:</b> R$ {v_exec:,.2f} / R$ {v_arrec:,.2f}<br>
        📊 <b>Resultado do Indicador (V):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{V:.4f}</code><br>
        ⚖️ <b>Diferença em Módulo (X):</b> R$ {X:,.2f} | <b>Situação:</b> <i>{status_cobertura}</i><br>
        🎯 <b>Pontuação Obtida:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{ptsF3:.2f} pontos</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Identificação de alterações para gravação em banco e incremento dos sufixos de input
    string_banco_atual = f"{v_exec:.2f}/{v_arrec:.2f}/{v_cred_superavit:.2f}"
    string_banco_salva = f"{float_r:.2f}/{float_o:.2f}/{float_c:.2f}"

    if string_banco_atual != string_banco_salva or lF3 != dF3["link"]:
        save_resp("F3", string_banco_atual, ptsF3, lF3)
        
        if f"{v_exec:.2f}" != f"{float_r:.2f}":
            st.session_state[f"f3_r_key_suffix_{ano_sel}"] += 1
        if f"{v_arrec:.2f}" != f"{float_o:.2f}":
            st.session_state[f"f3_o_key_suffix_{ano_sel}"] += 1
        if f"{v_cred_superavit:.2f}" != f"{float_c:.2f}":
            st.session_state[f"f3_c_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F3", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F4 • Análise do Esforço para Pagamento de Restos a Pagar (Dívida Flutuante)
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
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
    
    # 📝 Inclusão das memórias matemáticas oficiais do indicador F4
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 0,75 e menores que 0,95:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente, demonstrado por: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((Z – 0,75) / 0,20) * 25</code> <br><i>Exemplo: se Z = 0,80, a nota do indicador será 6,25 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar de forma independente o cache do Streamlit
    if f"f4_a_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f4_a_key_suffix_{ano_sel}"] = 0
    if f"f4_b_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f4_b_key_suffix_{ano_sel}"] = 0
    if f"f4_c_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f4_c_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a tripla de valores separada por barras (A/B/C)
    dF4 = res_data.get("F4", {"valor": "0.00/1.00/0.00", "pontos": 0, "link": ""})
    
    try:
        val_salvo_a, val_salvo_b, val_salvo_c = dF4["valor"].split("/")
        float_a = float(val_salvo_a)
        float_b = float(val_salvo_b)
        float_c = float(val_salvo_c)
    except:
        float_a, float_b, float_c = 0.0, 1.0, 0.0

    # Converte os números de ponto flutuante na máscara brasileira de apresentação (R$)
    str_inicial_a = f"R$ {float_a:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_b = f"R$ {float_b:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_c = f"R$ {float_c:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input 1: Pagamentos Realizados de RP (A)
        sufixo_a = st.session_state[f"f4_a_key_suffix_{ano_sel}"]
        input_a_str = st.text_input(
            "Pagamentos Realizados (A) - R$:",
            value=str_inicial_a,
            key=f"txt_f4_a_dinamico_{ano_sel}_{sufixo_a}_{ctr}"
        )
        
        # Input 2: Posição Inicial de RP (B)
        sufixo_b = st.session_state[f"f4_b_key_suffix_{ano_sel}"]
        input_b_str = st.text_input(
            "Posição Inicial de Restos a Pagar (B) - R$:",
            value=str_inicial_b,
            key=f"txt_f4_b_dinamico_{ano_sel}_{sufixo_b}_{ctr}"
        )

        # Input 3: Cancelamentos de RP no Exercício (C)
        sufixo_c = st.session_state[f"f4_c_key_suffix_{ano_sel}"]
        input_c_str = st.text_input(
            "Cancelamentos no Exercício (C) - R$:",
            value=str_inicial_c,
            key=f"txt_f4_c_dinamico_{ano_sel}_{sufixo_c}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do indicador Z
        try:
            v_pago = limpa_conversao_monetaria(input_a_str)
            v_pos_inicial = limpa_conversao_monetaria(input_b_str)
            v_cancelado = limpa_conversao_monetaria(input_c_str)
            
            # Cálculo da posição líquida (B - C) evitando divisão por zero ou base negativa
            posicao_liquida = max(v_pos_inicial - v_cancelado, 0.01)
            
            # Cálculo do Indicador Z
            Z = v_pago / posicao_liquida
            
            # Motor de regras de pontuação oficial do Indicador Z
            if Z >= 0.95:
                ptsF4 = 25.0
            elif 0.75 < Z < 0.95:
                ptsF4 = ((Z - 0.75) / 0.20) * 25
            else: # Z <= 0.75
                ptsF4 = 0.0
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_pago, v_pos_inicial, v_cancelado = float_a, float_b, float_c
            Z = float_a / max(float_b - float_c, 0.01)
            ptsF4 = float(dF4.get("pontos", 0))

    with c2:
        lF4 = st.text_area("Link/Evidência (F4 - Item GF26 AUDESP):", value=dF4.get("link", ""), key=f"txt_f4_{ano_sel}_{ctr}", height=215)

    # Exibição do painel consolidador de métricas fiscais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo do Esforço:</b> R$ {v_pago:,.2f} / (R$ {v_pos_inicial:,.2f} - R$ {v_cancelado:,.2f})<br>
        📊 <b>Resultado do Indicador (Z):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{Z:.4f}</code><br>
        🎯 <b>Pontuação Obtida:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{ptsF4:.2f} pontos</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência e invalidação de chaves textuais
    string_banco_atual = f"{v_pago:.2f}/{v_pos_inicial:.2f}/{v_cancelado:.2f}"
    string_banco_salva = f"{float_a:.2f}/{float_b:.2f}/{float_c:.2f}"

    if string_banco_atual != string_banco_salva or lF4 != dF4["link"]:
        save_resp("F4", string_banco_atual, ptsF4, lF4)
        
        # Incrementa individualmente as chaves correspondentes aos valores modificados
        if f"{v_pago:.2f}" != f"{float_a:.2f}":
            st.session_state[f"f4_a_key_suffix_{ano_sel}"] += 1
        if f"{v_pos_inicial:.2f}" != f"{float_b:.2f}":
            st.session_state[f"f4_b_key_suffix_{ano_sel}"] += 1
        if f"{v_cancelado:.2f}" != f"{float_c:.2f}":
            st.session_state[f"f4_c_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F4", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F5 • Análise do Nível de Cancelamento de Restos a Pagar
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F5 • Análise do Nível de Cancelamento de Restos a Pagar")
    st.write("**Divisão dos cancelamentos realizados pela posição inicial de restos a pagar (C / B = K)**")
    
    # Tabela Oficial de Parâmetros e Pontuações do Indicador F5
    st.markdown("""
    | Resultado de $K$ | Pontuação do Indicador |
    | :--- | :--- |
    | Maior ou igual a 0,20 | 0 |
    | Maior que 0,05 e menor que 0,20 | Graduação entre 0 e 25 |
    | Menor ou igual a 0,05 | 25 |
    """)
    
    # 📝 Inclusão das memórias matemáticas oficiais do indicador F5
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 0,05 e menores que 0,20:</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente, demonstrado por: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((0,20 - K) / 0,15) * 25</code> <br><i>Exemplo: se K = 0,06, a nota do indicador será 23,33 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar de forma independente o cache do Streamlit
    if f"f5_c_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f5_c_key_suffix_{ano_sel}"] = 0
    if f"f5_b_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f5_b_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores separada por barra (C/B)
    dF5 = res_data.get("F5", {"valor": "0.00/1.00", "pontos": 0, "link": ""})
    
    try:
        val_salvo_c, val_salvo_b = dF5["valor"].split("/")
        float_c = float(val_salvo_c)
        float_b = float(val_salvo_b)
    except:
        float_c, float_b = 0.0, 1.0

    # Converte os números de ponto flutuante na máscara brasileira de apresentação (R$)
    str_inicial_c = f"R$ {float_c:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_b = f"R$ {float_b:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input 1: Cancelamentos de RP no Exercício (C)
        sufixo_c = st.session_state[f"f5_c_key_suffix_{ano_sel}"]
        input_c_str = st.text_input(
            "Cancelamentos no Exercício (C) - R$:",
            value=str_inicial_c,
            key=f"txt_f5_c_dinamico_{ano_sel}_{sufixo_c}_{ctr}"
        )
        
        # Input 2: Posição Inicial de RP (B)
        sufixo_b = st.session_state[f"f5_b_key_suffix_{ano_sel}"]
        input_b_str = st.text_input(
            "Posição Inicial de Restos a Pagar (B) - R$:",
            value=str_inicial_b,
            key=f"txt_f5_b_dinamico_{ano_sel}_{sufixo_b}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do indicador K
        try:
            v_cancelado = limpa_conversao_monetaria(input_c_str)
            v_pos_inicial = max(limpa_conversao_monetaria(input_b_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Indicador K
            K = v_cancelado / v_pos_inicial
            
            # 🛑 TRAVA DE INICIALIZAÇÃO: Se os campos estiverem zerados/não editados, não pontua automático
            if v_cancelado == 0.0 and (dF5.get("link", "").strip() == ""):
                ptsF5 = 0.0
                texto_pontuacao = "⏳ Aguardando preenchimento para cálculo..."
            else:
                # Motor de regras de pontuação oficial do Indicador K
                if K >= 0.20:
                    ptsF5 = 0.0
                elif 0.05 < K < 0.20:
                    ptsF5 = ((0.20 - K) / 0.15) * 25
                else: # K <= 0.05
                    ptsF5 = 25.0
                texto_pontuacao = f"{ptsF5:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_cancelado, v_pos_inicial = float_c, float_b
            K = float_c / max(float_b, 0.01)
            ptsF5 = float(dF5.get("pontos", 0))
            texto_pontuacao = f"{ptsF5:.2f} pontos"

    with c2:
        lF5 = st.text_area("Link/Evidência (F5 - Item GF26 AUDESP):", value=dF5.get("link", ""), key=f"txt_f5_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo do Nível de Cancelamento:</b> R$ {v_cancelado:,.2f} / R$ {v_pos_inicial:,.2f}<br>
        📊 <b>Resultado do Indicador (K):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{K:.4f}</code><br>
        🎯 <b>Pontuação Obtida:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência e invalidação de chaves textuais
    string_banco_atual = f"{v_cancelado:.2f}/{v_pos_inicial:.2f}"
    string_banco_salva = f"{float_c:.2f}/{float_b:.2f}"

    if string_banco_atual != string_banco_salva or lF5 != dF5["link"]:
        save_resp("F5", string_banco_atual, ptsF5, lF5)
        
        # Incrementa individualmente as chaves correspondentes aos valores modificados
        if f"{v_cancelado:.2f}" != f"{float_c:.2f}":
            st.session_state[f"f5_c_key_suffix_{ano_sel}"] += 1
        if f"{v_pos_inicial:.2f}" != f"{float_b:.2f}":
            st.session_state[f"f5_b_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F5", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F6 • Despesas com Pessoal – Poder Executivo
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F6 • Despesas com Pessoal – Poder Executivo (LRF)")
    st.write("**Índice da Despesa Total com Pessoal do Executivo em relação à Receita Corrente Líquida (RCL)**")
    
    # Tabela Oficial de Parâmetros convertida para Percentual
    st.markdown("""
    | Resultado do Índice (%) | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Maior que 54,00% (Acima do Limite Legal) | 🚨 Rebaixa 1 faixa do i-Fiscal |
    | Entre 51,30% e 54,00% (Acima do Limite de Alerta) | ⚠️ -20 (Perde 20 pontos) |
    | Menor que 51,30% (Dentro do Limite) | ✅ 00 (Sem penalidades) |
    """)
    st.caption("ℹ️ *Dados obtidos a partir do Relatório de Instrução, item GF27 do Sistema AUDESP.*")
    st.markdown("<br>", unsafe_allow_html=True)

    # Inicializa o sufixo de controle no session_state para o Key-Toggle
    if f"f6_pessoal_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f6_pessoal_key_suffix_{ano_sel}"] = 0

    dF6 = res_data.get("F6", {"valor": "0.00", "pontos": 0, "link": ""})
    
    # Faz o parse seguro do valor percentual salvo (armazenado como float decimal, ex: 0.513)
    try:
        float_f6 = float(dF6["valor"])
    except:
        float_f6 = 0.0

    # Converte o float decimal para string percentual formatada no padrão BR (ex: 51,30%)
    str_inicial_f6 = f"{float_f6 * 100:.2f}%".replace(".", ",")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input Inteligente de Texto para o Percentual de Pessoal
        sufixo_f6 = st.session_state[f"f6_pessoal_key_suffix_{ano_sel}"]
        input_f6_str = st.text_input(
            "Índice de Despesa com Pessoal (%):",
            value=str_inicial_f6,
            placeholder="Ex: 51,30%",
            key=f"txt_f6_dinamico_{ano_sel}_{sufixo_f6}_{ctr}"
        )

        # 🧹 Função interna para limpar o símbolo '%' e converter para float decimal puro
        try:
            num_limpo = input_f6_str.replace("%", "").replace(" ", "").replace(",", ".")
            v_indice = float(num_limpo) / 100.0  # Transforma 51.30 em 0.513
            
            # 🛑 TRAVA DE INICIALIZAÇÃO: Evita aplicar nota 0 ou rebaixamento sem preenchimento
            if v_indice == 0.0 and (dF6.get("link", "").strip() == ""):
                ptsF6 = 0.0
                texto_resultado = "⏳ Aguardando preenchimento do índice..."
                estilo_status = "color: #64748b;"
            else:
                # Motor de regras baseado nas faixas da AUDESP
                if v_indice > 0.54:
                    ptsF6 = 0.0  # O rebaixamento de faixa do i-Fiscal deve ser tratado no consolidado geral
                    texto_resultado = "🚨 CRÍTICO: Maior que 54,00% (Gera Rebaixamento de Faixa Geral)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                elif 0.513 <= v_indice <= 0.54:
                    ptsF6 = -20.0
                    texto_resultado = "⚠️ ALERTA: Entre 51,30% e 54,00% (Penalidade: -20,00 pontos)"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else:
                    ptsF6 = 0.0
                    texto_resultado = "✅ REGULAR: Menor que 51,30% (Sem penalidades)"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                    
        except ValueError:
            st.error("⚠️ Formato de percentual inválido. Digite utilizando o padrão brasileiro (Ex: 52,45%).")
            v_indice = float_f6
            ptsF6 = float(dF6.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            estilo_status = "color: #dc2626;"

    with c2:
        lF6 = st.text_area("Link/Evidência (F6 - Item GF27 AUDESP):", value=dF6.get("link", ""), key=f"txt_f6_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador formatado em percentual brasileiro
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📊 <b>Índice Calculado:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{v_indice * 100:.2f}%</code><br>
        ⚖️ <b>Status da LRF:</b> <span style="{estilo_status}">{texto_resultado}</span>
    </div>
    """.replace(".", ","), unsafe_allow_html=True)

    # Verificação de alteração de dados para gravação e recarga do componente
    string_banco_atual = f"{v_indice:.4f}"
    string_banco_salva = f"{float_f6:.4f}"

    if string_banco_atual != string_banco_salva or lF6 != dF6["link"]:
        save_resp("F6", string_banco_atual, ptsF6, lF6)
        st.session_state[f"f6_pessoal_key_suffix_{ano_sel}"] += 1
        st.rerun()

    bloco_comentarios("F6", res_data)
    st.markdown('</div>', unsafe_allow_html=True)
# F7 • Despesas com Pessoal – Poder Legislativo
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F7 • Despesas com Pessoal – Poder Legislativo (LRF)")
    st.write("**Índice da Despesa Total com Pessoal do Legislativo em relação à Receita Corrente Líquida (DPPL / RCL = AB)**")
    
    # Adicionado o prefixo 'r' para corrigir os erros de SyntaxWarning (\ge e \le)
    st.markdown(r"""
    | Resultado do Índice $AB$ (%) | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Maior que 6,00% ($> 0,06$) | 🚨 -10 (Perde 10 pontos) |
    | Entre 5,60% e 6,00% ($\ge 0,056$ e $\le 0,06$) | ⚠️ Graduação entre 0 e -10 pontos |
    | Menor que 5,60% ($< 0,056$) | ✅ 00 pontos (Sem penalidades) |
    """)
    
    # 📝 Inclusão das memórias matemáticas oficiais do indicador F7
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo Crítico (Base Decimal):</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 5,70% (0,057) e menores ou iguais a 6,00% (0,060):</b> A graduação de penalidade será calculada estritamente sobre a base decimal. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AB – 0,057) / 0,003) * (-10)</code> <br><i>Exemplo: se AB = 5,80% (0,058), a perda será de -3,33 pontos. Se AB = 6,00% (0,060), a fórmula processa o teto exato de -10,00 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar de forma independente o cache do Streamlit
    if f"f7_ab_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f7_ab_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo o valor decimal do índice
    dF7 = res_data.get("F7", {"valor": "0.00", "pontos": 0, "link": ""})
    
    try:
        float_ab = float(dF7["valor"])
    except:
        float_ab = 0.0

    # Converte o float decimal para string percentual formatada no padrão BR (ex: 5,80%)
    str_inicial_ab = f"{float_ab * 100:.2f}%".replace(".", ",")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input de Texto Inteligente (O auditor digita em % para facilidade, o código processa em decimal)
        sufixo_ab = st.session_state[f"f7_ab_key_suffix_{ano_sel}"]
        input_ab_str = st.text_input(
            "Índice de Pessoal do Legislativo (AB) - %:",
            value=str_inicial_ab,
            placeholder="Ex: 5,80%",
            key=f"txt_f7_dinamico_{ano_sel}_{sufixo_ab}_{ctr}"
        )

        # 🧹 Higienização e conversão do percentual da tela para número decimal puro
        try:
            num_limpo = input_ab_str.replace("%", "").replace(" ", "").replace(",", ".")
            v_indice = round(float(num_limpo) / 100.0, 4)  # Força o arredondamento em 4 casas decimais para evitar ruídos de ponto flutuante
            
            # 🛑 TRAVA DE INICIALIZAÇÃO: Se estiver zerado e sem link, não gera penalidade automática
            if v_indice == 0.0 and (dF7.get("link", "").strip() == ""):
                ptsF7 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 Motor de Regras Oficiais ajustado para capturar o teto de 0,0600 na fórmula
                if v_indice > 0.0600:
                    ptsF7 = -10.0
                    texto_resultado = "🚨 CRÍTICO: Limite Máximo Estrapolado (> 6,00%)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                elif 0.0570 <= v_indice <= 0.0600:
                    # Agora o 0,0600 entra aqui e roda a fórmula: ((0,060 - 0,057) / 0,003) * -10 = -10,00
                    ptsF7 = ((v_indice - 0.0570) / 0.0030) * (-10.0)
                    texto_resultado = "⚠️ ALERTA DE GRADUAÇÃO (Fórmula Aplicada)"
                    estilo_status = "color: #d97706; font-weight: bold;"
                elif 0.0560 <= v_indice < 0.0570:
                    ptsF7 = 0.0  # Faixa prudencial que não pontua na fórmula, mas está na faixa de graduação inicial do manual
                    texto_resultado = "⚠️ Atenção: Faixa Prudencial de Alerta (Sem penalidade)"
                    estilo_status = "color: #b45309;"
                else:  # v_indice < 0.0560
                    ptsF7 = 0.0
                    texto_resultado = "✅ REGULAR: Menor que 5,60%"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                
                texto_pontuacao = f"{ptsF7:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 5,80%).")
            v_indice = float_ab
            ptsF7 = float(dF7.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF7:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF7 = st.text_area("Link/Evidência (F7 - Item GF27 AUDESP):", value=dF7.get("link", ""), key=f"txt_f7_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📊 <b>Índice Informado:</b> {v_indice * 100:.2f}% | 🕵️ <b>Base Decimal de Análise:</b> <code style="font-size: 14px; font-weight: bold; color: #b45309;">{v_indice:.4f}</code><br>
        ⚖️ <b>Situação do Poder Legislativo:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(".", ","), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência e invalidação de chaves textuais
    string_banco_atual = f"{v_indice:.4f}"
    string_banco_salva = f"{float_ab:.4f}"

    if string_banco_atual != string_banco_salva or lF7 != dF7["link"]:
        save_resp("F7", string_banco_atual, ptsF7, lF7)
        st.session_state[f"f7_ab_key_suffix_{ano_sel}"] += 1
        st.rerun()

    bloco_comentarios("F7", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F8 • Apuração do Resultado Financeiro (Superávit/Déficit)
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F8 • Apuração do Resultado Financeiro (Superávit/Déficit) – Resultado Consolidado")
    st.write("**Divisão entre o Ativo Financeiro e o Passivo Financeiro (AC / AD = AE)**")
    
    # Tabela Oficial de Parâmetros e Pontuações do Indicador F8
    st.markdown("""
    | Resultado de $AE$ | Pontuação do Indicador |
    | :--- | :--- |
    | Maior ou igual a 1,30 | 0 |
    | Maior que 1,10 e menor que 1,30 | Graduação entre 75 e 0 |
    | Maior ou igual a 1,00 e menor ou igual a 1,10 | 75 |
    | Maior que 0,75 e menor que 1,00 | Graduação entre 0 e 75 |
    | Menor ou igual a 0,75 | 0 |
    """)
    
    # 📝 Inclusão das memórias matemáticas oficiais do indicador F8
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regras de Distribuição Proporcional nos Intervalos:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 1,10 e menores que 1,30 (Superávit Elevado):</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AE – 1,30) * (-1) / 0,20) * 75</code> <br><i>Exemplo: se AE = 1,20, a nota do indicador será 37,50 pontos.</i></li>
            <li style="margin-top: 8px;"><b>Para resultados maiores que 0,75 e menores que 1,00 (Tendência a Déficit):</b> A graduação será distribuída igualitariamente no intervalo. Matematicamente: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AE – 0,75) / 0,25) * 75</code> <br><i>Exemplo: se AE = 0,85, a nota do indicador será 30,00 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar de forma independente o cache do Streamlit
    if f"f8_ac_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f8_ac_key_suffix_{ano_sel}"] = 0
    if f"f8_ad_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f8_ad_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores separada por barra (AC/AD)
    dF8 = res_data.get("F8", {"valor": "0.00/1.00", "pontos": 0, "link": ""})
    
    try:
        val_salvo_ac, val_salvo_ad = dF8["valor"].split("/")
        float_ac = float(val_salvo_ac)
        float_ad = float(val_salvo_ad)
    except:
        float_ac, float_ad = 0.0, 1.0

    # Converte os números de ponto flutuante na máscara brasileira de apresentação monetária (R$)
    str_inicial_ac = f"R$ {float_ac:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_ad = f"R$ {float_ad:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input 1: Ativo Financeiro (AC)
        sufixo_ac = st.session_state[f"f8_ac_key_suffix_{ano_sel}"]
        input_ac_str = st.text_input(
            "Ativo Financeiro (AC) - R$:",
            value=str_inicial_ac,
            placeholder="Ex: 1.200.000,00",
            key=f"txt_f8_ac_dinamico_{ano_sel}_{sufixo_ac}_{ctr}"
        )
        
        # Input 2: Passivo Financeiro (AD)
        sufixo_ad = st.session_state[f"f8_ad_key_suffix_{ano_sel}"]
        input_ad_str = st.text_input(
            "Passivo Financeiro (AD) - R$:",
            value=str_inicial_ad,
            placeholder="Ex: 1.000.000,00",
            key=f"txt_f8_ad_dinamico_{ano_sel}_{sufixo_ad}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do indicador AE
        try:
            v_ativo = limpa_conversao_monetaria(input_ac_str)
            v_passivo = max(limpa_conversao_monetaria(input_ad_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Indicador AE
            AE = v_ativo / v_passivo
            
            # 🛑 TRAVA DE INICIALIZAÇÃO: Se estiver zerado e sem link, não gera pontuação automática
            if v_ativo == 0.0 and (dF8.get("link", "").strip() == ""):
                ptsF8 = 0.0
                texto_pontuacao = "⏳ Aguardando preenchimento dos valores monetários..."
            else:
                # Motor de regras de pontuação oficial do Indicador AE
                if AE >= 1.30 or AE <= 0.75:
                    ptsF8 = 0.0
                elif 1.00 <= AE <= 1.10:
                    ptsF8 = 75.0
                elif 1.10 < AE < 1.30:
                    ptsF8 = ((AE - 1.30) * (-1) / 0.20) * 75
                else: # 0.75 < AE < 1.00
                    ptsF8 = ((AE - 0.75) / 0.25) * 75
                
                texto_pontuacao = f"{ptsF8:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_ativo, v_passivo = float_ac, float_ad
            AE = float_ac / max(float_ad, 0.01)
            ptsF8 = float(dF8.get("pontos", 0))
            texto_pontuacao = f"{ptsF8:.2f} pontos"

    with c2:
        lF8 = st.text_area("Link/Evidência (F8 - Balanço Patrimonial AUDESP):", value=dF8.get("link", ""), key=f"txt_f8_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas contábeis (padrão monetário BR)
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Balanço Contábil:</b> R$ {v_ativo:,.2f} / R$ {v_passivo:,.2f}<br>
        📊 <b>Resultado do Indicador (AE):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{AE:.4f}</code><br>
        🎯 <b>Pontuação Obtida:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência e invalidação de chaves textuais
    string_banco_atual = f"{v_ativo:.2f}/{v_passivo:.2f}"
    string_banco_salva = f"{float_ac:.2f}/{float_ad:.2f}"

    if string_banco_atual != string_banco_salva or lF8 != dF8["link"]:
        save_resp("F8", string_banco_atual, ptsF8, lF8)
        
        # Incrementa individualmente as chaves correspondentes aos valores modificados
        if f"{v_ativo:.2f}" != f"{float_ac:.2f}":
            st.session_state[f"f8_ac_key_suffix_{ano_sel}"] += 1
        if f"{v_passivo:.2f}" != f"{float_ad:.2f}":
            st.session_state[f"f8_ad_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F8", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

   # F9 • Apuração da Dívida Fundada (Aumento/Redução)
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F9 • Apuração da Dívida Fundada (DCL / RCL)")
    st.write("**Razão entre a Dívida Consolidada Líquida e a Receita Corrente Líquida [DCL / RCL = AF]**")
    
    # Adicionado o prefixo 'r' para corrigir os erros de SyntaxWarning (\ge e \le)
    st.markdown(r"""
    | Resultado do Índice $AF$ | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Maior que 1,20 ($> 1,2$) | 🚨 -10 (Perde 10 pontos fixos) |
    | Entre 1,10 e 1,20 ($\ge 1,1$ e $\le 1,2$) | ⚠️ Graduação entre 0 e -10 pontos |
    | Menor que 1,10 ($< 1,1$) | ✅ 00 ponto (Sem penalidades) |
    """)
    st.caption("ℹ️ *Dados extraídos do Relatório de Instrução, item GF-28 do Sistema AUDESP.*")
    
    # 📝 Memória de cálculo oficial fornecida
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo Crítico:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 1,10 e menores que 1,20:</b> A graduação será distribuída igualitariamente no intervalo através da fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AF – 1,1) / 0,10) * (-10)</code> <br><i>Exemplo: se AF = 1,15, a nota do indicador será exatamente -5,00 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f9_dcl_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f9_dcl_key_suffix_{ano_sel}"] = 0
    if f"f9_rcl_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f9_rcl_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (DCL/RCL)
    dF9 = res_data.get("F9", {"valor": "0.00/1.00", "pontos": 0, "link": ""})
    
    try:
        val_salvo_dcl, val_salvo_rcl = dF9["valor"].split("/")
        float_dcl = float(val_salvo_dcl)
        float_rcl = float(val_salvo_rcl)
    except:
        float_dcl, float_rcl = 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_dcl = f"R$ {float_dcl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_rcl = f"R$ {float_rcl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Input 1: Dívida Consolidada Líquida (DCL)
        sufixo_dcl = st.session_state[f"f9_dcl_key_suffix_{ano_sel}"]
        input_dcl_str = st.text_input(
            "Dívida Consolidada Líquida (DCL) - R$:",
            value=str_inicial_dcl,
            placeholder="Ex: 12.000.000,00",
            key=f"txt_f9_dcl_dinamico_{ano_sel}_{sufixo_dcl}_{ctr}"
        )
        
        # Input 2: Receita Corrente Líquida (RCL)
        sufixo_rcl = st.session_state[f"f9_rcl_key_suffix_{ano_sel}"]
        input_rcl_str = st.text_input(
            "Receita Corrente Líquida (RCL) - R$:",
            value=str_inicial_rcl,
            placeholder="Ex: 10.000.000,00",
            key=f"txt_f9_rcl_dinamico_{ano_sel}_{sufixo_rcl}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do indicador AF
        try:
            v_dcl = limpa_conversao_monetaria(input_dcl_str)
            v_rcl = max(limpa_conversao_monetaria(input_rcl_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Indicador AF (Decimal Puro)
            AF = round(v_dcl / v_rcl, 4)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO: Se a DCL estiver zerada e sem link, não penaliza automaticamente
            if v_dcl == 0.0 and (dF9.get("link", "").strip() == ""):
                ptsF9 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS: Baseado estritamente no enunciado da AUDESP
                if AF > 1.2000:
                    ptsF9 = -10.0
                    texto_resultado = "🚨 CRÍTICO: Índice Superior ao Teto (> 1,20)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                elif 1.1000 <= AF <= 1.2000:
                    # Aplicação exata da fórmula paramétrica fornecida
                    ptsF9 = ((AF - 1.1000) / 0.1000) * (-10.0)
                    texto_resultado = "⚠️ ALERTA DE GRADUAÇÃO (Fórmula Aplicada)"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else:  # AF < 1.1000
                    ptsF9 = 0.0
                    texto_resultado = "✅ REGULAR: Menor que 1,10 (Sem penalidades)"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                
                texto_pontuacao = f"{ptsF9:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_dcl, v_rcl = float_dcl, float_rcl
            AF = float_dcl / max(float_rcl, 0.01)
            ptsF9 = float(dF9.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF9:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF9 = st.text_area("Link/Evidência (F9 - Item GF-28 AUDESP):", value=dF9.get("link", ""), key=f"txt_f9_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Razão:</b> R$ {v_dcl:,.2f} / R$ {v_rcl:,.2f}<br>
        📊 <b>Resultado do Indicador (AF):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{AF:.4f}</code><br>
        ⚖️ <b>Situação da Dívida Líquida:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência e invalidação de chaves textuais
    string_banco_atual = f"{v_dcl:.2f}/{v_rcl:.2f}"
    string_banco_salva = f"{float_dcl:.2f}/{float_rcl:.2f}"  # Corrigido aqui de float_ad para float_rcl

    if string_banco_atual != string_banco_salva or lF9 != dF9["link"]:
        save_resp("F9", string_banco_atual, ptsF9, lF9)
        
        # Incrementa individualmente as chaves correspondentes aos valores modificados
        if f"{v_dcl:.2f}" != f"{float_dcl:.2f}":
            st.session_state[f"f9_dcl_key_suffix_{ano_sel}"] += 1
        if f"{v_rcl:.2f}" != f"{float_rcl:.2f}":
            st.session_state[f"f9_rcl_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F9", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F10 • Apuração dos Pagamentos dos Precatórios
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F10 • Apuração dos Pagamentos dos Precatórios (AG / AH)")
    st.write("**Razão entre o Estoque Final e o Estoque Inicial de Precatórios [AG / AH = AI]**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Resultado do Índice $AI$ | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Menor ou igual a 0,9 ($\le 0,9$) | ✅ 75 pontos (Pontuação Máxima) |
    | Entre 0,9 e 1,0 ($> 0,9$ e $< 1,0$) | ⚠️ Graduação entre 0 e 75 pontos |
    | Maior ou igual a 1,0 ($\ge 1,0$) | 🚨 00 ponto (Sem bonificação) |
    """)
    st.caption("ℹ️ *Dados extraídos da contabilidade encaminhada pelo Sistema AUDESP.*")

    # 📝 Memória de cálculo oficial fornecida
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo Crítico:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 0,90 e menores que 1,00:</b> A graduação será distribuída igualitariamente no intervalo através da fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AI – 1,0) * (-1) / 0,10) * 75</code> <br><i>Exemplo: se AI = 0,95, a nota do indicador será exatamente 37,50 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f10_ag_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f10_ag_key_suffix_{ano_sel}"] = 0
    if f"f10_ah_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f10_ah_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (AG/AH)
    dF10 = res_data.get("F10", {"valor": "0.00/1.00", "pontos": 0, "link": ""})

    try:
        val_salvo_ag, val_salvo_ah = dF10["valor"].split("/")
        float_ag = float(val_salvo_ag)
        float_ah = float(val_salvo_ah)
    except:
        float_ag, float_ah = 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_ag = f"R$ {float_ag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_ah = f"R$ {float_ah:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Estoque Final dos Precatórios (AG)
        sufixo_ag = st.session_state[f"f10_ag_key_suffix_{ano_sel}"]
        input_ag_str = st.text_input(
            "Estoque Final dos Precatórios (AG) - R$:",
            value=str_inicial_ag,
            placeholder="Ex: 950.000,00",
            key=f"txt_f10_ag_dinamico_{ano_sel}_{sufixo_ag}_{ctr}"
        )
        
        # Input 2: Estoque Inicial dos Precatórios (AH)
        sufixo_ah = st.session_state[f"f10_ah_key_suffix_{ano_sel}"]
        input_ah_str = st.text_input(
            "Estoque Inicial dos Precatórios (AH) - R$:",
            value=str_inicial_ah,
            placeholder="Ex: 1.000.000,00",
            key=f"txt_f10_ah_dinamico_{ano_sel}_{sufixo_ah}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do indicador AI
        try:
            v_ag = limpa_conversao_monetaria(input_ag_str)
            v_ah = max(limpa_conversao_monetaria(input_ah_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Indicador AI (Decimal Puro)
            AI = round(v_ag / v_ah, 4)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_ag == 0.0 and (dF10.get("link", "").strip() == ""):
                ptsF10 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS
                if AI <= 0.9000:
                    ptsF10 = 75.0
                    texto_resultado = "✅ REGULAR: Redução Ótima do Estoque (≤ 0,90)"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                elif 0.9000 < AI < 1.0000:
                    ptsF10 = ((AI - 1.0000) * (-1.0) / 0.1000) * 75.0
                    texto_resultado = "⚠️ ALERTA DE GRADUAÇÃO (Redução Parcial)"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else: # AI >= 1.0000
                    ptsF10 = 0.0
                    texto_resultado = "🚨 CRÍTICO: Estoque Mantido ou Aumentado (≥ 1,00)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                
                texto_pontuacao = f"{ptsF10:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_ag, v_ah = float_ag, float_ah
            AI = float_ag / max(float_ah, 0.01)
            ptsF10 = float(dF10.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF10:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF10 = st.text_area("Link/Evidência (F10 - Precatórios AUDESP):", value=dF10.get("link", ""), key=f"txt_f10_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Razão:</b> R$ {v_ag:,.2f} / R$ {v_ah:,.2f}<br>
        📊 <b>Resultado do Indicador (AI):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{AI:.4f}</code><br>
        ⚖️ <b>Situação do Estoque:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_ag:.2f}/{v_ah:.2f}"
    string_banco_salva = f"{float_ag:.2f}/{float_ah:.2f}"

    if string_banco_atual != string_banco_salva or lF10 != dF10["link"]:
        save_resp("F10", string_banco_atual, ptsF10, lF10)
        
        if f"{v_ag:.2f}" != f"{float_ag:.2f}":
            st.session_state[f"f10_ag_key_suffix_{ano_sel}"] += 1
        if f"{v_ah:.2f}" != f"{float_ah:.2f}":
            st.session_state[f"f10_ah_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F10", res_data)
    st.markdown('</div>', unsafe_allow_html=True)
        
    # F11 • Repasse de Duodécimos às Câmaras
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F11 • Repasse de Duodécimos às Câmaras (Valor Repassado / RCL)")
    st.write("**Razão entre as Transferências à Câmara e a Receita Corrente Líquida**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Percentual de Repasse | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Menor ou igual a 6,00% ($\le 6\%$) | ✅ 00 ponto (Sem penalidades / Regular) |
    | Maior que 6,00% ($> 6\%$) | 🚨 **REBAIXAR IEG-M PARA FAIXA C** (Nota Geral afetada) |
    """)
    st.caption("ℹ️ *Dados extraídos com base no item 'Transferências à Câmara dos Vereadores' do modelo de relatório de contas municipais do Sistema AUDESP.*")

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f11_rep_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f11_rep_key_suffix_{ano_sel}"] = 0
    if f"f11_rcl_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f11_rcl_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (Repasse/RCL)
    dF11 = res_data.get("F11", {"valor": "0.00/1.00", "pontos": 0, "link": ""})

    try:
        val_salvo_rep, val_salvo_rcl = dF11["valor"].split("/")
        float_rep = float(val_salvo_rep)
        float_rcl = float(val_salvo_rcl)
    except:
        float_rep, float_rcl = 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_rep = f"R$ {float_rep:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_rcl = f"R$ {float_rcl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Valor Repassado à Câmara
        sufixo_rep = st.session_state[f"f11_rep_key_suffix_{ano_sel}"]
        input_rep_str = st.text_input(
            "Transferências à Câmara dos Vereadores - R$:",
            value=str_inicial_rep,
            placeholder="Ex: 600.000,00",
            key=f"txt_f11_rep_dinamico_{ano_sel}_{sufixo_rep}_{ctr}"
        )
        
        # Input 2: Receita Corrente Líquida (RCL) - Reutilizada do contexto fiscal
        sufixo_rcl = st.session_state[f"f11_rcl_key_suffix_{ano_sel}"]
        input_rcl_str = st.text_input(
            "Receita Corrente Líquida (RCL) - R$ (F11):",
            value=str_inicial_rcl,
            placeholder="Ex: 10.000.000,00",
            key=f"txt_f11_rcl_dinamico_{ano_sel}_{sufixo_rcl}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do percentual
        try:
            v_rep = limpa_conversao_monetaria(input_rep_str)
            v_rcl = max(limpa_conversao_monetaria(input_rcl_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Percentual do Limite (Ex: 0.0540 = 5,40%)
            perc_repasse = round(v_rep / v_rcl, 4)
            perc_exibicao = perc_repasse * 100
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_rep == 0.0 and (dF11.get("link", "").strip() == ""):
                ptsF11 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ Verificar Limite"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS: Limite Constitucional de 6%
                if perc_repasse > 0.0600:
                    ptsF11 = 0.0
                    texto_resultado = "🚨 CRÍTICO: Limite Excedido! Rebaixar IEG-M para Faixa C"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                else:
                    ptsF11 = 0.0
                    texto_resultado = "✅ REGULAR: Dentro do teto constitucional de 6%"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                
                texto_pontuacao = "0,00 pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_rep, v_rcl = float_rep, float_rcl
            perc_exibicao = (float_rep / max(float_rcl, 0.01)) * 100
            ptsF11 = float(dF11.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF11:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF11 = st.text_area("Link/Evidência (F11 - Duodécimo Câmara):", value=dF11.get("link", ""), key=f"txt_f11_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo do Repasse:</b> (R$ {v_rep:,.2f} / R$ {v_rcl:,.2f}) * 100<br>
        📊 <b>Percentual Apurado:</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{perc_exibicao:.2f}%</code> (Limite: 6,00%)<br>
        ⚖️ <b>Situação Constitucional:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_rep:.2f}/{v_rcl:.2f}"
    string_banco_salva = f"{float_rep:.2f}/{float_rcl:.2f}"

    if string_banco_atual != string_banco_salva or lF11 != dF11["link"]:
        save_resp("F11", string_banco_atual, ptsF11, lF11)
        
        if f"{v_rep:.2f}" != f"{float_rep:.2f}":
            st.session_state[f"f11_rep_key_suffix_{ano_sel}"] += 1
        if f"{v_rcl:.2f}" != f"{float_rcl:.2f}":
            st.session_state[f"f11_rcl_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F11", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F12 • Pontualidade na Prestação de Contas
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F12 • Pontualidade na Prestação de Contas")
    st.write("**Cumprimento dos prazos de envio de Atas, Pareceres, Balancetes, Mapas de Precatórios e Conciliações**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Situação da Entrega | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Encaminhou no prazo | ✅ 50 pontos (Pontuação Máxima) |
    | Encaminhou fora do prazo | ⚠️ 25 pontos (Penalidade Parcial) |
    | Não encaminhou | 🚨 00 ponto (Sem pontuação) |
    """)
    st.caption("ℹ️ *Informações extraídas do Sistema AUDESP – Relatório de Situação de Entrega.*")

    # Carrega ou inicializa a string persistida no banco contendo o status salvo
    dF12 = res_data.get("F12", {"valor": "Aguardando preenchimento...", "pontos": 0, "link": ""})
    val_salvo_status = dF12["valor"]

    c1, c2 = st.columns([1, 2])

    with c1:
        # Mapeamento de opções do Audesp
        opcoes_status = [
            "Aguardando preenchimento...",
            "Encaminhou no prazo",
            "Encaminhou fora do prazo",
            "Não encaminhou"
        ]
        
        # Define o índice inicial com base no que veio do banco de dados
        try:
            idx_inicial = opcoes_status.index(val_salvo_status)
        except ValueError:
            idx_inicial = 0

        # Input: Selectbox para escolha da situação observada no relatório
        status_selecionado = st.selectbox(
            "Situação da entrega dos documentos no AUDESP:",
            options=opcoes_status,
            index=idx_inicial,
            key=f"sb_f12_status_{ano_sel}_{ctr}"
        )

        # 🧮 MOTOR DE REGRAS: Aplicação direta da pontuação por status
        if status_selecionado == "Encaminhou no prazo":
            ptsF12 = 50.0
            texto_resultado = "✅ REGULAR: Documentação enviada tempestivamente"
            estilo_status = "color: #16a34a; font-weight: bold;"
            texto_pontuacao = "50,00 pontos"
        elif status_selecionado == "Encaminhou fora do prazo":
            ptsF12 = 25.0
            texto_resultado = "⚠️ ALERTA: Remessa em atraso apurada no relatório"
            estilo_status = "color: #d97706; font-weight: bold;"
            texto_pontuacao = "25,00 pontos"
        elif status_selecionado == "Não encaminhou":
            ptsF12 = 0.0
            texto_resultado = "🚨 CRÍTICO: Ausência de prestação de contas obrigatória"
            estilo_status = "color: #dc2626; font-weight: bold;"
            texto_pontuacao = "0,00 pontos"
        else:
            ptsF12 = 0.0
            texto_resultado = "Aguardando seleção do status..."
            estilo_status = "color: #64748b;"
            texto_pontuacao = "⏳ 0,00 pontos"

    with c2:
        lF12 = st.text_area("Link/Evidência (F12 - Situação de Entrega AUDESP):", value=dF12.get("link", ""), key=f"txt_f12_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Critério Avaliado:</b> Atas, Pareceres, Balancetes, Precatórios, Conciliações e Questionário IEG-M<br>
        ⚖️ <b>Status da Prestação:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """, unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    if status_selecionado != val_salvo_status or lF12 != dF12["link"]:
        save_resp("F12", status_selecionado, ptsF12, lF12)
        st.rerun()

    bloco_comentarios("F12", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F13 • Dívida Ativa: Percentual de Recebimento
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F13 • Dívida Ativa: Percentual de Recebimento (AL)")
    st.write("**Nível de recebimento da dívida em relação ao estoque inicial**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Resultado do Índice $AL$ | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Igual a 0 ($AL = 0$) | 🚨 00 ponto (Sem arrecadação) |
    | Entre 0,0 e 0,1 ($> 0,0$ e $< 0,1$) | ⚠️ Graduação entre 0 e 50 pontos |
    | Maior ou igual a 0,10 ($\ge 0,10$) | ✅ 50 pontos (Arrecadação Excelente) |
    """)
    st.caption("ℹ️ *Dados extraídos do Relatório de Análises Anuais Eletrônicas do Sistema AUDESP.*")

    # 📝 Memória de cálculo oficial fornecida
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo Intermediário:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 0,00 e menores que 0,10:</b> A graduação será distribuída igualitariamente no intervalo através da fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">(AL / 0,10) * 50</code> <br><i>Exemplo: se AL = 0,0500 (5% de recebimento), a nota do indicador será exatamente 25,00 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f13_rec_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f13_rec_key_suffix_{ano_sel}"] = 0
    if f"f13_est_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f13_est_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (Arrecadado/Estoque)
    dF13 = res_data.get("F13", {"valor": "0.00/1.00", "pontos": 0, "link": ""})

    try:
        val_salvo_rec, val_salvo_est = dF13["valor"].split("/")
        float_rec = float(val_salvo_rec)
        float_est = float(val_salvo_est)
    except:
        float_rec, float_est = 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_rec = f"R$ {float_rec:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_est = f"R$ {float_est:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Valor Recebido da Dívida Ativa
        sufixo_rec = st.session_state[f"f13_rec_key_suffix_{ano_sel}"]
        input_rec_str = st.text_input(
            "Valor Arrecadado de Dívida Ativa - R$:",
            value=str_inicial_rec,
            placeholder="Ex: 50.000,00",
            key=f"txt_f13_rec_dinamico_{ano_sel}_{sufixo_rec}_{ctr}"
        )
        
        # Input 2: Estoque Inicial da Dívida Ativa
        sufixo_est = st.session_state[f"f13_est_key_suffix_{ano_sel}"]
        input_est_str = st.text_input(
            "Estoque Inicial da Dívida Ativa - R$:",
            value=str_inicial_est,
            placeholder="Ex: 1.000.000,00",
            key=f"txt_f13_est_dinamico_{ano_sel}_{sufixo_est}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do indicador AL
        try:
            v_rec = limpa_conversao_monetaria(input_rec_str)
            v_est = max(limpa_conversao_monetaria(input_est_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Indicador AL (Decimal Puro)
            AL = round(v_rec / v_est, 4)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_rec == 0.0 and (dF13.get("link", "").strip() == ""):
                ptsF13 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS
                if AL == 0.0000:
                    ptsF13 = 0.0
                    texto_resultado = "🚨 CRÍTICO: Nenhuma arrecadação apurada (= 0,00)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                elif 0.0000 < AL < 0.1000:
                    # Aplicação da fórmula (AL / 0,10) * 50
                    ptsF13 = (AL / 0.1000) * 50.0
                    texto_resultado = "⚠️ ALERTA DE GRADUAÇÃO (Recuperação Intermediária)"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else: # AL >= 0.1000
                    ptsF13 = 50.0
                    texto_resultado = "✅ REGULAR: Índice de recebimento adequado (≥ 10%)"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                
                texto_pontuacao = f"{ptsF13:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_rec, v_est = float_rec, float_est
            AL = float_rec / max(float_est, 0.01)
            ptsF13 = float(dF13.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF13:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF13 = st.text_area("Link/Evidência (F13 - Dívida Ativa AUDESP):", value=dF13.get("link", ""), key=f"txt_f13_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Razão:</b> R$ {v_rec:,.2f} / R$ {v_est:,.2f}<br>
        📊 <b>Resultado do Indicador (AL):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{AL:.4f}</code> ({AL*100:.2f}% de recebimento)<br>
        ⚖️ <b>Situação da Arrecadação:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_rec:.2f}/{v_est:.2f}"
    string_banco_salva = f"{float_rec:.2f}/{float_est:.2f}"

    if string_banco_atual != string_banco_salva or lF13 != dF13["link"]:
        save_resp("F13", string_banco_atual, ptsF13, lF13)
        
        if f"{v_rec:.2f}" != f"{float_rec:.2f}":
            st.session_state[f"f13_rec_key_suffix_{ano_sel}"] += 1
        if f"{v_est:.2f}" != f"{float_est:.2f}":
            st.session_state[f"f13_est_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F13", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F14 • Dívida Ativa: Percentual de Cancelamento
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F14 • Dívida Ativa: Percentual de Cancelamento (AM)")
    st.write("**Nível de cancelamento da dívida em relação ao estoque inicial**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Resultado do Índice $AM$ | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Igual a 0 ($AM = 0$) | ✅ 50 pontos (Pontuação Máxima) |
    | Entre 0,0 e 0,1 ($> 0,0$ e $< 0,1$) | ⚠️ Graduação entre 50 e 0 pontos |
    | Maior ou igual a 0,10 ($\ge 0,10$) | 🚨 00 ponto (Cancelamento Excessivo) |
    """)
    st.caption("ℹ️ *Dados extraídos do Relatório de Análises Anuais Eletrônicas do Sistema AUDESP.*")

    # 📝 Memória de cálculo oficial fornecida
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional Regressiva no Intervalo:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 0,00 e menores que 0,10:</b> A graduação decrescerá igualitariamente no intervalo através da fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">((AM – 0,10) * (-1) / 0,10) * 50</code> <br><i>Exemplo: se AM = 0,0500 (5% de cancelamento), a nota do indicador será exatamente 25,00 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f14_can_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f14_can_key_suffix_{ano_sel}"] = 0
    if f"f14_est_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f14_est_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (Cancelado/Estoque)
    dF14 = res_data.get("F14", {"valor": "0.00/1.00", "pontos": 50, "link": ""})

    try:
        val_salvo_can, val_salvo_est = dF14["valor"].split("/")
        float_can = float(val_salvo_can)
        float_est = float(val_salvo_est)
    except:
        float_can, float_est = 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_can = f"R$ {float_can:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_est = f"R$ {float_est:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Valor Cancelado da Dívida Ativa
        sufixo_can = st.session_state[f"f14_can_key_suffix_{ano_sel}"]
        input_can_str = st.text_input(
            "Valor Cancelado de Dívida Ativa - R$:",
            value=str_inicial_can,
            placeholder="Ex: 10.000,00",
            key=f"txt_f14_can_dinamico_{ano_sel}_{sufixo_can}_{ctr}"
        )
        
        # Input 2: Estoque Inicial da Dívida Ativa
        sufixo_est = st.session_state[f"f14_est_key_suffix_{ano_sel}"]
        input_est_str = st.text_input(
            "Estoque Inicial da Dívida Ativa - R$ (F14):",
            value=str_inicial_est,
            placeholder="Ex: 1.000.000,00",
            key=f"txt_f14_est_dinamico_{ano_sel}_{sufixo_est}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do indicador AM
        try:
            v_can = limpa_conversao_monetaria(input_can_str)
            v_est = max(limpa_conversao_monetaria(input_est_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Indicador AM (Decimal Puro)
            AM = round(v_can / v_est, 4)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO: Se o cancelamento estiver zerado e sem link, não força 50 automático antes do preenchimento
            if v_can == 0.0 and (dF14.get("link", "").strip() == ""):
                ptsF14 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS
                if AM == 0.0000:
                    ptsF14 = 50.0
                    texto_resultado = "✅ EXCELENTE: Nenhum cancelamento efetuado (= 0,00)"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                elif 0.0000 < AM < 0.1000:
                    # Aplicação exata da fórmula ((AM - 0.10) * (-1) / 0.10) * 50
                    ptsF14 = ((AM - 0.1000) * (-1.0) / 0.1000) * 50.0
                    texto_resultado = "⚠️ ALERTA DE GRADUAÇÃO (Baixa Parcial do Estoque)"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else: # AM >= 0.1000
                    ptsF14 = 0.0
                    texto_resultado = "🚨 CRÍTICO: Índice de cancelamento muito elevado (≥ 10%)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                
                texto_pontuacao = f"{ptsF14:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_can, v_est = float_can, float_est
            AM = float_can / max(float_est, 0.01)
            ptsF14 = float(dF14.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF14:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF14 = st.text_area("Link/Evidência (F14 - Cancelamento Dívida Ativa):", value=dF14.get("link", ""), key=f"txt_f14_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Razão:</b> R$ {v_can:,.2f} / R$ {v_est:,.2f}<br>
        📊 <b>Resultado do Indicador (AM):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{AM:.4f}</code> ({AM*100:.2f}% de cancelamento)<br>
        ⚖️ <b>Situação do Estoque:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_can:.2f}/{v_est:.2f}"
    string_banco_salva = f"{float_can:.2f}/{float_est:.2f}"

    if string_banco_atual != string_banco_salva or lF14 != dF14["link"]:
        save_resp("F14", string_banco_atual, ptsF14, lF14)
        
        if f"{v_can:.2f}" != f"{float_can:.2f}":
            st.session_state[f"f14_can_key_suffix_{ano_sel}"] += 1
        if f"{v_est:.2f}" != f"{float_est:.2f}":
            st.session_state[f"f14_est_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F14", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F15 • Alertas do Sistema AUDESP
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F15 • Alertas do Sistema AUDESP")
    st.write("**Quantidade total de alertas gerados pelo sistema eletrônico no exercício**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Quantidade de Alertas | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Menor ou igual a 20 ($\le 20$) | ✅ 25 pontos (Pontuação Máxima) |
    | Entre 21 e 40 ($> 20$ e $< 41$) | ⚠️ 10 pontos (Atenção / Nota Parcial) |
    | Maior ou igual a 41 ($\ge 41$) | 🚨 00 ponto (Volume Crítico de Alertas) |
    """)
    st.caption("ℹ *Informações extraídas do módulo de controle do Sistema AUDESP.*")

    # Carrega ou inicializa a string persistida no banco contendo o valor numérico
    dF15 = res_data.get("F15", {"valor": "0", "pontos": 0, "link": ""})
    
    try:
        val_salvo_alertas = int(float(dF15["valor"]))
    except:
        val_salvo_alertas = 0

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input: Número inteiro para contagem absoluta dos alertas gerados
        qtd_alertas = st.number_input(
            "Quantidade total de alertas gerados no ano:",
            min_value=0,
            max_value=9999,
            value=val_salvo_alertas,
            step=1,
            format="%d",
            key=f"num_f15_alertas_{ano_sel}_{ctr}"
        )

        # 🧮 MOTOR DE REGRAS: Avaliação por faixas discretas de tolerância fiscal
        if qtd_alertas <= 20:
            ptsF15 = 25.0
            texto_resultado = f"✅ ADEQUADO: Baixo volume de alertas ({qtd_alertas})"
            estilo_status = "color: #16a34a; font-weight: bold;"
            texto_pontuacao = "25,00 pontos"
        elif 20 < qtd_alertas < 41:
            ptsF15 = 10.0
            texto_resultado = f"⚠️ ATENÇÃO: Volume moderado de inconformidades ({qtd_alertas})"
            estilo_status = "color: #d97706; font-weight: bold;"
            texto_pontuacao = "10,00 pontos"
        else: # qtd_alertas >= 41
            ptsF15 = 0.0
            texto_resultado = f"🚨 EXCESSO: Alto índice de ocorrências sistêmicas ({qtd_alertas})"
            estilo_status = "color: #dc2626; font-weight: bold;"
            texto_pontuacao = "0,00 pontos"

    with c2:
        lF15 = st.text_area("Link/Evidência (F15 - Painel de Alertas AUDESP):", value=dF15.get("link", ""), key=f"txt_f15_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Métrica Avaliada:</b> Concentração de inconformidades contábeis e de gestão<br>
        ⚖️ <b>Situação Institucional:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """, unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    if qtd_alertas != val_salvo_alertas or lF15 != dF15["link"]:
        save_resp("F15", str(qtd_alertas), ptsF15, lF15)
        st.rerun()

    bloco_comentarios("F15", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F16 • Balancetes Rejeitados
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F16 • Balancetes Rejeitados")
    st.write("**Quantidade total de balancetes mensais rejeitados no exercício**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Balancetes Rejeitados | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Menor ou igual a 1 ($\le 1$) | ✅ 25 pontos (Pontuação Máxima) |
    | Entre 2 e 17 ($> 1$ e $< 18$) | ⚠️ 10 pontos (Atenção / Nota Parcial) |
    | Maior ou igual a 18 ($\ge 18$) | 🚨 00 ponto (Volume Crítico de Rejeições) |
    """)
    st.caption("ℹ️ *Informações apuradas com base nas notificações de rejeição do Sistema AUDESP.*")

    # Carrega ou inicializa a string persistida no banco contendo o valor numérico
    dF16 = res_data.get("F16", {"valor": "0", "pontos": 0, "link": ""})
    
    try:
        val_salvo_rejeitados = int(float(dF16["valor"]))
    except:
        val_salvo_rejeitados = 0

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input: Número inteiro para contagem absoluta das rejeições de balancetes
        qtd_rejeitados = st.number_input(
            "Quantidade de balancetes rejeitados no ano:",
            min_value=0,
            max_value=120,  # Margem segura considerando múltiplos órgãos/consórcios
            value=val_salvo_rejeitados,
            step=1,
            format="%d",
            key=f"num_f16_rejeitados_{ano_sel}_{ctr}"
        )

        # 🧮 MOTOR DE REGRAS: Avaliação por faixas de corte descritas
        if qtd_rejeitados <= 1:
            ptsF16 = 25.0
            texto_resultado = f"✅ ADEQUADO: Índice de rejeição mínimo ({qtd_rejeitados})"
            estilo_status = "color: #16a34a; font-weight: bold;"
            texto_pontuacao = "25,00 pontos"
        elif 1 < qtd_rejeitados < 18:
            ptsF16 = 10.0
            texto_resultado = f"⚠️ ATENÇÃO: Rejeições recorrentes identificadas ({qtd_rejeitados})"
            estilo_status = "color: #d97706; font-weight: bold;"
            texto_pontuacao = "10,00 pontos"
        else: # qtd_rejeitados >= 18
            ptsF16 = 0.0
            texto_resultado = f"🚨 EXCESSO: Volume crítico de inconsistências contábeis ({qtd_rejeitados})"
            estilo_status = "color: #dc2626; font-weight: bold;"
            texto_pontuacao = "0,00 pontos"

    with c2:
        lF16 = st.text_area("Link/Evidência (F16 - Histórico de Balancetes AUDESP):", value=dF16.get("link", ""), key=f"txt_f16_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Métrica Avaliada:</b> Qualidade e consistência das remessas contábeis mensais<br>
        ⚖️ <b>Situação Institucional:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """, unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    if qtd_rejeitados != val_salvo_rejeitados or lF16 != dF16["link"]:
        save_resp("F16", str(qtd_rejeitados), ptsF16, lF16)
        st.rerun()

    bloco_comentarios("F16", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F17 • Resultado Primário (Operacional)
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F17 • Resultado Primário (Operacional) [RP = RR - DL]")
    st.write("**Mede a capacidade do município de reduzir seu endividamento estrutural**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Resultado Primário ($RP$) | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Acima de ZERO ($RP > 0$) | ✅ 75 pontos (Superávit Primário) |
    | Igual a ZERO ($RP = 0$) | ⚠️ 40 pontos (Equilíbrio Limite) |
    | Abaixo de ZERO ($RP < 0$) | 🚨 00 ponto (Déficit Primário) |
    """)
    st.caption("ℹ️ *Dados extraídos da linha 'RESULTADO PRIMÁRIO (VIII-XVII)' do Demonstrativo do Resultado Primário do 6º bimestre (Item GF20 - AUDESP).*")

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f17_rr_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f17_rr_key_suffix_{ano_sel}"] = 0
    if f"f17_dl_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f17_dl_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (Receitas/Despesas)
    dF17 = res_data.get("F17", {"valor": "0.00/0.00", "pontos": 40, "link": ""})
    
    try:
        val_salvo_rr, val_salvo_dl = dF17["valor"].split("/")
        float_rr = float(val_salvo_rr)
        float_dl = float(val_salvo_dl)
    except:
        float_rr, float_dl = 0.0, 0.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_rr = f"R$ {float_rr:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_dl = f"R$ {float_dl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Receitas Realizadas (RR)
        sufixo_rr = st.session_state[f"f17_rr_key_suffix_{ano_sel}"]
        input_rr_str = st.text_input(
            "Receitas Realizadas (RR) - R$:",
            value=str_inicial_rr,
            placeholder="Ex: 1.500.000,00",
            key=f"txt_f17_rr_dinamico_{ano_sel}_{sufixo_rr}_{ctr}"
        )
        
        # Input 2: Despesas Liquidadas (DL)
        sufixo_dl = st.session_state[f"f17_dl_key_suffix_{ano_sel}"]
        input_dl_str = st.text_input(
            "Despesas Liquidadas (DL) - R$:",
            value=str_inicial_dl,
            placeholder="Ex: 1.400.000,00",
            key=f"txt_f17_dl_dinamico_{ano_sel}_{sufixo_dl}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico por subtração
        try:
            v_rr = limpa_conversao_monetaria(input_rr_str)
            v_dl = limpa_conversao_monetaria(input_dl_str)
            
            # Cálculo matemático oficial: RP = RR - DL
            v_rp = round(v_rr - v_dl, 2)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_rr == 0.0 and v_dl == 0.0 and (dF17.get("link", "").strip() == ""):
                ptsF17 = 40.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "40,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS OFICIAL
                if v_rp > 0.00:
                    ptsF17 = 75.0
                    texto_resultado = "✅ SUPERÁVIT: Capacidade de redução do endividamento"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                elif v_rp == 0.00:
                    ptsF17 = 40.0
                    texto_resultado = "⚠️ EQUILÍBRIO: Receitas equivalentes às despesas liquidadas"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else: # v_rp < 0.00
                    ptsF17 = 0.0
                    texto_resultado = "🚨 DÉFICIT: Tendência de aumento do endividamento municipal"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                
                texto_pontuacao = f"{ptsF17:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_rr, v_dl = float_rr, float_dl
            v_rp = round(v_rr - v_dl, 2)
            ptsF17 = float(dF17.get("pontos", 40))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF17:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF17 = st.text_area("Link/Evidência (F17 - Demonstrativo Primário AUDESP):", value=dF17.get("link", ""), key=f"txt_f17_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    sinal_exibicao = "-" if v_rp < 0 else ""
    str_v_rp_formatado = f"{sinal_exibicao}R$ {abs(v_rp):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Fórmula (RP = RR - DL):</b> R$ {v_rr:,.2f} - R$ {v_dl:,.2f}<br>
        📊 <b>Resultado Primário Apurado (RP):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_v_rp_formatado}</code><br>
        ⚖ Rose <b>Situação Fiscal:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_rr:.2f}/{v_dl:.2f}"
    string_banco_salva = f"{float_rr:.2f}/{float_dl:.2f}"

    if string_banco_atual != string_banco_salva or lF17 != dF17["link"]:
        save_resp("F17", string_banco_atual, ptsF17, lF17)
        
        if f"{v_rr:.2f}" != f"{float_rr:.2f}":
            st.session_state[f"f17_rr_key_suffix_{ano_sel}"] += 1
        if f"{v_dl:.2f}" != f"{float_dl:.2f}":
            st.session_state[f"f17_dl_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F17", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F18 • Índice de Liquidez Imediata
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F18 • Índice de Liquidez Imediata [IL = D / PC]")
    st.write("**Verifica a capacidade de pagamento com recursos do ativo disponível**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Resultado do Índice $IL$ | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Maior ou igual a 1 ($IL \ge 1,0$) | ✅ 75 pontos (Pontuação Máxima) |
    | Entre 0,8 e 1 ($> 0,8$ e $< 1,0$) | ⚠️ Graduação proporcional entre 0 e 75 pontos |
    | Menor ou igual a 0,8 ($IL \le 0,8$) | 🚨 00 ponto (Capacidade Crítica) |
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

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f18_disp_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f18_disp_key_suffix_{ano_sel}"] = 0
    if f"f18_pc_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f18_pc_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (Disponível/Passivo Circulante)
    dF18 = res_data.get("F18", {"valor": "0.00/1.00", "pontos": 0, "link": ""})

    try:
        val_salvo_disp, val_salvo_pc = dF18["valor"].split("/")
        float_disp = float(val_salvo_disp)
        float_pc = float(val_salvo_pc)
    except:
        float_disp, float_pc = 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_disp = f"R$ {float_disp:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_pc = f"R$ {float_pc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Ativo Disponível (D)
        sufixo_disp = st.session_state[f"f18_disp_key_suffix_{ano_sel}"]
        input_disp_str = st.text_input(
            "Recursos do Ativo Disponível (D) - R$:",
            value=str_inicial_disp,
            placeholder="Ex: 81.000,00",
            key=f"txt_f18_disp_dinamico_{ano_sel}_{sufixo_disp}_{ctr}"
        )
        
        # Input 2: Passivo Circulante (PC)
        sufixo_pc = st.session_state[f"f18_pc_key_suffix_{ano_sel}"]
        input_pc_str = st.text_input(
            "Passivo Circulante (PC) - R$ (F18):",
            value=str_inicial_pc,
            placeholder="Ex: 100.000,00",
            key=f"txt_f18_pc_dinamico_{ano_sel}_{sufixo_pc}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do índice IL
        try:
            v_disp = limpa_conversao_monetaria(input_disp_str)
            v_pc = max(limpa_conversao_monetaria(input_pc_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Índice de Liquidez (Decimal Puro)
            IL = round(v_disp / v_pc, 4)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_disp == 0.0 and (dF18.get("link", "").strip() == ""):
                ptsF18 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS OFICIAL
                if IL >= 1.0000:
                    ptsF18 = 75.0
                    texto_resultado = "✅ ADEQUADO: Disponível cobre totalmente o Passivo Circulante"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                elif 0.8000 < IL < 1.0000:
                    # Aplicação exata da fórmula oficial: ((IL - 0.80) * 75) / 0.20
                    ptsF18 = ((IL - 0.8000) * 75.0) / 0.2000
                    texto_resultado = "⚠️ GRADUAÇÃO PROPORCIONAL: Cobertura parcial do passivo"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else: # IL <= 0.8000
                    ptsF18 = 0.0
                    texto_resultado = "🚨 CRÍTICO: Índice de liquidez imediata muito baixo (≤ 0,80)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                
                texto_pontuacao = f"{ptsF18:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_disp, v_pc = float_disp, float_pc
            IL = float_disp / max(float_pc, 0.01)
            ptsF18 = float(dF18.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF18:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF18 = st.text_area("Link/Evidência (F18 - Liquidez Imediata RAAE):", value=dF18.get("link", ""), key=f"txt_f18_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Razão:</b> R$ {v_disp:,.2f} / R$ {v_pc:,.2f}<br>
        📊 <b>Resultado do Indicador (IL):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{IL:.4f}</code><br>
        ⚖️ <b>Situação de Liquidez:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_disp:.2f}/{v_pc:.2f}"
    string_banco_salva = f"{float_disp:.2f}/{float_pc:.2f}"

    if string_banco_atual != string_banco_salva or lF18 != dF18["link"]:
        save_resp("F18", string_banco_atual, ptsF18, lF18)
        
        if f"{v_disp:.2f}" != f"{float_disp:.2f}":
            st.session_state[f"f18_disp_key_suffix_{ano_sel}"] += 1
        if f"{v_pc:.2f}" != f"{float_pc:.2f}":
            st.session_state[f"f18_pc_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F18", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

# F19 • Limite de Endividamento – Regra de Ouro
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F19 • Limite de Endividamento – Regra de Ouro [RO = OC - DC - AL]")
    st.write("**Verifica se as operações de crédito ultrapassaram o volume de despesas de capital**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Resultado da Regra de Ouro ($RO$) | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Menor ou igual a ZERO ($RO \le 0$) | ✅ 00 ponto (Regra Cumprida / Sem Penalidade) |
    | Maior que ZERO ($RO > 0$) | 🚨 **REBAIXA 1 FAIXA DO I-FISCAL** (Descumprimento Crítico) |
    """)
    st.caption("ℹ️ *Variáveis extraídas dos demonstrativos fiscais e balanços anuais consolidados do município.*")

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f19_oc_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f19_oc_key_suffix_{ano_sel}"] = 0
    if f"f19_dc_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f19_dc_key_suffix_{ano_sel}"] = 0
    if f"f19_al_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f19_al_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo o trio de valores (OC/DC/AL)
    dF19 = res_data.get("F19", {"valor": "0.00/0.00/0.00", "pontos": 0, "link": ""})

    try:
        val_salvo_oc, val_salvo_dc, val_salvo_al = dF19["valor"].split("/")
        float_oc = float(val_salvo_oc)
        float_dc = float(val_salvo_dc)
        float_al = float(val_salvo_al)
    except:
        float_oc, float_dc, float_al = 0.0, 0.0, 0.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_oc = f"R$ {float_oc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_dc = f"R$ {float_dc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_al = f"R$ {float_al:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Operações de Crédito (OC)
        sufixo_oc = st.session_state[f"f19_oc_key_suffix_{ano_sel}"]
        input_oc_str = st.text_input(
            "Operações de Crédito Realizadas (OC) - R$:",
            value=str_inicial_oc,
            placeholder="Ex: 500.000,00",
            key=f"txt_f19_oc_dinamico_{ano_sel}_{sufixo_oc}_{ctr}"
        )
        
        # Input 2: Despesas de Capital (DC)
        sufixo_dc = st.session_state[f"f19_dc_key_suffix_{ano_sel}"]
        input_dc_str = st.text_input(
            "Despesas de Capital Liquidadas (DC) - R$:",
            value=str_inicial_dc,
            placeholder="Ex: 600.000,00",
            key=f"txt_f19_dc_dinamico_{ano_sel}_{sufixo_dc}_{ctr}"
        )

        # Input 3: Autorizações Legislativas (AL)
        sufixo_al = st.session_state[f"f19_al_key_suffix_{ano_sel}"]
        input_al_str = st.text_input(
            "Autorizações por Maioria Absoluta (AL) - R$:",
            value=str_inicial_al,
            placeholder="Ex: 50.000,00",
            key=f"txt_f19_al_dinamico_{ano_sel}_{sufixo_al}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo da fórmula estrutural
        try:
            v_oc = limpa_conversao_monetaria(input_oc_str)
            v_dc = limpa_conversao_monetaria(input_dc_str)
            v_al = limpa_conversao_monetaria(input_al_str)
            
            # Execução matemática da fórmula: RO = OC - DC - AL
            v_ro = round(v_oc - v_dc - v_al, 2)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_oc == 0.0 and v_dc == 0.0 and v_al == 0.0 and (dF19.get("link", "").strip() == ""):
                ptsF19 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ Verificar Regra"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS
                if v_ro > 0.00:
                    ptsF19 = 0.0
                    texto_resultado = "🚨 CRÍTICO: Regra de Ouro Descumprida! Rebaixar 1 faixa do i-Fiscal"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                else:
                    ptsF19 = 0.0
                    texto_resultado = "✅ REGULAR: Operações de crédito compatíveis com os investimentos"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                
                texto_pontuacao = "0,00 pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_oc, v_dc, v_al = float_oc, float_dc, float_al
            v_ro = round(v_oc - v_dc - v_al, 2)
            ptsF19 = float(dF19.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF19:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF19 = st.text_area("Link/Evidência (F19 - Regra de Ouro Balanços):", value=dF19.get("link", ""), key=f"txt_f19_{ano_sel}_{ctr}", height=210)

    # Exibição do painel consolidador de métricas fiscais
    sinal_exibicao = "-" if v_ro < 0 else ""
    str_v_ro_formatado = f"{sinal_exibicao}R$ {abs(v_ro):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Fórmula (RO = OC - DC - AL):</b> R$ {v_oc:,.2f} - R$ {v_dc:,.2f} - R$ {v_al:,.2f}<br>
        📊 <b>Resultado da Regra (RO):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{str_v_ro_formatado}</code><br>
        ⚖️ <b>Situação Constitucional:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_oc:.2f}/{v_dc:.2f}/{v_al:.2f}"
    string_banco_salva = f"{float_oc:.2f}/{float_dc:.2f}/{float_al:.2f}"

    if string_banco_atual != string_banco_salva or lF19 != dF19["link"]:
        save_resp("F19", string_banco_atual, ptsF19, lF19)
        
        if f"{v_oc:.2f}" != f"{float_oc:.2f}":
            st.session_state[f"f19_oc_key_suffix_{ano_sel}"] += 1
        if f"{v_dc:.2f}" != f"{float_dc:.2f}":
            st.session_state[f"f19_dc_key_suffix_{ano_sel}"] += 1
        if f"{v_al:.2f}" != f"{float_al:.2f}":
            st.session_state[f"f19_al_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F19", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

# F20 • Percentual da Taxa de Investimento
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F20 • Percentual da Taxa de Investimento [(L + F) / M = N]")
    st.write("**Mede a taxa de investimento real líquida em relação à receita total arrecadada**")

    # Tabela de Regras de Pontuação
    st.markdown(r"""
    | Resultado do Índice $N$ | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Maior ou igual a 0,15 ($N \ge 0,15$) | ✅ 50 pontos (Pontuação Máxima) |
    | Entre 0,02 e 0,15 ($> 0,02$ e $< 0,15$) | ⚠️ Graduação proporcional entre 0 e 50 pontos |
    | Menor ou igual a 0,02 ($N \le 0,02$) | 🚨 00 ponto (Baixo Índice de Investimento) |
    """)
    st.caption("ℹ️ *Despesa classificada no elemento '44 - Investimentos' (Portaria MPOG nº 163/2001) via Sistema AUDESP.*")

    # 📝 Memória de cálculo oficial fornecida
    st.markdown("""
    <div style="background-color: #f8fafc; padding: 12px; border-radius: 4px; border-left: 3px solid #64748b; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px;">📊 <b>Regra de Distribuição Proporcional no Intervalo:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px;">
            <li><b>Para resultados maiores que 0,02 e menores que 0,15:</b> A graduação será distribuída utilizando a fórmula: <br><code style="background-color: #e2e8f0; padding: 2px 5px;">P = ((N – 0,02) / 0,13) * 50</code> <br><i>Exemplo: se N = 0,1000 (10% de taxa), a nota do indicador será exatamente 30,77 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f20_l_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f20_l_key_suffix_{ano_sel}"] = 0
    if f"f20_f_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f20_f_key_suffix_{ano_sel}"] = 0
    if f"f20_m_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f20_m_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo o trio de valores (L/F/M)
    dF20 = res_data.get("F20", {"valor": "0.00/0.00/1.00", "pontos": 0, "link": ""})

    try:
        val_salvo_l, val_salvo_f, val_salvo_m = dF20["valor"].split("/")
        float_l = float(val_salvo_l)
        float_f = float(val_salvo_f)
        float_m = float(val_salvo_m)
    except:
        float_l, float_f, float_m = 0.0, 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_l = f"R$ {float_l:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_f = f"R$ {float_f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_m = f"R$ {float_m:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Despesa Liquidada Total - Grupo 44 (L)
        sufixo_l = st.session_state[f"f20_l_key_suffix_{ano_sel}"]
        input_l_str = st.text_input(
            "Despesa Liquidada Total - Cat. 44 (L) - R$:",
            value=str_inicial_l,
            placeholder="Ex: 90.000,00",
            key=f"txt_f20_l_dinamico_{ano_sel}_{sufixo_l}_{ctr}"
        )
        
        # Input 2: Liquidação de Restos a Pagar Não Processados (F)
        sufixo_f = st.session_state[f"f20_f_key_suffix_{ano_sel}"]
        input_f_str = st.text_input(
            "Liq. Restos a Pagar Não Processados (F) - R$:",
            value=str_inicial_f,
            placeholder="Ex: 10.000,00",
            key=f"txt_f20_f_dinamico_{ano_sel}_{sufixo_f}_{ctr}"
        )

        # Input 3: Receita Total Arrecadada (M)
        sufixo_m = st.session_state[f"f20_m_key_suffix_{ano_sel}"]
        input_m_str = st.text_input(
            "Receita Total Arrecadada no Período (M) - R$:",
            value=str_inicial_m,
            placeholder="Ex: 1.000.000,00",
            key=f"txt_f20_m_dinamico_{ano_sel}_{sufixo_m}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico da Taxa de Investimento
        try:
            v_l = limpa_conversao_monetaria(input_l_str)
            v_f = limpa_conversao_monetaria(input_f_str)
            v_m = max(limpa_conversao_monetaria(input_m_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Índice N (Decimal Puro)
            N = round((v_l + v_f) / v_m, 4)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_l == 0.0 and v_f == 0.0 and (dF20.get("link", "").strip() == ""):
                ptsF20 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS OFICIAL
                if N >= 0.1500:
                    ptsF20 = 50.0
                    texto_resultado = "✅ EXCELENTE: Alto percentual de aplicação em investimentos"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                elif 0.0200 < N < 0.1500:
                    # Aplicação exata da fórmula oficial: ((N - 0.02) / 0.13) * 50
                    ptsF20 = ((N - 0.0200) / 0.1300) * 50.0
                    texto_resultado = "⚠️ GRADUAÇÃO PROPORCIONAL: Nível intermediário de investimentos"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else: # N <= 0.0200
                    ptsF20 = 0.0
                    texto_resultado = "🚨 CRÍTICO: Índice de investimento igual ou abaixo do limite de tolerância (≤ 2%)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                
                texto_pontuacao = f"{ptsF20:.2f} pontos"
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_l, v_f, v_m = float_l, float_f, float_m
            N = (float_l + float_f) / max(float_m, 0.01)
            ptsF20 = float(dF20.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF20:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF20 = st.text_area("Link/Evidência (F20 - Taxa de Investimento AUDESP):", value=dF20.get("link", ""), key=f"txt_f20_{ano_sel}_{ctr}", height=210)

    # Exibição do painel consolidador de métricas fiscais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Equação [(L + F) / M]:</b> (R$ {v_l:,.2f} + R$ {v_f:,.2f}) / R$ {v_m:,.2f}<br>
        📊 <b>Resultado da Taxa (N):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{N:.4f}</code> ({N*100:.2f}% de aplicação)<br>
        ⚖️ <b>Situação de Alocação:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #1e40af;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_l:.2f}/{v_f:.2f}/{v_m:.2f}"
    string_banco_salva = f"{float_l:.2f}/{float_f:.2f}/{float_m:.2f}"

    if string_banco_atual != string_banco_salva or lF20 != dF20["link"]:
        save_resp("F20", string_banco_atual, ptsF20, lF20)
        
        if f"{v_l:.2f}" != f"{float_l:.2f}":
            st.session_state[f"f20_l_key_suffix_{ano_sel}"] += 1
        if f"{v_f:.2f}" != f"{float_f:.2f}":
            st.session_state[f"f20_f_key_suffix_{ano_sel}"] += 1
        if f"{v_m:.2f}" != f"{float_m:.2f}":
            st.session_state[f"f20_m_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F20", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

# F21 • Relação entre Despesas Correntes e Receitas Correntes
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F21 • Relação Despesas Correntes / Receitas Correntes [LDC = DC / RC]")
    st.write("**Verifica o cumprimento do limite constitucional de gastos (Art. 167-A da CF)**")

    # Tabela de Regras de Pontuação (Penalidades)
    st.markdown(r"""
    | Resultado do Índice $LDC$ | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Menor ou igual a 0,85 ($LDC \le 0,85$) | ✅ 00 ponto (Situação Confortável / Sem Penalidade) |
    | Entre 0,85 e 0,95 ($> 0,85$ e $\le 0,95$) | ⚠️ Graduação proporcional entre 0 e -50 pontos (Perda) |
    | Maior que 0,95 ($LDC > 0,95$) | 🚨 -50,00 pontos (Penalidade Máxima por Estouro de Teto) |
    """)
    st.caption("ℹ️ *Dados consolidados (Prefeitura, Câmara e Autarquias) com base no Relatório de Instrução AUDESP, item GF56.*")

    # 📝 Memória de cálculo oficial fornecida
    st.markdown("""
    <div style="background-color: #fff5f5; padding: 12px; border-radius: 4px; border-left: 3px solid #e53e3e; margin-bottom: 15px;">
        <p style="margin-bottom: 8px; font-size: 13px; color: #9b2c2c;">📊 <b>Regra de Penalização Proporcional no Intervalo:</b></p>
        <ul style="font-size: 13px; margin-left: 15px; padding-left: 0px; color: #9b2c2c;">
            <li><b>Para resultados maiores que 0,85 e menores ou iguais a 0,95:</b> A perda de pontos será distribuída utilizando a fórmula: <br><code style="background-color: #fed7d7; padding: 2px 5px; color: #9b2c2c;">P = ((LDC – 0,85) / 0,10) * (-50)</code> <br><i>Exemplo: se LDC = 0,9300 (93% de comprometimento), a nota do indicador será exatamente de -40,00 pontos.</i></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f21_dc_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f21_dc_key_suffix_{ano_sel}"] = 0
    if f"f21_rc_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f21_rc_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (Despesas/Receitas)
    dF21 = res_data.get("F21", {"valor": "0.00/1.00", "pontos": 0, "link": ""})

    try:
        val_salvo_dc, val_salvo_rc = dF21["valor"].split("/")
        float_dc = float(val_salvo_dc)
        float_rc = float(val_salvo_rc)
    except:
        float_dc, float_rc = 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_dc = f"R$ {float_dc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_rc = f"R$ {float_rc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Despesa Corrente Liquidada (DC)
        sufixo_dc = st.session_state[f"f21_dc_key_suffix_{ano_sel}"]
        input_dc_str = st.text_input(
            "Despesa Corrente Liquidada (DC) - R$:",
            value=str_inicial_dc,
            placeholder="Ex: 850.000,00",
            key=f"txt_f21_dc_dinamico_{ano_sel}_{sufixo_dc}_{ctr}"
        )
        
        # Input 2: Receita Corrente Arrecadada (RC)
        sufixo_rc = st.session_state[f"f21_rc_key_suffix_{ano_sel}"]
        input_rc_str = st.text_input(
            "Receita Corrente Total (RC) - R$ (F21):",
            value=str_inicial_rc,
            placeholder="Ex: 1.000.000,00",
            key=f"txt_f21_rc_dinamico_{ano_sel}_{sufixo_rc}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do índice LDC e penalidades
        try:
            v_dc = limpa_conversao_monetaria(input_dc_str)
            v_rc = max(limpa_conversao_monetaria(input_rc_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Índice LDC (Decimal Puro)
            LDC = round(v_dc / v_rc, 4)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_dc == 0.0 and (dF21.get("link", "").strip() == ""):
                ptsF21 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS (LÓGICA DE PENALIZAÇÃO)
                if LDC <= 0.8500:
                    ptsF21 = 0.0
                    texto_resultado = "✅ ADEQUADO: Gastos correntes equilibrados e sob controle"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                elif 0.8500 < LDC <= 0.9500:
                    # Aplicação exata da fórmula paramétrica de decréscimo: ((LDC - 0.85) / 0.10) * (-50)
                    ptsF21 = round(((LDC - 0.8500) / 0.1000) * (-50.0), 2)
                    texto_resultado = "⚠️ ALERTA: Próximo ao limite prudencial (Incidência de Penalidade)"
                    estilo_status = "color: #d97706; font-weight: bold;"
                else: # LDC > 0.9500
                    ptsF21 = -50.0
                    texto_resultado = "🚨 CRÍTICO: Violação do teto do Art. 167-A da CF (> 95%)"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                
                sinal_pontos = "" if ptsF21 >= 0 else " "
                texto_pontuacao = f"{sinal_pontos}{ptsF21:.2f} pontos".replace(".", ",")
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_dc, v_rc = float_dc, float_rc
            LDC = float_dc / max(float_rc, 0.01)
            ptsF21 = float(dF21.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF21:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF21 = st.text_area("Link/Evidência (F21 - Relação Corrente AUDESP):", value=dF21.get("link", ""), key=f"txt_f21_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Razão (DC / RC):</b> R$ {v_dc:,.2f} / R$ {v_rc:,.2f}<br>
        📊 <b>Resultado do Indicador (LDC):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{LDC:.4f}</code> ({LDC*100:.2f}% de comprometimento)<br>
        ⚖️ <b>Enquadramento Legal:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Glosa/Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #dc2626;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_dc:.2f}/{v_rc:.2f}"
    string_banco_salva = f"{float_dc:.2f}/{float_rc:.2f}"

    if string_banco_atual != string_banco_salva or lF21 != dF21["link"]:
        save_resp("F21", string_banco_atual, ptsF21, lF21)
        
        if f"{v_dc:.2f}" != f"{float_dc:.2f}":
            st.session_state[f"f21_dc_key_suffix_{ano_sel}"] += 1
        if f"{v_rc:.2f}" != f"{float_rc:.2f}":
            st.session_state[f"f21_rc_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F21", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

    # F22 • Liquidez dos Restos a Pagar
    st.markdown('<div class="quesito-card">', unsafe_allow_html=True)
    st.subheader("F22 • Liquidez dos Restos a Pagar [LRP = RPA / D]")
    st.write("**Mede a capacidade de pagamento do estoque de restos a pagar com base na disponibilidade de caixa**")

    # Tabela de Regras de Pontuação (Penalidades)
    st.markdown(r"""
    | Resultado do Índice $LRP$ | Impacto / Pontuação do Indicador |
    | :--- | :--- |
    | Menor ou igual a 1 ($LRP \le 1$) | ✅ 00 ponto (Cobertura de Caixa Suficiente / Sem Penalidade) |
    | Maior que 1 ($LRP > 1$) | 🚨 -5,00 pontos (Caixa Insuficiente para Cobrir Restos a Pagar) |
    """)
    st.caption("ℹ️ *Variáveis extraídas do Relatório de Análises Anuais Eletrônicas (RAAE) e do Relatório de Instrução (RI).*")

    # Inicializa os sufixos de controle no session_state para gerenciar o cache de forma isolada
    if f"f22_rpa_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f22_rpa_key_suffix_{ano_sel}"] = 0
    if f"f22_d_key_suffix_{ano_sel}" not in st.session_state:
        st.session_state[f"f22_d_key_suffix_{ano_sel}"] = 0

    # Carrega ou inicializa a string persistida no banco contendo a dupla de valores (RPA/D)
    dF22 = res_data.get("F22", {"valor": "0.00/1.00", "pontos": 0, "link": ""})

    try:
        val_salvo_rpa, val_salvo_d = dF22["valor"].split("/")
        float_rpa = float(val_salvo_rpa)
        float_d = float(val_salvo_d)
    except:
        float_rpa, float_d = 0.0, 1.0

    # Converte os números salvos na máscara brasileira de apresentação monetária (R$)
    str_inicial_rpa = f"R$ {float_rpa:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    str_inicial_d = f"R$ {float_d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    c1, c2 = st.columns([1, 2])

    with c1:
        # Input 1: Estoque de Restos a Pagar (RPA)
        sufixo_rpa = st.session_state[f"f22_rpa_key_suffix_{ano_sel}"]
        input_rpa_str = st.text_input(
            "Estoque de Restos a Pagar - Proc. e Não Proc. (RPA) - R$:",
            value=str_inicial_rpa,
            placeholder="Ex: 150.000,00",
            key=f"txt_f22_rpa_dinamico_{ano_sel}_{sufixo_rpa}_{ctr}"
        )
        
        # Input 2: Disponibilidade de Caixa (D)
        sufixo_d = st.session_state[f"f22_d_key_suffix_{ano_sel}"]
        input_d_str = st.text_input(
            "Disponibilidade de Caixa / Disponível (D) - R$:",
            value=str_inicial_d,
            placeholder="Ex: 200.000,00",
            key=f"txt_f22_d_dinamico_{ano_sel}_{sufixo_d}_{ctr}"
        )

        # 🧹 Função interna para higienizar strings monetárias do padrão BR
        def limpa_conversao_monetaria(texto):
            num_limpo = texto.replace("R$", "").replace(" ", "")
            if "." in num_limpo and "," in num_limpo:
                num_limpo = num_limpo.replace(".", "").replace(",", ".")
            elif "," in num_limpo:
                num_limpo = num_limpo.replace(",", ".")
            return float(num_limpo)

        # Tratamento lógico e cálculo dinâmico do índice LRP e penalidades
        try:
            v_rpa = limpa_conversao_monetaria(input_rpa_str)
            v_d = max(limpa_conversao_monetaria(input_d_str), 0.01) # Evita divisão por zero
            
            # Cálculo do Índice LRP (Decimal Puro)
            LRP = round(v_rpa / v_d, 4)
            
            # 🛑 TRAVA DE INICIALIZAÇÃO
            if v_rpa == 0.0 and (dF22.get("link", "").strip() == ""):
                ptsF22 = 0.0
                texto_resultado = "Aguardando preenchimento..."
                texto_pontuacao = "⏳ 0,00 pontos"
                estilo_status = "color: #64748b;"
            else:
                # 🧮 MOTOR DE REGRAS (LÓGICA DE PENALIZAÇÃO DIRETA)
                if LRP <= 1.0000:
                    ptsF22 = 0.0
                    texto_resultado = "✅ ADEQUADO: O saldo em caixa cobre integralmente as obrigações de restos a pagar"
                    estilo_status = "color: #16a34a; font-weight: bold;"
                else: # LRP > 1.0000
                    ptsF22 = -5.0
                    texto_resultado = "🚨 CRÍTICO: Despesas postergadas sem suficiência de caixa financeira"
                    estilo_status = "color: #dc2626; font-weight: bold;"
                
                sinal_pontos = "" if ptsF22 >= 0 else " "
                texto_pontuacao = f"{sinal_pontos}{ptsF22:.2f} pontos".replace(".", ",")
                
        except ValueError:
            st.error("⚠️ Formato numérico inválido. Digite utilizando o padrão brasileiro (Ex: 150.000,00).")
            v_rpa, v_d = float_rpa, float_d
            LRP = float_rpa / max(float_d, 0.01)
            ptsF22 = float(dF22.get("pontos", 0))
            texto_resultado = "Erro na leitura do campo"
            texto_pontuacao = f"{ptsF22:.2f} pontos"
            estilo_status = "color: #dc2626;"

    with c2:
        lF22 = st.text_area("Link/Evidência (F22 - Liquidez Restos a Pagar RAAE/RI):", value=dF22.get("link", ""), key=f"txt_f22_{ano_sel}_{ctr}", height=150)

    # Exibição do painel consolidador de métricas fiscais decimais
    st.markdown(f"""
    <div style="padding: 12px; background-color: #f1f5f9; border-left: 5px solid #1e3a8a; border-radius: 4px; margin-top: 15px; margin-bottom: 15px;">
        📌 <b>Cálculo da Razão (RPA / D):</b> R$ {v_rpa:,.2f} / R$ {v_d:,.2f}<br>
        📊 <b>Resultado do Indicador (LRP):</b> <code style="font-size: 15px; font-weight: bold; color: #b45309;">{LRP:.4f}</code><br>
        ⚖️ <b>Suficiência de Caixa:</b> <span style="{estilo_status}">{texto_resultado}</span><br>
        🎯 <b>Glosa/Impacto na Pontuação:</b> <code style="font-size: 15px; font-weight: bold; color: #dc2626;">{texto_pontuacao}</code>
    </div>
    """.replace(", ", "X").replace(".", ",").replace("X", "."), unsafe_allow_html=True)

    # Verificação de alteração de dados para gatilho de persistência
    string_banco_atual = f"{v_rpa:.2f}/{v_d:.2f}"
    string_banco_salva = f"{float_rpa:.2f}/{float_d:.2f}"

    if string_banco_atual != string_banco_salva or lF22 != dF22["link"]:
        save_resp("F22", string_banco_atual, ptsF22, lF22)
        
        if f"{v_rpa:.2f}" != f"{float_rpa:.2f}":
            st.session_state[f"f22_rpa_key_suffix_{ano_sel}"] += 1
        if f"{v_d:.2f}" != f"{float_d:.2f}":
            st.session_state[f"f22_d_key_suffix_{ano_sel}"] += 1
            
        st.rerun()

    bloco_comentarios("F22", res_data)
    st.markdown('</div>', unsafe_allow_html=True)

