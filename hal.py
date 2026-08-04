import psycopg2
import psycopg2.extras

class SistemaHAL:
    def __init__(self):
        self.questoes_por_dimensao = {}
        self.carregar_dicionarios_globais()

    def carregar_dicionarios_globais(self):
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": "Foi criada a Coordenadoria Municipal de Proteção e Defesa Civil (COMPDEC)...",
                "1.3": "A COMPDEC ou órgão similar está associada ou subordinada a qual secretaria/diretoria?",
            },
            "iGov-Ti": {
                "1.0": "A Prefeitura possui uma área ou setor que cuida de Tecnologia da Informação...",
            },
            "i-Amb": {
                "1.0": "Existe estrutura organizacional instalada para tratar de assuntos ligados ao Meio Ambiente Municipal?",
            }
        }

    def get_db_connection(self):
        """
        Conecta diretamente ao banco de dados Neon via URI real.
        """
        # Substituído a URL genérica pela sua conexão real do Neon
        DATABASE_URL = "postgresql://neondb_owner:npg_beMKhVR2N4wo@ep-divine-sky-awx1636y-pooler.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn, None
        except Exception as e:
            return None, str(e)

    def get_dimensoes(self):
        if hasattr(self, 'questoes_por_dimensao') and isinstance(self.questoes_por_dimensao, dict):
            return list(self.questoes_por_dimensao.keys())
        return ["iCidade", "iGov-Ti", "i-Amb"]

    def get_quesitos_por_dimensao(self, dimensao):
        if hasattr(self, 'questoes_por_dimensao') and dimensao in self.questoes_por_dimensao:
            return [
                f"{codigo} - {texto}" 
                for codigo, texto in self.questoes_por_dimensao[dimensao].items()
            ]
        return []

    def get_resposta_municipio(self, dimensao, codigo_quesito, ano):
        mapa_tabelas = {
            "iGov-Ti": "respostas_igov",
            "i-Amb": "respostas_iamb",
            "iCidade": "respostas_iplan"
        }

        tabela = mapa_tabelas.get(dimensao)
        if not tabela:
            return {
                "resposta": "Dimensão desconhecida",
                "detalhes": f"Tabela para a dimensão {dimensao} não configurada.",
                "pontuacao_obtida": 0
            }

        conn, erro = self.get_db_connection()
        if not conn:
            return {
                "resposta": "Sem conexão",
                "detalhes": f"Não foi possível conectar ao banco Neon: {erro}",
                "pontuacao_obtida": 0
            }

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                query = f"""
                    SELECT id, ano, valor, pontos, link, comentarios 
                    FROM {tabela} 
                    WHERE id = %s AND ano = %s;
                """
                cur.execute(query, (str(codigo_quesito), int(ano)))
                resultado = cur.fetchone()

                if resultado:
                    detalhe_texto = []
                    link = resultado.get('link')
                    comentarios = resultado.get('comentarios')

                    if link and link != 'EMPTY_STRING':
                        detalhe_texto.append(f"Link: {link}")
                    if comentarios and comentarios != 'EMPTY_STRING':
                        detalhe_texto.append(f"Comentários: {comentarios}")

                    txt_detalhes = " | ".join(detalhe_texto) if detalhe_texto else "Sem observações adicionais."

                    return {
                        "resposta": resultado.get('valor') if resultado.get('valor') else "Sem resposta",
                        "detalhes": txt_detalhes,
                        "pontuacao_obtida": resultado.get('pontos') if resultado.get('pontos') is not None else 0
                    }
                else:
                    return {
                        "resposta": "Sem registro",
                        "detalhes": f"Nenhum registro encontrado na tabela {tabela} para o item {codigo_quesito} em {ano}.",
                        "pontuacao_obtida": 0
                    }
        except Exception as e:
            return {
                "resposta": "Erro na consulta",
                "detalhes": f"Erro SQL ao consultar {tabela}: {e}",
                "pontuacao_obtida": 0
            }
        finally:
            if conn:
                conn.close()

    def carregar_dicionarios_globais(self):
        # Dicionário unificado com as 3 dimensões operacionais
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
                    "Sobre treinamento e capacitação em Proteção e Defesa Civil,"
                    " a Prefeitura capacita seus agentes para ações municipais"
                    " de Defesa Civil?"
                ),
                "2.1": (
                    "Qual a data da última classificação dos agentes municipais"
                    " para ações de Defesa Civil?"
                ),
                "2.2": (
                    "A Prefeitura Municipal offered cursos/treinamentos sobre"
                    " Proteção e Defesa Civil para qual público?"
                ),
                "3.0": (
                    "O Município realiza ações para estimular a participação de"
                    " entidades privadas, associações de voluntários, clubes de"
                    " serviços, organizações não governamentais e associações"
                    " de classe e comunitárias nas ações de proteção e defesa"
                    " civil?"
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
                    " vulneráveis com o objetivo de identificar a necessidade de"
                    " intervenção preventiva nos imóveis?"
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
                    "São realizados regularly exercícios simulados para as"
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
                "10.0": (
                    "O Município elaborou seu Plano de Mobilidade Urbana?"
                ),
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
                    "O Município fiscaliza regularmente o transporte remunerado"
                    " privado individual de passageiros (táxi por aplicativo)?"
                ),
                "14.0": (
                    "O Município adequou os calçamentos públicos para"
                    " acessibilidade das pessoas com deficiência e restrição de"
                    " mobilidade?"
                ),
                "15.0": (
                    "As vias públicas pavimentadas estão devidamente"
                    " sinalizadas (vertical e horizontalmente) de forma a"
                    " garantir condições adequadas de segurança na circulação?"
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
                "1.4.1": (
                    "Assinale as etapas que o pessoal de TIC participa."
                ),
                "1.4.2": (
                    "Sobre softwares adquiridos/licenciados nos últimos 5 anos,"
                    " foi realizada análise ou estudo prévio com a participação"
                    " de TIC?"
                ),
                "2.0": (
                    "A prefeitura municipal possui um PDTIC vigente que"
                    " estabeleça diretrizes e metas de atingimento no futuro?"
                ),
                "2.1": (
                    "Informe a página eletrônica (link na internet) do PDTIC."
                ),
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
                    "O Termo de Responsabilidade/Compromisso dispõe sobre o uso"
                    " da assinatura eletrônica pelos funcionários?"
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
                "3.6": (
                    "A Prefeitura possui inventário atualizado dos ativos de"
                    " TIC?"
                ),
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
                    "Há necessidade de informar os motivos para a solicitação de"
                    " informações de interesse público?"
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
                "9.0": "A Prefeitura offered serviços de forma online?",
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
            "i-Amb": {
                "1.0": (
                    "Existe estrutura organizacional instalada para tratar de"
                    " assuntos ligados ao Meio Ambiente Municipal?"
                ),
                "1.1": (
                    "Informe a disponibilidade de recursos humanos para"
                    " operacionalização dos assuntos ligados ao Meio Ambiente."
                ),
                "1.1.1": (
                    "Informe o detalhamento e informações sobre os recursos"
                    " humanos da área."
                ),
                "1.1.2": (
                    "A prefeitura realizou treinamento específico voltado ao"
                    " Meio Ambiente no ano de 2025?"
                ),
                "1.1.3": (
                    "Informe os cursos e treinamentos de educação ambiental"
                    " ofertados pela Secretaria de Meio Ambiente."
                ),
                "1.2": (
                    "Informe quais recursos foram disponibilizados para a"
                    " operacionalização das atividades de meio ambiente."
                ),
                "2.0": (
                    "O Município promove a participação em Programas de Educação"
                    " Ambiental?"
                ),
                "2.1": (
                    "Há programas ou ações de educação ambiental implementadas"
                    " na rede escolar municipal?"
                ),
                "3.0": (
                    "O Município promove estímulo a projetos e ações para o uso"
                    " racional de recursos naturais?"
                ),
                "3.1": (
                    "Assinale quais tipos de ações são realizadas para o uso"
                    " racional de recursos naturais."
                ),
                "4.0": (
                    "Há fiscalização da emissão de poluentes de combustíveis"
                    " fósseis (diesel) na frota municipal?"
                ),
                "5.0": (
                    "Existe contrato vigente para a prestação de serviços de"
                    " poda e corte de árvores, arbustos e outras plantas"
                    " lenhosas?"
                ),
                "5.1": (
                    "Informe o número do contrato e o respectivo prestador de"
                    " serviço."
                ),
                "5.2": (
                    "Qual a periodicidade definida para a realização de poda e"
                    " manutenção das árvores?"
                ),
                "5.2.1": (
                    "Informe a destinação final dada aos resíduos decorrentes das"
                    " podas de árvores."
                ),
                "5.3": (
                    "Houve capacitação específica para os responsáveis pela"
                    " execução da manutenção e poda de árvores?"
                ),
                "6.0": (
                    "O Município adota ações e medidas preventivas de"
                    " contingenciamento para períodos de estiagem?"
                ),
                "6.1": (
                    "Informe os tipos de ações and medidas preventivas que foram"
                    " executadas."
                ),
                "6.2": (
                    "Indique os setores envolvidos com ações específicas para a"
                    " provisão de água potável."
                ),
                "7.0": (
                    "Existe Plano Municipal ou Regional de Saneamento Básico"
                    " instituído e vigente?"
                ),
                "7.1": "Informe o instrumento normativo de aprovação do Plano.",
                "7.2": (
                    "Informe a página eletrônica (link na internet) para acesso"
                    " ao Plano."
                ),
                "7.3": (
                    "O Plano establishes metas específicas de abastecimento de"
                    " água potável?"
                ),
                "7.3.1": (
                    "Informe detalhadamente as metas estabelecidas para o"
                    " abastecimento de água."
                ),
                "7.3.2": (
                    "Qual a data prevista para a universalização do"
                    " atendimento de abastecimento de água?"
                ),
                "7.4": "O Plano estabelece metas de coleta de esgoto sanitário?",
                "7.4.1": (
                    "Informe as metas estabelecidas para o serviço de coleta de"
                    " esgoto."
                ),
                "7.4.2": (
                    "Qual a data prevista para a universalização da coleta de"
                    " esgoto?"
                ),
                "7.5": (
                    "O Plano estabelece metas para o tratamento do esgoto"
                    " coletado?"
                ),
                "7.5.1": (
                    "Qual a data prevista para a universalização do tratamento"
                    " de esgoto?"
                ),
                "7.6": (
                    "O Plano contempla metas de drenagem e manejo de águas"
                    " pluviais urbanas?"
                ),
                "7.6.1": (
                    "Informe as metas estabelecidas voltadas à drenagem e"
                    " manejo de águas pluviais."
                ),
                "7.7": (
                    "O Município realiza o monitoramento e avaliação das ações e"
                    " metas de abastecimento de água e esgotamento sanitário?"
                ),
                "7.7.1": (
                    "Informe de qual forma é realizado este monitoramento e"
                    " avaliação."
                ),
                "7.8": (
                    "Existe um cronograma formalizado de metas para o"
                    " saneamento básico?"
                ),
                "7.8.1": (
                    "As metas estabelecidas estão sendo cumpridas dentro do"
                    " prazo estipulado?"
                ),
                "7.8.1.1": (
                    "Informe os principais motivos que justificam o não"
                    " cumprimento das metas."
                ),
                "7.9": (
                    "O Plano apresenta previsão de áreas prioritárias ou"
                    " críticas para intervenções de abastecimento de água e"
                    " esgotamento sanitário?"
                ),
                "7.10": (
                    "Qual a data da última revisão realizada no Plano de"
                    " Saneamento Básico?"
                ),
                "8.0": (
                    "Existe Plano Municipal ou Regional de Gestão Integrada de"
                    " Resíduos Sólidos instituído?"
                ),
                "8.1": (
                    "Informe o instrumento normativo de aprovação do Plano de"
                    " Resíduos Sólidos."
                ),
                "8.2": (
                    "Informe a página eletrônica (link na internet) para acesso"
                    " ao Plano."
                ),
                "8.3": (
                    "O Plano apresenta a caracterização qualitativa e"
                    " quantitativa dos resíduos sólidos urbanos?"
                ),
                "8.3.1": (
                    "Informe a metodologia ou forma utilizada para a"
                    " caracterização dos resíduos."
                ),
                "8.4": (
                    "Existe um cronograma formalizado de metas para a gestão de"
                    " resíduos sólidos?"
                ),
                "8.4.1": (
                    "Informe as metas que foram formalmente estabelecidas sobre"
                    " os resíduos sólidos."
                ),
                "8.4.2": (
                    "O Município realiza o monitoramento e avaliação das ações e"
                    " metas deste Plano?"
                ),
                "8.4.2.1": (
                    "Informe de qual forma é realizado esse monitoramento e"
                    " avaliação."
                ),
                "8.4.3": (
                    "As metas estabelecidas estão sendo cumpridas dentro do"
                    " prazo estipulado?"
                ),
                "8.4.3.1": (
                    "Informe os principais motivos para o não cumprimento das"
                    " metas no prazo."
                ),
                "8.4.4": (
                    "Qual a data da última revisão do Plano de Gestão"
                    " Integrada de Resíduos Sólidos?"
                ),
                "9.0": (
                    "O Município realiza de forma efetiva a coleta seletiva de"
                    " resíduos sólidos?"
                ),
                "9.1": (
                    "Existe um cronograma ou planejamento de coleta seletiva"
                    " programada?"
                ),
                "9.2": (
                    "A prestação da coleta seletiva atende a todas as regiões"
                    " do território municipal?"
                ),
                "9.3": (
                    "São promovidas ações e campanhas institucionais de"
                    " incentivo à coleta seletiva?"
                ),
                "9.3.1": (
                    "Informe quais tipos de ações e campanhas de conscientização"
                    " foram realizadas."
                ),
                "10.0": (
                    "O Município realiza o serviço regular de coleta de lixo"
                    " doméstico (resíduos domiciliares)?"
                ),
                "10.1": (
                    "Existe um cronograma de atendimento para a coleta"
                    " programada?"
                ),
                "10.2": (
                    "O serviço regular de coleta de lixo domiciliar atende a"
                    " todas as regiões do município?"
                ),
                "10.3": (
                    "O Município dispõe de Área de Transbordo e Triagem (ATT)"
                    " para resíduos sólidos urbanos?"
                ),
                "10.3.1": (
                    "A referida ATT possui licença de operação ativa emitida"
                    " pela CETESB?"
                ),
                "10.3.1.1": (
                    "Informe o prazo de validade da licença de operação da"
                    " CETESB."
                ),
                "11.0": (
                    "Existe Plano de Gerenciamento de Resíduos da Construção"
                    " Civil (PGRCC) instituído?"
                ),
                "11.1": (
                    "Informe o instrumento normativo que regulamenta o PGRCC."
                ),
                "11.2": "Informe a página eletrônica (link na internet) do PGRCC.",
                "11.3": (
                    "Existe um cronograma de metas definido no âmbito do PGRCC?"
                ),
                "11.3.1": (
                    "Informe as metas previstas no Plano de Resíduos da"
                    " Construção Civil."
                ),
                "11.3.2": (
                    "Há monitoramento e avaliação das ações e metas do PGRCC?"
                ),
                "11.3.2.1": (
                    "Informe de qual forma é realizado o monitoramento e a"
                    " avaliação."
                ),
                "11.3.3": (
                    "As metas estabelecidas no PGRCC estão sendo cumpridas no"
                    " prazo estipulado?"
                ),
                "11.3.3.1": (
                    "Informe os motivos identificados para o não cumprimento das"
                    " metas estruturadas."
                ),
                "11.4": (
                    "Quem é o agente ou setor responsável pela triagem dos"
                    " resíduos da construção civil?"
                ),
                "11.5": (
                    "O Município realiza a fiscalização activa das atividades"
                    " relacionadas aos resíduos da construção civil?"
                ),
                "11.5.1": (
                    "Informe quais as principais atividades que são fiscalizadas"
                    " pelo órgão municipal."
                ),
                "11.6": (
                    "Existe Área de Transbordo e Triagem (ATT) específica para"
                    " resíduos da construção civil?"
                ),
                "11.6.1": (
                    "A referida ATT de resíduos da construção civil possui"
                    " licença de operação da CETESB?"
                ),
                "11.6.1.1": (
                    "Informe o prazo de validade da licença emitida pela"
                    " CETESB."
                ),
                "12.0": (
                    "O Município adota alguma forma de processamento de"
                    " resíduos antes da sua disposição final?"
                ),
                "12.1": (
                    "Informe detalhadamente qual a forma de processamento"
                    " utilizada nos resíduos."
                ),
                "13.0": (
                    "Existe aterro sanitário ou industrial para destinação de"
                    " resíduos sólidos urbanos no território municipal ou"
                    " consorciado?"
                ),
                "13.1": (
                    "Informe as características e a situação atual do local de"
                    " destinação final dos resíduos."
                ),
                "13.1.1": (
                    "Informe a data provável estimada para o fechamento ou"
                    " esgotamento do aterro."
                ),
                "13.2": (
                    "O aterro utilizado possui licença de operação regular"
                    " emitida pela CETESB?"
                ),
                "13.2.1": (
                    "Informe o prazo de validade da respectiva licença de"
                    " operação."
                ),
                "14.0": (
                    "Foram identificados pontos de descarte irregular de lixo ou"
                    " entulho no município?"
                ),
                "14.1": (
                    "Informe a quantidade total de pontos de descarte irregular"
                    " atualmente identificados."
                ),
                "14.2": (
                    "Indique os endereços ou localizações dos pontos críticos"
                    " identificados."
                ),
                "14.3": (
                    "Quais ações práticas e fiscalizatórias foram promovidas"
                    " para combater e mitigar o descarte irregular?"
                ),
                "15.0": (
                    "Está definida qual a entidade responsável pela regulação e"
                    " fiscalização dos serviços de saneamento básico?"
                ),
                "15.1": (
                    "Assinale quais serviços municipais possuem entidade"
                    " reguladora e fiscalizadora externa ou interna."
                ),
                "15.1.1": (
                    "Informe a entidade responsável pela regulação do"
                    " abastecimento de água potável."
                ),
                "15.1.2": (
                    "Informe a entidade responsável pela regulação do"
                    " esgotamento sanitário."
                ),
                "15.1.3": (
                    "Informe a entidade responsável pela regulação da limpeza"
                    " urbana e manejo de resíduos sólidos."
                ),
                "15.1.4": (
                    "Informe a entidade responsável pela regulação da drenagem e"
                    " manejo das águas pluviais urbanas."
                ),
                "16.0": (
                    "Gostaria de registrar suas impressões, comentários e"
                    " sugestões gerais a respeito deste bloco do questionário?"
                ),
                "A1": (
                    "O Município possui Zoneamento Ecológico-Econômico (ZEE)"
                    " instituído ou em andamento?"
                ),
                "A2": (
                    "Há monitoramento sistemático da qualidade do ar nas zones"
                    " urbanas ou industriais do município?"
                ),
                "A3": (
                    "O município possui mapeamento atualizado e proteção ativa de"
                    " suas Áreas de Preservação Permanente (APP)?"
                ),
                "A4": (
                    "Existe programa municipal voltado para a proteção e"
                    " bem-estar de animais domésticos e controle de zoonoses?"
                ),
                "A4.1.1": (
                    "Informe a capacidade física e operacional do abrigo ou"
                    " canil municipal."
                ),
                "A4.1.1.1": (
                    "Há veterinário responsável contratado em regime definitivo"
                    " ou plantonista?"
                ),
                "A4.1.2": (
                    "O município realiza campanhas periódicas e gratuitas de"
                    " castração de cães e gatos?"
                ),
                "A4.1.3": (
                    "Informe o número de procedimentos de esterilização animal"
                    " realizados no último ano de exercício."
                ),
                "A4.1.4": (
                    "Existem parcerias ativas com ONGs e protetores"
                    " independentes locais registradas?"
                ),
                "A5": (
                    "O Município possui plano de prevenção e combate a incêndios"
                    " florestais e queimadas urbanas?"
                ),
                "A6": (
                    "O órgão ambiental municipal possui equipamentos adequados"
                    " para atendimento e contenção de emergências químicas ou"
                    " derramamentos?"
                ),
            },
        }

import streamlit as st
import psycopg2
import psycopg2.extras

class SistemaHAL:
    def __init__(self):
        self.questoes_por_dimensao = {}
        self.pontuacoes_maximas_por_dimensao = {}
        self.carregar_dicionarios_globais()

    def carregar_dicionarios_globais(self):
        self.questoes_por_dimensao = {
            "iCidade": {
                "1.0": "Foi criada a Coordenadoria Municipal de Proteção e Defesa Civil (COMPDEC)...",
                "1.3": "A COMPDEC ou órgão similar está associada ou subordinada a qual secretaria/diretoria?",
            },
            "iGov-Ti": {
                "1.0": "A Prefeitura possui uma área ou setor que cuida de Tecnologia da Informação...",
            },
            "i-Amb": {
                "1.0": "Existe estrutura organizacional instalada para tratar de assuntos ligados ao Meio Ambiente Municipal?",
            }
        }

    def get_db_connection(self):
        """
        Estabelece a conexão com o PostgreSQL (Neon).
        Lê as credenciais preferencialmente do st.secrets.
        """
        try:
            # Caso esteja configurado no st.secrets (.streamlit/secrets.toml)
            if "postgres" in st.secrets:
                conn = psycopg2.connect(**st.secrets["postgres"])
            else:
                # Exemplo fallback para desenvolvimento local (substitua com suas credenciais se necessário)
                conn = psycopg2.connect(
                    dbname="seu_banco",
                    user="seu_usuario",
                    password="sua_senha",
                    host="seu_host.neon.tech",
                    port="5432"
                )
            return conn, None
        except Exception as e:
            return None, str(e)

    def get_dimensoes(self):
        """Retorna as dimensões disponíveis no dicionário."""
        if hasattr(self, 'questoes_por_dimensao') and isinstance(self.questoes_por_dimensao, dict):
            return list(self.questoes_por_dimensao.keys())
        return ["iCidade", "iGov-Ti", "i-Amb"]

    def get_quesitos_por_dimensao(self, dimensao):
        """Retorna uma lista formatada com [Código] + [Texto da Pergunta]"""
        if hasattr(self, 'questoes_por_dimensao') and dimensao in self.questoes_por_dimensao:
            return [
                f"{codigo} - {texto}" 
                for codigo, texto in self.questoes_por_dimensao[dimensao].items()
            ]
        return []

    def get_resposta_municipio(self, dimensao, codigo_quesito, ano):
        """
        Busca a resposta real no banco de dados Neon consultando a tabela específica.
        """
        mapa_tabelas = {
            "iGov-Ti": "respostas_igov",
            "i-Amb": "respostas_iamb",
            "iCidade": "respostas_iplan"
        }

        tabela = mapa_tabelas.get(dimensao)
        if not tabela:
            return {
                "resposta": "Dimensão desconhecida",
                "detalhes": f"Tabela para a dimensão {dimensao} não configurada.",
                "pontuacao_obtida": 0
            }

        conn, erro = self.get_db_connection()
        if not conn:
            return {
                "resposta": "Sem conexão",
                "detalhes": f"Não foi possível conectar ao banco de dados Neon: {erro}",
                "pontuacao_obtida": 0
            }

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                query = f"""
                    SELECT id, ano, valor, pontos, link, comentarios 
                    FROM {tabela} 
                    WHERE id = %s AND ano = %s;
                """
                cur.execute(query, (str(codigo_quesito), int(ano)))
                resultado = cur.fetchone()

                if resultado:
                    detalhe_texto = []
                    link = resultado.get('link')
                    comentarios = resultado.get('comentarios')

                    if link and link != 'EMPTY_STRING':
                        detalhe_texto.append(f"Link: {link}")
                    if comentarios and comentarios != 'EMPTY_STRING':
                        detalhe_texto.append(f"Comentários: {comentarios}")

                    txt_detalhes = " | ".join(detalhe_texto) if detalhe_texto else "Sem observações adicionais."

                    return {
                        "resposta": resultado.get('valor') if resultado.get('valor') else "Sem resposta",
                        "detalhes": txt_detalhes,
                        "pontuacao_obtida": resultado.get('pontos') if resultado.get('pontos') is not None else 0
                    }
                else:
                    return {
                        "resposta": "Sem registro",
                        "detalhes": f"Nenhum registro encontrado na tabela {tabela} para o item {codigo_quesito} em {ano}.",
                        "pontuacao_obtida": 0
                    }
        except Exception as e:
            return {
                "resposta": "Erro na consulta",
                "detalhes": f"Erro SQL ao consultar {tabela}: {e}",
                "pontuacao_obtida": 0
            }
        finally:
            if conn:
                conn.close()


def mostrar_chat_hal():
    st.title("🤖 Assistente HAL - Análise & Diagnóstico")

    # Garante que a instância existe E que possui o método novo
    if (
        "sistema_hal" not in st.session_state
        or not hasattr(st.session_state.sistema_hal, "get_db_connection")
    ):
        st.session_state.sistema_hal = SistemaHAL()

    sistema = st.session_state.sistema_hal

    # Status da Conexão com o Banco
    with st.expander("🔌 Status da Conexão com o Banco", expanded=False):
        conn, erro_conexao = sistema.get_db_connection()
        if conn:
            st.success("✅ Conectado ao PostgreSQL (Neon) com sucesso!")
            conn.close()
        else:
            st.error("❌ Falha ao conectar no banco Neon!")
            st.code(f"Erro: {erro_conexao}", language="bash")

    # ---------------------------------------------------------
    # Filtros de Consulta
    # ---------------------------------------------------------
    st.subheader("📊 Consulta por Dimensão e Quesito")

    lista_dimensoes = sistema.get_dimensoes()
    lista_anos = [2026, 2025, 2024, 2023] # Anos relevantes em ordem decrescente

    col1, col2, col3 = st.columns([1, 2.5, 1])

    with col1:
        dimensao_sel = st.selectbox("Dimensão:", options=lista_dimensoes)

    with col2:
        lista_quesitos_formatados = sistema.get_quesitos_por_dimensao(dimensao_sel)
        quesito_formatado_sel = st.selectbox("Quesito / Pergunta:", options=lista_quesitos_formatados)
        codigo_quesito_sel = quesito_formatado_sel.split(" - ")[0] if quesito_formatado_sel else ""

    with col3:
        ano_sel = st.selectbox("Ano:", options=lista_anos)

    # Exibição do Resultado da Consulta
    if quesito_formatado_sel:
        dados_resposta = sistema.get_resposta_municipio(dimensao_sel, codigo_quesito_sel, ano_sel)

        with st.container(border=True):
            st.markdown(f"### 📍 Resposta do Município ({ano_sel})")
            st.caption(f"**Item:** {quesito_formatado_sel}")
            st.divider()

            col_res1, col_res2 = st.columns([3, 1])
            with col_res1:
                st.write(f"**Resposta Cadastrada:** {dados_resposta.get('resposta', 'Sem registro')}")
                st.write(f"**Detalhamento:** {dados_resposta.get('detalhes', 'Sem observações')}")
            with col_res2:
                pontos = dados_resposta.get('pontuacao_obtida', 0)
                st.metric("Pontuação", pontos)

    st.divider()

    # ---------------------------------------------------------
    # Chat Interativo
    # ---------------------------------------------------------
    st.subheader("💬 Diagnóstico com o Assistente HAL")

    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []

    # Renderiza mensagens anteriores
    for msg in st.session_state.mensagens:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Entrada do chat
    if prompt := st.chat_input(f"Pergunte ao HAL sobre o quesito {codigo_quesito_sel} ({ano_sel})..."):
        st.session_state.mensagens.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            texto_pergunta = sistema.questoes_por_dimensao.get(dimensao_sel, {}).get(codigo_quesito_sel, "")
            
            # Aqui você pode enviar 'prompt_contextualizado' para a API da sua LLM (OpenAI, Gemini, etc.)
            prompt_contextualizado = (
                f"Contexto: Dimensão {dimensao_sel}, Quesito {codigo_quesito_sel} ('{texto_pergunta}'), Ano {ano_sel}.\n"
                f"Pergunta do usuário: {prompt}"
            )

            resposta = f"Analisando **{dimensao_sel}** (Item {codigo_quesito_sel} - {ano_sel}):\n\nRecebi sua pergunta: *\"{prompt}\"*."
            
            st.write(resposta)
            st.session_state.mensagens.append({"role": "assistant", "content": resposta})


if __name__ == "__main__":
    mostrar_chat_hal()
