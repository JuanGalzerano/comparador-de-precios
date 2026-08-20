"""Tests del filtro de texto por tokens (`app/api/routers/search.py`).

El caso que motiva todo esto: pegar el link de un producto en el buscador produce una
consulta de doce palabras salida del slug de la URL, y buscarla como frase entera no
matchea nada en ninguna otra tienda.
"""

from __future__ import annotations

import pytest

from app.api.routers.search import (
    _is_model_number,
    _live_term,
    _relaxations,
    _text_filter,
    _tokenize,
)

SLUG_ML = "placa de video nvidia gigabyte geforce rtx 5080 windforce oc 16g gddr7"


def test_tokenize_saca_stopwords_y_repetidos():
    assert _tokenize("placa de video de la rtx") == ["placa", "video", "rtx"]


def test_tokenize_corta_en_el_tope():
    from app.api.routers.search import _MAX_TOKENS

    assert len(_tokenize(SLUG_ML)) == _MAX_TOKENS


def test_tokenize_ignora_puntuacion_y_acentos():
    assert _tokenize("Notebook 15,6\" Lenovo — 8GB") == ["notebook", "15", "lenovo", "8gb"]


@pytest.mark.parametrize(
    "token,esperado",
    [
        ("5080", True),
        ("4090", True),
        ("128", True),
        ("13", False),  # dos cifras aparecen dentro de cualquier codigo: no discriminan
        ("16gb", False),  # cada tienda lo escribe distinto (16GB / 16 GB / 16g)
        ("gddr7", False),
        ("rtx", False),
    ],
)
def test_is_model_number(token, esperado):
    assert _is_model_number(token) is esperado


def test_consulta_vacia_no_filtra():
    assert _text_filter(None) is None
    assert _text_filter("   ") is None


def test_una_palabra_arma_filtro():
    assert _text_filter("notebook") is not None


class TestLiveTerm:
    """El termino que se le manda al buscador de cada tienda."""

    def test_consulta_corta_se_manda_tal_cual(self):
        assert _live_term("rtx 5090") == "rtx 5090"
        assert _live_term("  iphone 13  ") == "iphone 13"

    def test_slug_largo_se_recorta(self):
        recortado = _live_term(SLUG_ML)
        assert recortado == "placa video nvidia 5080"

    def test_el_recorte_conserva_el_numero_de_modelo(self):
        """Sin el modelo, la tienda devuelve cualquier placa de video."""
        assert "5080" in _live_term(SLUG_ML)

    def test_el_recorte_es_mas_corto_que_el_original(self):
        assert len(_live_term(SLUG_ML).split()) < len(SLUG_ML.split())


class TestRelaxations:
    """La cascada que suelta palabras cuando la busqueda exacta no encuentra nada."""

    def test_suelta_del_final_no_del_principio(self):
        """Los titulos van de lo general a lo especifico: lo primero es lo que importa."""
        tokens = ["placa", "video", "nvidia", "gigabyte", "geforce"]
        assert _relaxations(tokens)[0] == ["placa", "video", "nvidia", "gigabyte"]

    def test_va_de_mas_a_menos_exigente(self):
        largos = [len(t) for t in _relaxations(_tokenize(SLUG_ML))]
        assert largos == sorted(largos, reverse=True)

    def test_nunca_baja_de_dos_palabras(self):
        for intento in _relaxations(_tokenize(SLUG_ML)):
            assert len(intento) >= 2

    def test_descarta_palabras_de_una_o_dos_letras(self):
        """Buscando por subcadena, "no" matchea "Notebook" y devolveria basura."""
        intentos = _relaxations(["no", "existe", "ningun", "producto"])
        assert all("no" not in intento for intento in intentos)

    def test_consulta_de_dos_palabras_no_se_afloja(self):
        """Ya es el minimo: aflojarla la convertiria en una sola palabra generica."""
        assert _relaxations(["rtx", "5090"]) == []

    def test_tiene_tope(self):
        from app.api.routers.search import _MAX_RELAXATIONS

        assert len(_relaxations(_tokenize(SLUG_ML))) <= _MAX_RELAXATIONS


class TestBusquedaAflojadaEnElEndpoint:
    """De punta a punta: el caso del link pegado en el buscador.

    `seeded_db` trae el cluster "Apple iPhone 13 128 GB" (4 publicaciones) y una
    "Remera Nike Sportswear Club".
    """

    def test_titulo_largo_no_devuelve_vacio(self, client, seeded_db):
        """Pegar un link produce una consulta de muchas palabras que no matchea exacto.

        Antes de la cascada esto daba cero resultados para un producto que la base tiene.
        """
        resp = client.get(
            "/search",
            params={"q": "apple iphone 13 128 gb midnight libre de fabrica sellado", "live": "false"},
        )
        body = resp.json()

        assert body["total"] >= 1
        assert body["items"][0]["canonical_title"] == "Apple iPhone 13 128 GB"

    def test_avisa_cuando_aflojo_la_busqueda(self, client, seeded_db):
        """Sin el aviso, el usuario cree que el buscador le ignoro lo que pidio.

        La base tiene un iPhone 13; se busca un 15 de 256 GB. El numero de modelo es
        obligatorio, asi que la busqueda exacta no encuentra nada y hay que aflojar
        hasta soltarlo.
        """
        resp = client.get(
            "/search",
            params={"q": "apple iphone 15 pro max 256 gb titanio natural", "live": "false"},
        )
        body = resp.json()

        assert body["total"] >= 1
        assert body["relaxed_query"], "tendria que informar con que consulta encontro"
        assert "256" not in body["relaxed_query"], "solto el modelo que no existia"
        assert len(body["relaxed_query"].split()) < 8

    def test_busqueda_exacta_no_marca_nada(self, client, seeded_db):
        """Si encontro con lo que se pidio, no hay nada que avisar."""
        resp = client.get("/search", params={"q": "iphone", "live": "false"})
        body = resp.json()

        assert body["total"] == 1
        assert body["relaxed_query"] is None

    def test_consulta_sin_relacion_sigue_dando_vacio(self, client, seeded_db):
        """Aflojar no puede degenerar en 'devolver cualquier cosa'."""
        resp = client.get(
            "/search", params={"q": "no existe ningun producto asi", "live": "false"}
        )
        body = resp.json()

        assert body["total"] == 0
        assert body["items"] == []
