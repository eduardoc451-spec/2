import psycopg2
import psycopg2.extras
import streamlit as st

# URL DIRETA DO BANCO NEON
NEON_URI = "postgresql://neondb_owner:npg_beMKhVR2N4wo@ep-divine-sky-awx1636y-pooler.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"


def criar_conexao_direta():
    """Conecta diretamente ao banco de dados Neon."""
    try:
        conn = psycopg2.connect(NEON_URI)
        return conn, None
    except Exception as e:
        return None, str(e)


class SistemaHAL:

    def __init__(self):
        self.questoes_por_dimensao = {}
        self.carregar_dicionarios_globais()

    def carregar_dicionarios_globais(self):
        # Dicionário unificado com as dimensões operacionais
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": (
                    "Foi criada a Coordenadoria Municipal de Proteção e Defesa"
                    " Civil (COMPDEC) ou órgão similar responsável pela"
                    " execução, coordenação e mobilização de todas as ações de"
                    " defesa civil no município?"
                ),
                "1.3": (
                    "A COMPDEC ou órgão similar está associada ou subordinada"
                    " a qual secretaria/diretoria?"
                ),
                "1.4": (
                    "Os órgãos e entidades da administração pública municipal"
                    " atuam de forma sistêmica, articulados com a COMPDEC, nas"
                    " ações de prevenção, mitigação, preparação, resposta e"
                    " recuperação, de acordo com a Política Nacional de"
                    " Proteção e Defesa Civil (PNPDEC)?"
                ),
                "2.0": (
                    "Sobre treinamento e capacitação em Proteção e Defesa"
                    " Civil, a Prefeitura capacita seus agentes para ações"
                    " municipais de Defesa Civil?"
                ),
                "2.1": (
                    "Qual a data da última classificação dos agentes"
                    " municipais para ações de Defesa Civil?"
                ),
                "2.2": (
                    "A Prefeitura Municipal ofereceu cursos/treinamentos sobre"
                    " Proteção e Defesa Civil para qual público?"
                ),
                "3.0": (
                    "O Município realiza ações para estimular a participação de"
                    " entidades privadas, associações de voluntários, clubes"
                    " de serviços, organizações não governamentais e"
                    " associações de classe e comunitárias nas ações de"
                    " proteção e defesa civil?"
                ),
                "3.1.1": (
                    "Qual a data do último treinamento de associações de"
                    " voluntários?"
                ),
                "4.2": (
                    "A Carta Geotécnica de Suscetibilidade, Aptidão à"
                    " Urbanização e Risco consta no Plano Diretor, conforme"
                    " art. 42-A, §§ 1º, 2º e 3º, da Lei Federal nº 10.257, de"
                    " 10 de julho de 2001?"
                ),
                "5.0": (
                    "O Município realizou, por conta própria, o mapeamento e"
                    " identificação das principais ameaças existentes em seu"
                    " território?"
                ),
                "5.1.1": (
                    "As secretarias setoriais realizam a fiscalização das áreas"
                    " de risco?"
                ),
                "5.2": (
                    "A população foi informada sobre todas as ameaças"
                    " identificadas pelo município?"
                ),
                "6.0": (
                    "A Secretaria responsável realizou vistorias in edificações"
                    " vulneráveis com o objetivo de identificar a necessidade"
                    " de intervenção preventiva nos imóveis?"
                ),
                "7.0": (
                    "O Município possui Plano de Contingência Municipal"
                    " (PLANCON) de Defesa Civil?"
                ),
                "7.1": (
                    "Foi elaborado um PLANCON específico para cada ameaça"
                    " identificada?"
                ),
                "7.2": (
                    "São realizados regularmente exercícios simulados para as"
                    " contingências previstas no PLANCON?"
                ),
                "7.3": "O Município possui sistema de alerta para desastres?",
                "7.4": (
                    "O Município dispõe de sinal, dispositivo ou sistema de"
                    " alarme para desastres?"
                ),
                "7.5": (
                    "Possui cadastro dos locais para abrigo da população em"
                    " situação de desastre junto à Coordenadoria Estadual de"
                    " Proteção e Defesa Civil (CEPDEC)?"
                ),
                "7.6": (
                    "O Município possui cadastro da lista de fornecedores para"
                    " coleta e distribuição de suprimentos de ajuda humanitária"
                    " para o caso de desastre?"
                ),
                "8.0": (
                    "O Município possui um canal de atendimento de emergência à"
                    " população para registro de ocorrências de desastres?"
                ),
                "8.1.1.1": "O telefone 199 tem atendimento 24 horas por dia?",
                "8.2": (
                    "O Município registra as ocorrências de Defesa Civil de"
                    " forma eletrônica?"
                ),
                "9.0": (
                    "O Município realizou estudo de avaliação da estrutura de"
                    " todas as escolas e unidades de saúde para garantir que,"
                    " em caso de desastre, esses locais estejam preparados para"
                    " abrigar e atender a população afetada?"
                ),
                "10.0": "O Município elaborou seu Plano de Mobilidade Urbana?",
                "11.1": (
                    "Foram estabelecidas metas de qualidade e desempenho para"
                    " o transporte público coletivo municipal?"
                ),
                "11.1.1": (
                    "As metas de qualidade e desempenho do transporte público"
                    " coletivo estão sendo atingidas?"
                ),
                "11.2": (
                    "Foi realizada pesquisa de satisfação dos usuários do"
                    " transporte público coletivo em 2025?"
                ),
                "12.1": (
                    "Informe o instrumento normativo, número e data da"
                    " publicação do transporte regulamentado."
                ),
                "12.1.3": (
                    "O Município fiscaliza regularmente o transporte"
                    " remunerado privado individual de passageiros (táxi por"
                    " aplicativo)?"
                ),
                "14.0": (
                    "O Município adequou os calçamentos públicos para"
                    " acessibilidade das pessoas com deficiência e restrição"
                    " de mobilidade?"
                ),
                "15.0": (
                    "As vias públicas pavimentadas estão devidamente"
                    " sinalizadas (vertical e horizontalmente) de forma a"
                    " garantir condições adequadas de segurança na"
                    " circulação?"
                ),
                "16.0": (
                    "Há manutenção adequada das vias públicas no Município?"
                ),
                "C1.1": (
                    "Indique os pontos de controle externos da auditoria ou"
                    " controle de metas vigentes."
                ),
            },
            "iGov-Ti": {
                "1.0": (
                    "A Prefeitura possui uma área ou setor que cuida de"
                    " Tecnologia da Informação e Comunicação (TIC)?"
                ),
                "1.1": (
                    "Informe a quantidade de funcionários concursados,"
                    " comissionados e estagiários no suporte e atendimento de"
                    " primeiro nível."
                ),
                "1.2": (
                    "A prefeitura municipal definiu formalmente as atribuições"
                    " do pessoal do setor de Tecnologia da Informação e"
                    " Comunicação (TIC)?"
                ),
                "1.3": (
                    "A prefeitura disponibilizou capacitação para o pessoal da"
                    " área de Tecnologia da Informação e Comunicação (TIC)?"
                ),
                "1.3.1": "Informe em quais áreas houve capacitação.",
                "1.4": (
                    "Nas licitações e contratos que tenham como soluções o uso"
                    " de TIC, houve participação formalizada do pessoal de TIC?"
                    " (Verba municipal)"
                ),
                "1.4.1": "Assinale as etapas que o pessoal de TIC participa.",
                "1.4.2": (
                    "Sobre softwares adquiridos/licenciados nos últimos 5 anos,"
                    " foi realizada análise ou estudo prévio com a participação"
                    " de TIC?"
                ),
                "2.0": (
                    "A prefeitura municipal possui um PDTIC vigente que"
                    " estabeleça diretrizes e metas de atingimento no futuro?"
                ),
                "2.1": "Informe a página eletrônica (link na internet) do PDTIC.",
                "2.2": (
                    "O plano de TIC vigente contempla as metas operacionais"
                    " estratégicas municipais?"
                ),
                "2.3": "Qual a data da última atualização do PDTIC?",
                "3.0": (
                    "A Prefeitura dispõe de Política de Segurança da"
                    " Informação formalmente instituída e de cumprimento"
                    " obrigatório?"
                ),
                "3.1": (
                    "A Prefeitura establishes procedimentos e"
                    " responsabilidades quanto ao uso de TI (Termo de"
                    " Responsabilidade/Compromisso)?"
                ),
                "3.1.1": (
                    "O Termo de Responsabilidade/Compromisso dispõe sobre o"
                    " uso da assinatura eletrônica pelos funcionários?"
                ),
                "3.1.1.1": (
                    "Informe o tipo de assinatura eletrônica utilizada nos"
                    " documentos digitais."
                ),
                "3.2": (
                    "Os riscos de TIC são identificados de acordo com as normas"
                    " brasileiras da família ISO/IEC 27000?"
                ),
                "3.2.1": (
                    "As secretarias realizam a fiscalização das áreas de risco?"
                    " Informe quais normas ISO/IEC 27000 são utilizadas."
                ),
                "3.3": (
                    "Os riscos de TIC são identificados de acordo com as normas"
                    " da ABNT NBR ISO/IEC 31000?"
                ),
                "3.4": (
                    "A Prefeitura possui um Plano de Continuidade dos Serviços"
                    " de Tecnologia da Informação e Comunicação (TIC)?"
                ),
                "3.5": (
                    "A Prefeitura dispõe de política de cópias de segurança"
                    " (backup) formalmente instituída como norma obrigatória?"
                ),
                "3.6": "A Prefeitura possui inventário atualizado dos ativos de TIC?",
                "3.6.1": "Como é composta a base de ativos?",
                "4.0": (
                    "O município regulamentou a Lei de Acesso à Informação (Lei"
                    " Federal nº 12.527/2011)?"
                ),
                "4.1": (
                    "Informe o Instrumento normativo, Número e Data da"
                    " publicação (LAI)."
                ),
                "4.2": (
                    "Página eletrônica (link na internet) do instrumento"
                    " normativo da LAI."
                ),
                "5.0": (
                    "O município regulamentou a Lei sobre Eficiência Pública"
                    " (Governo Digital - Lei Federal nº 14.129/2021)?"
                ),
                "5.1": (
                    "Informe o Instrumento normativo, Número e Data da"
                    " publicação (Governo Digital)."
                ),
                "5.2": (
                    "Página eletrônica (link na internet) do instrumento"
                    " normativo (Governo Digital)."
                ),
                "5.3": (
                    "A Prefeitura implantou soluções digitais para trâmite de"
                    " processos administrativos?"
                ),
                "6.0": (
                    "A prefeitura mantém site na internet com informações"
                    " atualizadas?"
                ),
                "6.1": (
                    "O site eletrônico da prefeitura continha ferramenta de"
                    " pesquisa/busca interna de conteúdo?"
                ),
                "6.2": (
                    "O site possibilita o download de dados e informações em"
                    " formatos abertos e não proprietários?"
                ),
                "6.3": (
                    "O site disponibiliza as respostas a perguntas mais"
                    " frequentes da sociedade?"
                ),
                "6.4": (
                    "O site disponibiliza acessibilidade de conteúdo para"
                    " pessoas com deficiência?"
                ),
                "7.0": (
                    "A Prefeitura disponibiliza no site o Serviço de"
                    " Informação ao Cidadão (e-SIC)?"
                ),
                "7.1": "A solicitação por meio do e-SIC é simplificada?",
                "7.2": (
                    "O e-SIC apresenta possibilidade de acompanhamento da"
                    " solicitação?"
                ),
                "7.3": (
                    "Há necessidade de informar os motivos para a solicitação"
                    " de informações de interesse público?"
                ),
                "8.0": (
                    "A Prefeitura possui programas de computador (softwares)"
                    " para gestão de processos?"
                ),
                "8.1": (
                    "Os programas de computador (softwares) englobam quais"
                    " processos/setores?"
                ),
                "8.2": (
                    "Informe quais sistemas encontram-se integrados ao Sistema"
                    " de Contabilidade do município."
                ),
                "8.2.1": (
                    "Informe o nível de integração entre o Sistema da Dívida"
                    " Ativa e o de Contabilidade."
                ),
                "8.2.2": (
                    "Informe o nível de integração entre o Sistema de"
                    " Precatórios e o de Contabilidade."
                ),
                "8.3": (
                    "Assinale quais bases de dados encontram-se sob gestão"
                    " direta da Prefeitura (Risco de Perdas)."
                ),
                "8.4": (
                    "Assinale quais sistemas possuem controle de acesso à"
                    " informação."
                ),
                "9.0": "A Prefeitura ofereceu serviços de forma online?",
                "9.1": "Quais tipos de serviços são oferecidos online?",
                "9.2": (
                    "Quais as formas de atendimento à distância disponibilizadas"
                    " ao público pela Prefeitura?"
                ),
                "10.0": (
                    "A Prefeitura Municipal regulamentou o tratamento de dados"
                    " pessoais, inclusive nos meios digitais, segundo a LGPD"
                    " (Lei Federal nº 13.709/2018)?"
                ),
                "10.1": (
                    "Informe o instrumento normativo, número e data da"
                    " publicação."
                ),
                "10.2": "Informe a página eletrônica (link na internet).",
                "10.3": (
                    "Os contratos com os prestadores de serviços contêm"
                    " cláusulas de observância à LGPD?"
                ),
                "10.4": (
                    "A Prefeitura Municipal realizou mapeamento de dados (data"
                    " mapping)?"
                ),
                "10.5": (
                    "Foram adotadas medidas de segurança, técnicas e"
                    " administrativas para proteção dos dados pessoais?"
                ),
                "10.5.1": "Informe as medidas adotadas.",
                "11.0": (
                    "A Prefeitura Municipal designou um encarregado para as"
                    " operações de tratamento de dados pessoais?"
                ),
                "11.1": (
                    "Informe a página eletrônica que contenha a identidade e as"
                    " informações de contato do encarregado."
                ),
                "12.0": (
                    "Gostaria de registrar suas impressões, comentários e"
                    " sugestões a respeito do presente questionário?"
                ),
            },
        }

    def get_db_connection(self):
        return criar_conexao_direta()

    def get_dimensoes(self):
        return list(self.questoes_por_dimensao.keys())

    def get_quesitos_por_dimensao(self, dimensao):
        if dimensao in self.questoes_por_dimensao:
            return [
                f"{codigo} - {texto}"
                for codigo, texto in self.questoes_por_dimensao[
                    dimensao
                ].items()
            ]
        return []

    def get_resposta_municipio(self, dimensao, codigo_quesito, ano):
        """Busca a resposta na tabela correspondente à dimensão fornecida."""

        # Mapeamento dinâmico de tabelas
        tabelas_map = {
            "iCidade": "respostas",
            "iGov-Ti": "respostas_igov",
        }

        if dimensao not in tabelas_map:
            return {
                "resposta": "Dimensão em teste",
                "detalhes": f"A dimensão '{dimensao}' não possui tabela configurada.",
                "pontuacao_obtida": 0,
            }

        tabela = tabelas_map[dimensao]

        conn, erro = criar_conexao_direta()
        if not conn:
            return {
                "resposta": "Sem conexão",
                "detalhes": f"Erro de conexão com o Neon: {erro}",
                "pontuacao_obtida": 0,
            }

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                query = f"SELECT * FROM {tabela} WHERE id::text = %s AND ano = %s;"
                cur.execute(query, (str(codigo_quesito), int(ano)))
                resultado = cur.fetchone()

                if resultado:
                    dados = dict(resultado)

                    resp_val = (
                        dados.get("valor")
                        or dados.get("resposta")
                        or dados.get("texto")
                        or "Resposta cadastrada sem texto"
                    )

                    pontos_val = dados.get("pontos", dados.get("pontuacao", 0))
                    link = dados.get("link")
                    comentarios = dados.get("comentarios")

                    detalhe_texto = []
                    if link and str(link) not in ["EMPTY_STRING", "None", ""]:
                        detalhe_texto.append(f"Link: {link}")

                    if comentarios and str(comentarios) not in [
                        "EMPTY_STRING",
                        "[]",
                        "None",
                        "",
                    ]:
                        detalhe_texto.append(f"Comentários: {comentarios}")

                    txt_detalhes = (
                        " | ".join(detalhe_texto)
                        if detalhe_texto
                        else "Sem observações adicionais."
                    )

                    return {
                        "resposta": resp_val,
                        "detalhes": txt_detalhes,
                        "pontuacao_obtida": pontos_val,
                    }
                else:
                    return {
                        "resposta": "Sem registro",
                        "detalhes": (
                            f"Nenhum registro encontrado em {tabela} para o"
                            f" item {codigo_quesito} no ano {ano}."
                        ),
                        "pontuacao_obtida": 0,
                    }
        except Exception as e:
            return {
                "resposta": "Erro na consulta",
                "detalhes": f"Erro SQL ao consultar {tabela}: {e}",
                "pontuacao_obtida": 0,
            }
        finally:
            if conn:
                conn.close()


def mostrar_chat_hal():
    """Função para desenhar a interface do Streamlit."""
    st.title("Sistema HAL - Consulta")

    hal = SistemaHAL()

    dimensoes = hal.get_dimensoes()
    if dimensoes:
        dim_selecionada = st.selectbox("Selecione a Dimensão:", dimensoes)

        quesitos = hal.get_quesitos_por_dimensao(dim_selecionada)
        if quesitos:
            quesito_selecionado = st.selectbox(
                "Selecione o Quesito:", quesitos
            )
            # Extrai apenas o código (ex: "1.0" de "1.0 - Texto...")
            codigo_quesito = quesito_selecionado.split(" - ")[0]

            ano = st.number_input(
                "Ano:", min_value=2000, max_value=2030, value=2026
            )

            if st.button("Buscar Resposta"):
                resultado = hal.get_resposta_municipio(
                    dim_selecionada, codigo_quesito, ano
                )

                st.subheader(f"Resposta: {resultado['resposta']}")
                st.write(f"**Detalhes:** {resultado['detalhes']}")
                st.write(
                    f"**Pontuação:** {resultado['pontuacao_obtida']} pontos"
                )


def main():
    """Ponto de entrada do script."""
    mostrar_chat_hal()


if __name__ == "__main__":
    main()
