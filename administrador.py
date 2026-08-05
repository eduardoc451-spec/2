import io
import re
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def localizar_colunas_exatas(df):
    """
    Identifica de forma inteligente e por exclusão as colunas corretas,
    impedindo que colunas de anexos/links sejam confundidas com o usuário.
    """
    colunas = list(df.columns)
    
    # 1. Identifica Código (ID) e Descrição por texto ou posição inicial
    col_codigo = "id_quesito" if "id_quesito" in colunas else colunas[0]
    
    col_desc = "Descrição do Quesito"
    if col_desc not in colunas:
        col_desc = colunas[1] if len(colunas) > 1 else colunas[0]

    # 2. Identifica a Nota (geralmente tem 'nota' ou 'pontos' no nome)
    col_nota = None
    for col in colunas:
        if "nota" in col.lower() or "pontos" in col.lower() or "pts" in col.lower():
            col_nota = col
            break
    if not col_nota:
        col_nota = colunas[3] if len(colunas) > 3 else colunas[-2]

    # 3. Identifica a Resposta Principal
    col_resposta = "Resposta / Situação"
    if col_resposta not in colunas:
        col_resposta = colunas[2] if len(colunas) > 2 else colunas[1]

    # 4. PEGA O USUÁRIO DE FORMA RIGOROSA (Ignora colunas de links/metadados)
    col_usuario = None
    for col in colunas:
        if col.lower() in ["usuário responsável", "usuario", "responsavel", "usuario_responsavel", "login"]:
            col_usuario = col
            break
            
    if not col_usuario:
        for col in colunas:
            if col in [col_codigo, col_desc, col_resposta, col_nota]:
                continue
            
            # Pega uma amostra da linha para analisar o conteúdo
            amostra = str(df[col].dropna().iloc[0]).lower() if not df[col].dropna().empty else ""
            
            # Se a coluna tiver links ou metadados, ela NÃO é o usuário!
            if "http" in amostra or "drive.google" in amostra or "c:" in amostra or "link:" in amostra:
                continue
                
            col_usuario = col
            break

    if not col_usuario:
        col_usuario = colunas[-1]

    return col_codigo, col_desc, col_resposta, col_nota, col_usuario


def aplicar_ordenacao_natural(df, col_codigo):
    """
    Ordena o DataFrame dividindo os códigos dos quesitos em blocos numéricos.
    Funciona perfeitamente para: 1.0, 1.4, 8.2, 8.2.1, 8.2.11, etc.
    """
    df_copia = df.copy()
    
    def converter_para_tupla_chave(texto):
        blocos = re.findall(r'\d+', str(texto))
        if not blocos:
            return (9999,)
        return tuple(int(b) for b in blocos)

    df_copia['temp_chave_ordem'] = df_copia[col_codigo].apply(converter_para_tupla_chave)
    df_copia = df_copia.sort_values(by='temp_chave_ordem')
    df_copia = df_copia.drop(columns=['temp_chave_ordem'])
    return df_copia


def gerar_pdf_reportlab(ano, dimensão, df_filtrado):
    """Gera o arquivo PDF estruturando os dados de forma estrita ao que está gravado no banco."""
    buffer = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=landscape(letter), 
        rightMargin=20, 
        leftMargin=20, 
        topMargin=30, 
        bottomMargin=30
    )
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor('#001A4D'), alignment=1)
    subtitle_style = ParagraphStyle('SubTitleStyle', parent=styles['Normal'], fontSize=12, leading=16, textColor=colors.HexColor('#64748B'), alignment=1, spaceAfter=20)
    
    cell_text_style = ParagraphStyle('CellTextStyle', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.black)
    cell_header_style = ParagraphStyle('CellHeaderStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.HexColor('#001A4D'))

    story.append(Paragraph("IEG-M Francisco Morato", title_style))
    story.append(Paragraph("EXTRATO OFICIAL DE AUDITORIA E RASTREABILIDADE", subtitle_style))
    story.append(Spacer(1, 10))
    
    story.append(Paragraph(f"<b>Ano de Referência:</b> {ano}", cell_text_style))
    story.append(Paragraph(f"<b>Dimensão Selecionada:</b> {dimensão}", cell_text_style))
    story.append(Spacer(1, 15))
    
    # Obtém o mapeamento rigoroso e inteligente das colunas
    col_codigo, col_desc, col_resposta, col_nota, col_usuario = localizar_colunas_exatas(df_filtrado)
    df_ordenado = aplicar_ordenacao_natural(df_filtrado, col_codigo)

    data_tabela = [[
        Paragraph("Nº Quesito", cell_header_style),
        Paragraph("Descrição do Quesito", cell_header_style), 
        Paragraph("Resposta / Situação", cell_header_style), 
        Paragraph("Nota", cell_header_style), 
        Paragraph("Usuário Responsável", cell_header_style)
    ]]
    
    dimensao_normalizada = str(dimensão).lower().replace(" ", "").replace("-", "")
    is_igov_ti = "igovti" in dimensao_normalizada

    for _, linha in df_ordenado.iterrows():
        id_original = str(linha[col_codigo]).strip()
        if id_original.isdigit():
            id_original = f"{id_original}.0"
        
        # 1. TRADUÇÃO DO ENUNCIADO
        if is_igov_ti:
            try:
                # Caso a função higienizar_e_traduzir_quesito exista no seu escopo
                texto_final = higienizar_e_traduzir_quesito(id_original)
                if not texto_final: 
                    texto_final = str(linha[col_desc])
            except NameError:
                texto_final = str(linha[col_desc])
        else:
            texto_final = str(linha[col_desc])

        if "qid" in texto_final or "str(" in texto_final or "pts" in texto_final or texto_final.strip() == id_original:
            texto_final = f"Quesito de Auditoria Técnica — Referência {id_original}"

        # 2. LIMPEZA DA RESPOSTA
        resposta_crua = str(linha[col_resposta]).strip()
        if resposta_crua.startswith("[") and resposta_crua.endswith("]"):
            resposta_crua = resposta_crua.replace("[", "").replace("]", "").replace("'", "").replace('"', '').strip()
        if resposta_crua.lower() in ["none", "null", "nan", "", "selecione..."]:
            resposta_crua = "Não Respondido / Em Branco"

        # 3. LEITURA PURA E FILTRADA DA COLUNA DE USUÁRIO
        banco_user = str(linha[col_usuario]).strip()
        banco_user_clean = banco_user.replace("[", "").replace("]", "").replace("'", "").replace('"', '').strip()
        
        if banco_user_clean.lower() in ["none", "null", "nan", "", "[]", "['']", "undefined"]:
            responsavel_final = "Não Gravado"
        else:
            responsavel_final = banco_user_clean
            
        # 4. TRATAMENTO DA NOTA
        nota_final = str(linha[col_nota]).strip()
        if nota_final.lower() in ["none", "null", "nan", ""]:
            nota_final = "0.0"

        data_tabela.append([
            Paragraph(id_original, cell_text_style),
            Paragraph(texto_final, cell_text_style),
            Paragraph(resposta_crua, cell_text_style),
            Paragraph(nota_final, cell_text_style),
            Paragraph(responsavel_final, cell_text_style)
        ])
    
    larguras = [62, 235, 235, 40, 180]
    
    t = Table(data_tabela, colWidths=larguras, repeatRows=1, splitByRow=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E6F0FF')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),  
        ('ALIGN', (3, 0), (3, -1), 'CENTER'),  
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    story.append(t)
    
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()