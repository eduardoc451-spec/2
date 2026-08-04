import logging
import pandas as pd
import streamlit as st

# Importa a conexão com o PostgreSQL do seu projeto
try:
    from database import get_connection
except ImportError:
    try:
        from db import get_connection
    except ImportError:

        def get_connection():
            raise NotImplementedError(
                "Função get_connection() não encontrada no projeto."
            )


def buscar_soma_pontos(tabela: str, ano: int) -> float:
    """Consulta a soma dos pontos de uma tabela no PostgreSQL de forma isolada e segura."""
    ano_str = str(ano)

    try:
        with get_connection() as conn:
            # Garante que a transação comece limpa
            try:
                conn.rollback()
            except Exception:
                pass

            with conn.cursor() as cursor:
                # Consulta flexível convertendo ano para texto e somando 'pontos'
                sql = f"""
                    SELECT COALESCE(SUM(pontos), 0)
                    FROM {tabela}
                    WHERE CAST(ano AS TEXT) = %s
                """
                cursor.execute(sql, (ano_str,))
                res = cursor.fetchone()

                if res and res[0] is not None:
                    return float(res[0])
    except Exception as e:
        logging.warning(
            f"[IEG-M Final] Consulta na tabela {tabela} (Ano {ano}) falhou/não existe: {e}"
        )

    return 0.0


# =============================================================================
# FUNÇÕES DE LEITURA DAS DIMENSÕES
# =============================================================================


def puxar_nota_iplan(ano: int) -> int:
    return int(round(buscar_soma_pontos("respostas_iplan", ano)))


def puxar_nota_ifiscal(ano: int) -> int:
    """Carrega i-Fiscal e aplica regra de rebaixamento crítico (<-100 zerando a dimensão)."""
    ano_str = str(ano)
    try:
        with get_connection() as conn:
            try:
                conn.rollback()
            except Exception:
                pass

            with conn.cursor() as cursor:
                sql = "SELECT pontos FROM respostas_ifiscal WHERE CAST(ano AS TEXT) = %s"
                cursor.execute(sql, (ano_str,))
                rows = cursor.fetchall()

                if not rows:
                    return 0

                pontos_lista = [
                    float(r[0]) for r in rows if r[0] is not None
                ]

                # Rebaixamento crítico
                if any(p <= -100.0 for p in pontos_lista):
                    return 0

                total = sum(p for p in pontos_lista if p > -100.0)
                return int(round(total))
    except Exception as e:
        logging.warning(f"[i-Fiscal] Falha ao ler ano {ano}: {e}")
        return 0


def puxar_nota_ieduc(ano: int) -> int:
    return int(round(buscar_soma_pontos("respostas_ieduc", ano)))


def puxar_nota_isaude(ano: int) -> int:
    return int(round(buscar_soma_pontos("respostas_isaude", ano)))


def puxar_nota_iamb(ano: int) -> int:
    return int(round(buscar_soma_pontos("respostas_iamb", ano)))


def puxar_nota_icidade(ano: int) -> int:
    return int(round(buscar_soma_pontos("respostas_icidade", ano)))


def puxar_nota_igov(ano: int) -> int:
    return int(round(buscar_soma_pontos("respostas_igov", ano)))


# =============================================================================
# CÁLCULOS TCESP
# =============================================================================


def calcular_nota_final(
    plan: float,
    fiscal: float,
    educ: float,
    saude: float,
    amb: float,
    cidade: float,
    gov: float,
) -> int:
    """Calcula a Média Ponderada oficial do IEG-M TCESP (escala 0 a 1000)."""
    try:
        soma = (
            (float(plan) * 20)
            + (float(fiscal) * 20)
            + (float(educ) * 20)
            + (float(saude) * 20)
            + (float(amb) * 10)
            + (float(cidade) * 5)
            + (float(gov) * 5)
        )
        return int(round(soma / 100.0))
    except Exception:
        return 0


def obter_faixa_classificacao(nota: int):
    if nota >= 900:
        return "A (Altamente Efetiva)", "#10B981"
    elif nota >= 750:
        return "B+ (Muito Efetiva)", "#3B82F6"
    elif nota >= 600:
        return "B (Efetiva)", "#F59E0B"
    elif nota >= 500:
        return "C+ (Em Fase de Adequação)", "#F97316"
    else:
        return "C (Baixo Nível de Adequação)", "#EF4444"


# =============================================================================
# EXIBIÇÃO NO STREAMLIT
# =============================================================================


def mostrar_painel_iegm_final(ano_selecionado: int):
    st.subheader(
        "🏆 Consolidação do Índice de Efetividade da Gestão Municipal (IEG-M)"
    )

    anos = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    registro_historico = []

    # Lê as notas reais no PostgreSQL
    for ano in anos:
        plan = puxar_nota_iplan(ano)
        fiscal = puxar_nota_ifiscal(ano)
        educ = puxar_nota_ieduc(ano)
        saude = puxar_nota_isaude(ano)
        amb = puxar_nota_iamb(ano)
        cidade = puxar_nota_icidade(ano)
        gov = puxar_nota_igov(ano)

        nota_f = calcular_nota_final(
            plan, fiscal, educ, saude, amb, cidade, gov
        )
        faixa, _ = obter_faixa_classificacao(nota_f)

        registro_historico.append(
            {
                "Ano": ano,
                "i-Plan": plan,
                "i-Fiscal": fiscal,
                "i-Educ": educ,
                "i-Saúde": saude,
                "i-Amb": amb,
                "i-Cidade": cidade,
                "i-Gov TI": gov,
                "Nota Final": nota_f,
                "Faixa": faixa.split(" (")[0],
            }
        )

    df_historico = pd.DataFrame(registro_historico)

    # Cálculo da variação percentual
    variacoes = ["-"]
    for i in range(1, len(df_historico)):
        nota_ant = df_historico.loc[i - 1, "Nota Final"]
        nota_at = df_historico.loc[i, "Nota Final"]

        if nota_ant == 0:
            variacoes.append("▲ +100.0%" if nota_at > 0 else "0.0%")
        else:
            pct = ((nota_at - nota_ant) / nota_ant) * 100
            if pct > 0:
                variacoes.append(f"▲ +{pct:.1f}%")
            elif pct < 0:
                variacoes.append(f"▼ {pct:.1f}%")
            else:
                variacoes.append("0.0%")

    df_historico["Variação %"] = variacoes

    # Reordenar
    colunas_ordenadas = [
        "Ano",
        "i-Plan",
        "i-Fiscal",
        "i-Educ",
        "i-Saúde",
        "i-Amb",
        "i-Cidade",
        "i-Gov TI",
        "Nota Final",
        "Variação %",
        "Faixa",
    ]
    df_historico = df_historico[colunas_ordenadas]

    # Filtra o ano selecionado
    df_ano_atual = df_historico[df_historico["Ano"] == int(ano_selecionado)]
    dados_ano_atual = (
        df_ano_atual.iloc[0]
        if not df_ano_atual.empty
        else df_historico.iloc[0]
    )

    nota_f_atual = dados_ano_atual["Nota Final"]
    faixa_atual, cor_atual = obter_faixa_classificacao(nota_f_atual)

    st.markdown("---")
    st.markdown(
        f"### Resultado Consolidado Real: Ano de Referência {ano_selecionado}"
    )

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        st.metric(
            label="Nota Final Calculada", value=f"{int(nota_f_atual)} pts"
        )
    with c2:
        st.markdown("**Faixa TCESP:**")
        st.markdown(
            f"<div style='padding: 8px; border-radius: 8px; background-color: {cor_atual}; color: white; text-align: center; font-weight: bold;'>{faixa_atual}</div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.info(
            "💡 **Fórmula TCESP:** `(i-Plan×20 + i-Fiscal×20 + i-Educ×20 + i-Saúde×20 + i-Amb×10 + i-Cidade×5 + i-Gov TI×5) / 100`"
        )

    st.markdown("#### Desempenho das Dimensões (Escala 0-1000)")
    dados_tabela_atual = pd.DataFrame(
        {
            "Dimensão": [
                "i-Plan",
                "i-Fiscal",
                "i-Educ",
                "i-Saúde",
                "i-Amb",
                "i-Cidade",
                "i-Gov TI",
            ],
            "Peso TCESP": ["20%", "20%", "20%", "20%", "10%", "5%", "5%"],
            "Pontuação Obtida": [
                dados_ano_atual["i-Plan"],
                dados_ano_atual["i-Fiscal"],
                dados_ano_atual["i-Educ"],
                dados_ano_atual["i-Saúde"],
                dados_ano_atual["i-Amb"],
                dados_ano_atual["i-Cidade"],
                dados_ano_atual["i-Gov TI"],
            ],
        }
    )

    st.dataframe(
        dados_tabela_atual.style.set_properties(
            **{"text-align": "center"}
        ).hide(axis="index"),
        use_container_width=True,
    )

    st.markdown("---")
    st.markdown("### 📊 Painel Evolutivo — Série Histórica Real (2023 a 2030)")

    df_grafico = df_historico.set_index("Ano")[["Nota Final"]]
    st.bar_chart(df_grafico)

    st.markdown("#### 📅 Matriz de Dados Históricos Consolidados")
    df_exibicao = df_historico.set_index("Ano")
    st.dataframe(
        df_exibicao.style.set_properties(**{"text-align": "center"}),
        use_container_width=True,
    )

    # =========================================================================
    # DIAGNÓSTICO DO BANCO DE DADOS (EXPANSÍVEL)
    # =========================================================================
    with st.expander(
        f"🛠️ Diagnóstico do PostgreSQL (Verificar se há dados no Ano {ano_selecionado})"
    ):
        st.write(
            "Abaixo está a verificação direta nas tabelas do seu banco de dados:"
        )

        tabelas_para_testar = [
            "respostas_igov",
            "respostas_icidade",
            "respostas_iplan",
            "respostas_ifiscal",
            "respostas_ieduc",
            "respostas_isaude",
            "respostas_iamb",
            "respostas",
        ]

        relatorio_db = []
        for tab in tabelas_para_testar:
            try:
                with get_connection() as conn:
                    with conn.cursor() as cursor:
                        # Verifica se tabela existe e quantos registros tem para o ano
                        cursor.execute(
                            f"SELECT COUNT(*), COALESCE(SUM(pontos), 0) FROM {tab} WHERE CAST(ano AS TEXT) = %s",
                            (str(ano_selecionado),),
                        )
                        qtd, soma = cursor.fetchone()
                        relatorio_db.append(
                            {
                                "Tabela": tab,
                                "Status": "Existe no DB",
                                "Qtd Registros": qtd,
                                "Soma dos Pontos": float(soma),
                            }
                        )
            except Exception as err:
                relatorio_db.append(
                    {
                        "Tabela": tab,
                        "Status": f"Não encontrada / Erro ({err})",
                        "Qtd Registros": 0,
                        "Soma dos Pontos": 0.0,
                    }
                )

        st.dataframe(pd.DataFrame(relatorio_db), use_container_width=True)
