"""Votos por secao no mapa, agrupados por local eleitoral oficial TSE.

Em coordenadas iguais nao inventa deslocamento de secoes; o ponto
mostra o local de votacao, popup revela a situacao individual de suas
secoes. Sem coordenadas, o resultado permanece na tabela.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

import folium
import polars as pl
from folium.plugins import MarkerCluster

from mapa_eleicoes.map_tiles import atlas_map
from mapa_eleicoes.vote_gradients import percentage_shade, legend_html

KEYS = ["uf", "cd_municipio_tse", "zona", "secao", "turno"]


def load_sections(
    data_root: Path, year: int, uf: str, municipio_codes: list[str],
    cargo: str, turno: int, zona: int | None = None,
    secao: int | None = None,
) -> pl.DataFrame:
    """Filtra no scan por UF/município antes de materializar em memória."""
    if uf == "Todas" or not municipio_codes:
        return pl.DataFrame()
    # Arquivos separados por UF: evita abrir os Parquets nacionais a cada zoom.
    path = data_root / "serving" / str(year) / "secoes" / f"secoes_{uf}.parquet"
    if not path.exists():
        return pl.DataFrame()
    lazy = pl.scan_parquet(path).filter(
        (pl.col("uf") == uf)
        & pl.col("cd_municipio_tse").is_in(municipio_codes)
        & (pl.col("cargo") == cargo)
        & (pl.col("turno") == turno)
    )
    if zona is not None:
        lazy = lazy.filter(pl.col("zona") == zona)
    if secao is not None:
        lazy = lazy.filter(pl.col("secao") == secao)
    return lazy.collect()


def load_locations(data_root: Path, year: int, uf: str, codes: list[str],
                   turno: int) -> pl.DataFrame:
    path = data_root / "serving" / str(year) / "locais.parquet"
    if not path.exists():
        return pl.DataFrame()
    return (
        pl.scan_parquet(path)
        .filter(
            (pl.col("uf") == uf)
            & (pl.col("turno") == turno)
            & pl.col("cd_municipio_tse").is_in(codes)
        ).collect()
    )


def section_detail(
    votes: pl.DataFrame, places: pl.DataFrame,
    selected_number: str | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, int]:
    """Retorna (secoes com percentuais, locais consolidados, sem coordenada).

    Votos validos nominais sao o denominador; branco, nulo e legenda
    nao sao somados como validos de candidato.
    """
    if votes.is_empty():
        return pl.DataFrame(), pl.DataFrame(), 0
    nominal = votes.filter(pl.col("tipo_voto") == "nominal")
    if nominal.is_empty():
        return pl.DataFrame(), pl.DataFrame(), 0
    if places.is_empty():
        return pl.DataFrame(), pl.DataFrame(), nominal.select(KEYS).unique().height
    duplicates = (
        places.group_by(KEYS).len().filter(pl.col("len") > 1)
    )
    if not duplicates.is_empty():
        # Dois enderecos registrados para uma secao/turno nao podem ser
        # resolvidos arbitrariamente; falhar evita cartografia falsa.
        raise ValueError("Cadastro TSE com multiplos locais para a mesma secao/turno")
    candidates = nominal.group_by(KEYS + ["numero", "candidato"]).agg(
        pl.col("votos").sum()
    )
    totals = candidates.group_by(KEYS).agg(
        pl.col("votos").sum().alias("total_validos")
    )
    scored = candidates.join(totals, on=KEYS, how="left").with_columns(
        (pl.col("votos") * 100.0 / pl.col("total_validos")).alias("pct")
    )
    winners = (
        scored.sort(KEYS + ["votos", "numero"],
                    descending=[False] * len(KEYS) + [True, False])
        .unique(subset=KEYS, keep="first", maintain_order=True)
        .rename({"numero": "numero_lider", "candidato": "lider",
                 "votos": "votos_lider", "pct": "pct_lider"})
    )
    joined = winners.join(places, on=KEYS, how="left", validate="m:1")
    no_geo = joined.filter(
        pl.col("latitude").is_null() | pl.col("longitude").is_null()
    ).height
    valid = joined.filter(
        pl.col("latitude").is_not_null() & pl.col("longitude").is_not_null()
    )
    if selected_number is not None:
        selected_votes = (
            scored.filter(pl.col("numero") == selected_number)
            .select(KEYS + [pl.col("pct").alias("pct_selecionado")])
        )
        valid = valid.join(selected_votes, on=KEYS, how="left").with_columns(
            pl.col("pct_selecionado").fill_null(0.0)
        )
    if valid.is_empty():
        return valid, pl.DataFrame(), no_geo
    # Agregacao por LOCAL faz sentido para marcadores coincidentes.
    group = ["uf", "cd_municipio_tse", "turno", "zona", "local",
             "latitude", "longitude", "nome_local", "endereco"]
    sites = valid.group_by(group).agg(
        pl.col("secao").n_unique().alias("n_secoes"),
        pl.col("total_validos").sum().alias("total_validos"),
    )
    # Vencedor agregado do local usa votos reais por candidato, nao media
    # de percentuais de secoes.
    votes_at_places = nominal.join(places, on=KEYS, how="inner", validate="m:1")
    site_candidate = (
        votes_at_places.group_by(group + ["numero", "candidato"])
        .agg(pl.col("votos").sum())
        .join(sites.select(group + ["total_validos"]), on=group, how="inner")
        .with_columns((pl.col("votos") * 100.0 / pl.col("total_validos")).alias("pct"))
    )
    best = (
        site_candidate.sort(group + ["votos", "numero"],
                            descending=[False] * len(group) + [True, False])
        .unique(subset=group, keep="first", maintain_order=True)
        .select(group + [
            pl.col("numero").alias("numero_lider"),
            pl.col("candidato").alias("lider"),
            pl.col("pct").alias("pct_lider"),
        ])
    )
    sites = sites.join(best, on=group, how="left")
    if selected_number is not None:
        selected = site_candidate.filter(
            pl.col("numero") == selected_number
        ).select(group + [pl.col("pct").alias("pct_selecionado")])
        sites = sites.join(selected, on=group, how="left").with_columns(
            pl.col("pct_selecionado").fill_null(0.0)
        )
    return valid, sites, no_geo


def render_site_points(
    sections: pl.DataFrame, sites: pl.DataFrame, *,
    selected_number: str | None = None,
    max_sites: int = 1800,
) -> tuple[folium.Map, int, int]:
    """Mapa de enderecos oficiais com seção no popup, sem geometria falsa."""
    if sites.is_empty():
        raise ValueError("Nao ha locais georreferenciados para a selecao")
    sites = sites.sort(["n_secoes", "local"], descending=[True, False])
    total = sites.height
    truncated = total > max_sites
    sites = sites.head(max_sites)
    lat = float(sites["latitude"].mean())
    lon = float(sites["longitude"].mean())
    mapa = atlas_map([lat, lon])
    cluster = MarkerCluster(name="Locais de votação").add_to(mapa)
    # Tabela de seções por local: indexada em Python, sem Pandas.
    key_columns = ["uf", "cd_municipio_tse", "turno", "zona", "local"]
    by_site = {}
    for entry in sections.iter_rows(named=True):
        key = tuple(str(entry[c]) for c in key_columns)
        by_site.setdefault(key, []).append(entry)
    for site in sites.iter_rows(named=True):
        key = tuple(str(site[c]) for c in key_columns)
        details = sorted(by_site.get(key, []), key=lambda x: int(x["secao"]))
        pct = (
            site.get("pct_selecionado", 0.0)
            if selected_number is not None else site["pct_lider"]
        )
        number = selected_number or site["numero_lider"]
        color = percentage_shade(number, pct)
        entries = "".join(
            "<tr>"
            f"<td>{int(row['secao'])}</td>"
            f"<td>{escape(str(row['lider']))}</td>"
            f"<td>{float(row['pct_lider']):.2f}%</td>"
            "</tr>"
            for row in details[:60]
        )
        more = (
            f"<p>Mais {len(details) - 60} seções neste local.</p>"
            if len(details) > 60 else ""
        )
        heading = escape(str(site["nome_local"] or site["local"]))
        endereco = escape(str(site["endereco"] or "Endereço não informado"))
        body = (
            f"<b>{heading}</b><br>{endereco}<br>"
            f"Local {escape(str(site['local']))} — "
            f"{site['n_secoes']} seções, {site['total_validos']:,} votos válidos"
            f"<br>Mais votado: {escape(str(site['lider']))} "
            f"({float(site['pct_lider']):.2f}%)"
            + (
                f"<br>Votação do número {escape(str(selected_number))}: "
                f"{float(pct):.2f}% dos votos nominais"
                if selected_number is not None else ""
            )
            + "<hr><table style='width:100%'><tr>"
            "<th>Seção</th><th>Mais votado</th><th>% válidos</th></tr>"
            + entries + "</table>" + more
            + "<p style='font-size:11px'>Ponto do local de votação, "
            "não é perímetro geográfico da seção.</p>"
        )
        folium.CircleMarker(
            location=[float(site["latitude"]), float(site["longitude"])],
            radius=7, fill=True, color="#f8f8f2", weight=0.5,
            fill_color=color, fill_opacity=0.92,
            popup=folium.Popup(body, max_width=420),
            tooltip=f"{heading} · {int(site['n_secoes'])} seções · {float(pct):.1f}%",
        ).add_to(cluster)
    mapa.get_root().html.add_child(
        folium.Element(legend_html("percentual"))
    )
    if len(sites):
        lat_min, lat_max = sites["latitude"].min(), sites["latitude"].max()
        lon_min, lon_max = sites["longitude"].min(), sites["longitude"].max()
        if lat_min != lat_max or lon_min != lon_max:
            mapa.fit_bounds([[float(lat_min), float(lon_min)],
                             [float(lat_max), float(lon_max)]])
        else:
            # Ajuste apenas da CAMERA quando todos os locais coincidirem.
            # Nao move nem inventa coordenadas das secoes eleitorais.
            mapa.fit_bounds([
                [float(lat_min) - 0.014, float(lon_min) - 0.014],
                [float(lat_max) + 0.014, float(lon_max) + 0.014],
            ])
    return mapa, total, total - sites.height if truncated else 0


def site_feature_group(
    sections: pl.DataFrame, sites: pl.DataFrame, *,
    selected_number: str | None = None,
    max_sites: int = 1800,
) -> tuple[folium.FeatureGroup, int, int]:
    """Camada dinamica para st_folium sem reconstruir o mapa nacional.

    O componente streamlit-folium remove a FeatureGroup anterior
    quando os marcadores mudam ao aproximar/arrastar o mapa.
    """
    site_map, total, hidden = render_site_points(
        sections, sites, selected_number=selected_number, max_sites=max_sites
    )
    layer = folium.FeatureGroup(name="Locais TSE por secao")
    clusters = [
        child for child in site_map._children.values()
        if isinstance(child, MarkerCluster)
    ]
    if len(clusters) != 1:
        raise ValueError("Camada de locais de votacao nao foi criada")
    layer.add_child(clusters[0])
    return layer, total, hidden
