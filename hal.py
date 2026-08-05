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
                    "O Município promove a participação em Programas de"
                    " Educação Ambiental?"
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
                    "Informe a destinação final dada aos resíduos decorrentes"
                    " das podas de árvores."
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
                    "Informe os tipos de ações e medidas preventivas que foram"
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
                "7.1": (
                    "Informe o instrumento normativo de aprovação do Plano."
                ),
                "7.2": (
                    "Informe a página eletrônica (link na internet) para"
                    " acesso ao Plano."
                ),
                "7.3": (
                    "O Plano estabelece metas específicas de abastecimento de"
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
                "7.4": (
                    "O Plano estabelece metas de coleta de esgoto sanitário?"
                ),
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
                    "Qual a data prevista para a universalização do"
                    " tratamento de esgoto?"
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
                    "O Município realiza o monitoramento e avaliação das ações"
                    " e metas de abastecimento de água e esgotamento"
                    " sanitário?"
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
                    "Informe a página eletrônica (link na internet) para"
                    " acesso ao Plano."
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
                    "O Município realiza o monitoramento e avaliação das ações"
                    " e metas deste Plano?"
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
                    "Informe quais tipos de ações e campanhas de"
                    " conscientização foram realizadas."
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
                "11.2": (
                    "Informe a página eletrônica (link na internet) do PGRCC."
                ),
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
                    "Informe os motivos identificados para o não cumprimento"
                    " das metas estruturadas."
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
                    "Informe quais as principais atividades que são"
                    " fiscalizadas pelo órgão municipal."
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
                    "Foram identificados pontos de descarte irregular de lixo"
                    " ou entulho no município?"
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
                    "Informe a entidade responsável pela regulação da drenagem"
                    " e manejo das águas pluviais urbanas."
                ),
                "16.0": (
                    "Gostaria de registrar suas impressões, comentários e"
                    " sugestões gerais a respeito deste bloco do"
                    " questionário?"
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
                    "O município possui mapeamento atualizado e proteção ativa"
                    " de suas Áreas de Preservação Permanente (APP)?"
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
                    "Há veterinário responsável contratado em regime"
                    " definitivo ou plantonista?"
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
                    "O Município possui plano de prevenção e combate a"
                    " incêndios florestais e queimadas urbanas?"
                ),
                "A6": (
                    "O órgão ambiental municipal possui equipamentos adequados"
                    " para atendimento e contenção de emergências químicas ou"
                    " derramamentos?"
                ),
            },
            "iPlan": {
                "1.0": (
                    "Prefeitura realizou audiências públicas para elaboração das"
                    " peças orçamentárias?"
                ),
                "1.1": (
                    "Para quais peças orçamentárias foram realizadas as"
                    " audiências públicas?"
                ),
                "1.2": "Dia e horário das audiências públicas.",
                "1.3": (
                    "As audiências são registradas em atas ou documentos?"
                ),
                "1.3.1": "Link de divulgação das atas.",
                "1.4": (
                    "Elementos considerados no planejamento e organização das"
                    " audiências."
                ),
                "2.0": (
                    "Houve consulta pública online para elaboração do PPA"
                    " 2022-2025?"
                ),
                "2.1": (
                    "Foi disponibilizado glossário explicativo na consulta"
                    " pública?"
                ),
                "3.0": "Foi realizado diagnóstico prévio ao planejamento?",
                "3.1": (
                    "O diagnóstico considerou programas federais ou estadual?"
                ),
                "3.1.1": "Quais programas foram utilizados?",
                "3.2": "Os programas do PPA tiveram diagnóstico prévio?",
                "4.0": (
                    "Há estabelecimento de metas físicas e financeiras anuais"
                    " no PPA?"
                ),
                "4.1": "Os programas finalísticos possuem objetivo comum?",
                "4.1.1": "Houve avaliação dos programas finalísticos?",
                "4.1.1.1": "Houve Relatório Anual de Avaliação?",
                "4.1.1.1.1": "Aspectos analisados na avaliação.",
                "4.1.1.2": "Houve publicação dos resultados?",
                "4.1.1.2.1": "Link da divulgação dos resultados.",
                "4.2": "Indicadores são mensuráveis e coerentes?",
                "4.3": "Planos Setoriais incorporados ao PPA.",
                "5.0": "É realizado estudo/análise para previsão de receitas?",
                "5.1": "Tipos de tributos e transferências avaliados.",
                "5.1.1": "Considera previsão de repasse do ICMS?",
                "5.2": "Metodologia varia conforme a espécie da receita?",
                "6.0": "Itens dispostos na LDO.",
                "7.0": (
                    "Houve remanejamento, transposição ou transferência por"
                    " decreto?"
                ),
                "7.1": "Classificação funcional das despesas alteradas.",
                "8.0": "O Anexo de Metas Fiscais integra a LDO?",
                "8.1": "Link de divulgação.",
                "8.2": "Itens constantes do Anexo de Metas Fiscais.",
                "9.0": "O Anexo de Riscos Fiscais integra a LDO?",
                "9.1": "Link de divulgação.",
                "9.2": "Etapas de gerenciamento dos riscos.",
                "10.0": (
                    "Itens que demonstram compatibilidade entre LOA, PPA e LDO."
                ),
                "11.0": (
                    "A LOA prevê abertura de créditos adicionais por decreto?"
                ),
                "11.1": "Percentual autorizado para crédito suplementar.",
                "12.0": (
                    "Há estrutura administrativa voltada ao planejamento?"
                ),
                "12.1": "Há recursos humanos para planejamento?",
                "12.1.1.1": "Equipe possui qualificação técnica?",
                "12.1.2": "Servidores recebem treinamento específico?",
                "13.0": "Há acompanhamento da execução do planejamento?",
                "13.1": (
                    "Metas fiscais são avaliadas em audiências públicas"
                    " quadrimestrais?"
                ),
                "13.1.1": "Foram elaborados Relatórios Quadrimestrais?",
                "13.1.1.1": "Link dos relatórios.",
                "13.2": (
                    "Há acompanhamento mensal da execução orçamentária com"
                    " participação do Prefeito?"
                ),
                "13.3": "O acompanhamento subsidia o replanejamento?",
                "14.0": (
                    "Houve instituição e regulamentação do Sistema de Controle"
                    " Interno?"
                ),
                "14.1": "Instrumento normativo.",
                "14.2": "Link de divulgação.",
                "14.3": "Funções atribuídas ao controle interno.",
                "14.4": "Há recursos humanos para o sistema?",
                "14.4.1": "Responsável ocupa cargo efetivo?",
                "14.4.2": "Equipe recebe treinamento?",
                "14.4.3": "Existe segregação de funções?",
                "14.4.4": "A UCCI possui autonomia?",
                "14.4.4.1": "Vinculação da UCCI.",
                "14.4.4.2": "Houve comunicação de irregularidades?",
                "14.4.4.2.1": "Quantidade de irregularidades comunicadas.",
                "14.4.5": "Há relatórios periódicos?",
                "14.4.5.1": "O Prefeito determinou providências?",
                "14.4.5.1.1": (
                    "O Controle Interno acompanhou as providências?"
                ),
                "14.5": "Houve Plano Operativo Anual?",
                "14.5.1": "Atividades previstas no Plano Operativo Anual.",
                "15.0": "Houve criação da Ouvidoria Pública?",
                "15.1": "Instrumento normativo de criação.",
                "15.2": "Link de divulgação.",
                "15.3": "Link de divulgação.",
                "15.4": "Foi elaborado Relatório de Gestão da Ouvidoria?",
                "15.4.1": (
                    "Informações constantes dos relatórios gerenciais."
                ),
                "15.4.2": "Link do sistema.",
                "15.5": "Iniciativas de divulgação e mobilização social.",
                "16.0": "A Prefeitura elaborou a Carta de Serviços ao Usuário?",
                "16.1": "Link de divulgação.",
                "16.2": "A carta está atualizada?",
                "16.3": "Houve regulamentação da Carta?",
                "16.3.1": "Instrumento normativo.",
                "16.3.2": "Link de divulgação.",
                "17.0": (
                    "A Prefeitura regulamentou e instituiu o Conselho de"
                    " Usuários?"
                ),
                "17.1": "Instrumento normativo.",
                "17.2": "Link de divulgação.",
                "18.0": "O Município elaborou Plano Diretor?",
                "18.1": "Data da última atualização.",
                "19.0": (
                    "Impressões, comentários e sugestões sobre o questionário."
                ),
            },
        },
        "iFiscal": {
                "1.0": (
                    "Há estrutura administrativa voltada para a administração"
                    " tributária?"
                ),
                "1.1": (
                    "O Município possui lei que defina a estrutura"
                    " organizacional da Administração Tributária?"
                ),
                "1.2": (
                    "Qual o número de cargos de fiscais/auditores tributários"
                    " preenchidos?"
                ),
                "1.3": (
                    "Os fiscais tributários recebem treinamento específico para"
                    " execução das atividades inerentes ao cargo?"
                ),
                "1.4": (
                    "O Município possui Plano de Cargos e Salários específico"
                    " para seus fiscais tributários?"
                ),
                "1.4.1": (
                    "Informe o instrumento normativo de regulamentação do Plano"
                    " de Cargos e Salários específico para seus fiscais"
                    " tributários."
                ),
                "1.4.2": (
                    "Informe a página eletrônica de divulgação do Plano de"
                    " Cargos e Salários específico para os fiscais tributários."
                ),
                "1.5": (
                    "Há segregação de funções entre os setores de lançadoria,"
                    " arrecadação, fiscalização e contabilidade?"
                ),
                "1.5.1": (
                    "Há segregação nas permissões de acesso do sistema, com"
                    " identificação do usuário e registro das transações"
                    " efetuadas?"
                ),
                "2.0": (
                    "O servidor responsável pela contabilidade do município é"
                    " ocupante de cargo de provimento efetivo?"
                ),
                "3.0": (
                    "O Município adotou medidas efetivas para aumento da"
                    " arrecadação?"
                ),
                "3.1": (
                    "Assinale as medidas implementadas para aumento da"
                    " arrecadação."
                ),
                "4.0": (
                    "Foi instituído procedimento de revisão do cadastro"
                    " imobiliário estabelecendo a sua periodicidade?"
                ),
                "4.1": (
                    "Informe o instrumento normativo e endereço eletrônico de"
                    " divulgação do procedimento de revisão do cadastro"
                    " imobiliário."
                ),
                "4.2": (
                    "Qual a periodicidade da revisão geral do Cadastro"
                    " Imobiliário?"
                ),
                "4.3": (
                    "O cadastro imobiliário está com a revisão periódica ou"
                    " geral atualizada?"
                ),
                "5.0": (
                    "O instrumento da Planta Genérica de Valores (PGV) foi"
                    " aprovado por lei?"
                ),
                "5.1": "Informe o instrumento normativo de aprovação da PGV.",
                "5.2": "Informe a página eletrônica de divulgação da PGV.",
                "5.3": (
                    "O Código Tributário Municipal prevê revisão periódica"
                    " obrigatória da PGV?"
                ),
                "5.3.1": (
                    "Informe o instrumento normativo de revisão da PGV."
                ),
                "5.3.2": (
                    "Informe a página eletrônica de divulgação da revisão da"
                    " PGV."
                ),
                "5.3.3": "Informe a data da última revisão da PGV.",
                "5.3.4": "Informe a periodicidade de revisão da PGV.",
                "5.4": (
                    "Os dados da PGV e do Cadastro Imobiliário atualizam a base"
                    " de cálculo do IPTU?"
                ),
                "6.0": (
                    "Sobre a alíquota do IPTU, quais critérios o município"
                    " instituiu para a cobrança do imposto?"
                ),
                "7.0": "O município adotou programa de isenção do IPTU?",
                "7.1": (
                    "Informe o instrumento normativo de regulamentação do"
                    " programa de isenção do IPTU."
                ),
                "7.2": (
                    "Informe a página eletrônica de divulgação do programa de"
                    " isenção do IPTU."
                ),
                "7.3": (
                    "Assinale os critérios estabelecidos para a concessão de"
                    " isenção total ou parcial do IPTU."
                ),
                "8.0": "O ISSQN foi instituído no município?",
                "8.1": (
                    "O Município atualizou sua legislação conforme a LC"
                    " 157/2016?"
                ),
                "8.2": (
                    "Houve rotina de fiscalização para detectar sonegação do"
                    " ISSQN?"
                ),
                "8.3": (
                    "A pesquisa de autenticidade de notas fiscais eletrônicas"
                    " está disponível ao público?"
                ),
                "9.0": "O ITBI foi regulamentado?",
                "9.1": (
                    "Informe o instrumento normativo de regulamentação do ITBI."
                ),
                "9.2": (
                    "Informe a página eletrônica de divulgação da"
                    " regulamentação do ITBI."
                ),
                "9.3": (
                    "Assinale a forma de registro e emissão da guia de"
                    " recolhimento do ITBI."
                ),
                "9.4": (
                    "O município instituiu norma para comunicação periódica dos"
                    " Cartórios sobre transmissões imobiliárias?"
                ),
                "9.4.1": (
                    "O município aplica penalidade ou multa aos Cartórios pelo"
                    " descumprimento?"
                ),
                "9.5": "Assinale a forma de recolhimento da guia do ITBI.",
                "9.6": (
                    "O município estabelece alíquotas progressivas para o ITBI?"
                ),
                "10.0": "A CIP/COSIP foi instituída?",
                "10.1": "Informe o instrumento normativo de instituição da CIP.",
                "10.2": "Informe a página eletrônica de divulgação da CIP.",
                "10.3": (
                    "Os recursos da CIP foram movimentados em contas"
                    " específicas?"
                ),
                "11.0": (
                    "Houve regulamentação sobre a retenção de IRRF das"
                    " contratações efetuadas pelo município?"
                ),
                "12.0": (
                    "Houve concessão de benefícios e incentivos com renúncia de"
                    " receita em 2025?"
                ),
                "12.1": (
                    "Há normas e procedimentos relativos à renúncia de receita?"
                ),
                "12.1.1": (
                    "Informe o instrumento normativo de regulamentação dos"
                    " procedimentos relativos à renúncia de receita."
                ),
                "12.1.2": (
                    "Informe a página eletrônica de divulgação da"
                    " regulamentação."
                ),
                "12.2": (
                    "A Prefeitura realizou acompanhamento e reavaliação das"
                    " renúncias de receita?"
                ),
                "12.3": (
                    "O Anexo de Metas Fiscais contém demonstrativo da estimativa"
                    " e compensação da renúncia de receita?"
                ),
                "12.3.1": (
                    "O valor da renúncia de receita de 2025 está compatível com"
                    " a estimativa constante na LDO?"
                ),
                "12.4": "Informe o valor das renúncias no exercício de 2025.",
                "12.5": (
                    "Houve publicidade e transparência dos benefícios"
                    " concedidos por renúncia de receitas?"
                ),
                "12.5.1": (
                    "Assinale as informações divulgadas referentes aos"
                    " benefícios concedidos."
                ),
                "12.5.2": (
                    "Informe a página eletrônica de divulgação dessas"
                    " informações."
                ),
                "13.0": "O município possui regulamentação sobre dívida ativa?",
                "13.1": (
                    "Informe o instrumento normativo de regulamentação da"
                    " dívida ativa."
                ),
                "13.2": (
                    "Informe a página eletrônica de divulgação da regulamentação"
                    " da dívida ativa."
                ),
                "13.3": (
                    "Assinale os critérios estabelecidos na legislação sobre"
                    " dívida ativa."
                ),
                "14.0": (
                    "O Município possui dívida ativa executada de forma judicial"
                    " em 2025?"
                ),
                "14.1": (
                    "Informe o valor total da dívida ativa executada"
                    " judicialmente em 2025."
                ),
                "15.0": (
                    "A Prefeitura realiza cobrança de dívida ativa de forma"
                    " extrajudicial?"
                ),
                "15.1": (
                    "Informe o valor total da dívida ativa cobrada"
                    " extrajudicialmente em 2025."
                ),
                "15.2": (
                    "Assinale as modalidades de cobrança extrajudicial da"
                    " dívida ativa."
                ),
                "16.0": "No exercício de 2025 houve dívidas prescritas?",
                "16.1": (
                    "Informe o valor da dívida ativa prescrita na execução"
                    " judicial em 2025."
                ),
                "16.2": (
                    "Informe o valor da dívida ativa cobrada de forma"
                    " extrajudicial prescrita em 2025."
                ),
                "16.3": (
                    "O montante da dívida ativa prescrita estava registrado na"
                    " conta de Provisão para Perdas de Dívida Ativa?"
                ),
                "17.0": (
                    "A Prefeitura possui controle das ações judiciais em que é"
                    " parte (polo passivo)?"
                ),
                "17.1": (
                    "Descreva de que forma é realizado o controle dessas ações."
                ),
                "17.2": (
                    "Qual o valor atualizado em 31/12/2025 de todas as ações"
                    " judiciais em que é parte?"
                ),
                "18.0": (
                    "Os dados relativos à transparência na gestão fiscal são"
                    " divulgados na página eletrônica do Município?"
                ),
                "18.1": (
                    "Assinale os itens divulgados na página eletrônica do"
                    " Município."
                ),
                "19.0": "Houve divulgação das receitas arrecadadas em tempo real?",
                "19.1": "Assinale os itens da receita divulgados em tempo real.",
                "20.0": "Houve divulgação das despesas executadas em tempo real?",
                "20.1": (
                    "Assinale os itens das despesas divulgados em tempo real."
                ),
                "21.0": (
                    "Houve divulgação de remuneração individualizada por nome"
                    " do agente público?"
                ),
                "21.1": (
                    "Informe a página eletrônica de divulgação da remuneração"
                    " individualizada."
                ),
                "22.0": (
                    "Houve divulgação de diárias e passagens por nome de"
                    " favorecido?"
                ),
                "22.1": (
                    "Informe a página eletrônica de divulgação de diárias e"
                    " passagens."
                ),
                "23.0": (
                    "Os repasses para o RGPS da competência de 2025 foram"
                    " realizados em qual prazo?"
                ),
                "24.0": (
                    "A Prefeitura aderiu a parcelamento de encargos sociais"
                    " junto ao RGPS?"
                ),
                "24.1": (
                    "As parcelas referentes ao parcelamento com vencimento em"
                    " 2025 foram pagas em qual prazo?"
                ),
                "25.0": (
                    "O Município efetuou compensação de encargos sociais junto"
                    " à Receita Federal do Brasil?"
                ),
                "25.1": (
                    "Houve autorização formal da Receita Federal ou decisão"
                    " judicial para realizar as compensações?"
                ),
                "26.0": (
                    "Gostaria de registrar suas impressões, comentários e"
                    " sugestões a respeito do presente questionário?"
                ),
                "F1": "Análise da Receita (Execução Orçamentária)",
                "F2": "Análise da Despesa (Execução Orçamentária)",
                "F3": "Análise do Resultado da Execução Orçamentária",
                "F4": (
                    "Análise do Esforço para Pagamento de Restos a Pagar até o"
                    " Bimestre"
                ),
                "F5": "Análise do Nível de Cancelamento de Restos a Pagar",
                "F6": "Despesas com Pessoal – Poder Executivo",
                "F7": "Despesas com Pessoal – Poder Legislativo",
                "F8": (
                    "Apuração do Resultado Financeiro (Superávit/Déficit)"
                ),
                "F9": "Apuração da Dívida Fundada (Aumento/Redução)",
                "F10": "Apuração dos Pagamentos dos Precatórios",
                "F11": "Repasse de Duodécimos às Câmaras",
                "F12": "Pontualidade na Prestação de Contas",
                "F13": "Dívida Ativa: Percentual de Recebimento",
                "F14": "Dívida Ativa: Percentual de Cancelamento",
                "F15": "Alertas do Sistema AUDESP",
                "F16": "Balancetes Rejeitados",
                "F17": "Resultado Primário (Operacional)",
                "F18": "Índice de Liquidez Imediata",
                "F19": "Limite de Endividamento – Regra de Ouro",
                "F20": "Percentual da Taxa de Investimento",
                "F21": "Relação entre Despesas Correntes e Receitas Correntes",
                "F22": "Liquidez dos Restos a Pagar",
                "F23": (
                    "Análise das Despesas Assumidas nos Últimos Quatro"
                    " Bimestres"
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

        tabelas_map = {
            "iCidade": "respostas",
            "iGov-Ti": "respostas_igov",
            "i-Amb": "respostas_iamb",
            "iPlan": "respostas_iplan",
            "iFiscal": "respostas_ifiscal",  # 👈 Adicionada nova dimensão
        }

        if dimensao not in tabelas_map:
            return {
                "resposta": "Dimensão em teste",
                "detalhes": (
                    f"A dimensão '{dimensao}' não possui tabela configurada."
                ),
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
                # 👈 Tabela respostas_ifiscal utiliza 'quesito' ao invés de 'id'
                if tabela in [
                    "respostas_iamb",
                    "respostas_iplan",
                    "respostas_ifiscal",
                ]:
                    query = f"SELECT * FROM {tabela} WHERE quesito::text = %s AND ano = %s;"
                else:
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
                    detalhes_campo = dados.get("detalhes")

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

                    if detalhes_campo and str(detalhes_campo) not in [
                        "EMPTY_STRING",
                        "{}",
                        "[]",
                        "None",
                        "",
                    ]:
                        detalhe_texto.append(f"Detalhes: {detalhes_campo}")

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

   
