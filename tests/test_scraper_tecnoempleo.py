import pytest

from jobhunting.descarga import Bloqueado
from jobhunting.portales.tecnoempleo.parser import ParserRoto
from jobhunting.portales.tecnoempleo.scraper import URL_BASE, recorrer

URL2 = "https://www.tecnoempleo.com/ofertas-trabajo/?pr=,240,252,262,276,&pagina=2"


class Fetch:
    def __init__(self, paginas):
        self.paginas, self.urls = paginas, []

    def __call__(self, url):
        self.urls.append(url)
        r = self.paginas[url]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def sleeps():
    return []


def _sin_siguiente(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for n in soup.find_all("link", rel="next"):
        n.decompose()
    for n in soup.find_all("a"):
        if n.get_text().strip().lower() == "siguiente":
            n.decompose()
    return str(soup)


def test_p1_p2_fin(html_p1, html_p2, sleeps):
    p2 = _sin_siguiente(html_p2)
    f = Fetch({URL_BASE: html_p1, URL2: p2})
    res = recorrer(fetch=f, sleep=sleeps.append, pausa_s=7)
    assert f.urls == [URL_BASE, URL2]
    assert len(res.ofertas) == 60
    assert res.paginas == 2
    assert res.motivo_parada == "fin"
    assert res.total_anunciado == 640 and not res.bloqueado
    assert sleeps == [7]  # una pausa entre p1 y p2, ninguna antes de p1


def test_max_paginas(html_p1, html_p2, sleeps):
    f = Fetch({URL_BASE: html_p1, URL2: html_p2})
    res = recorrer(fetch=f, max_paginas=2, sleep=sleeps.append, pausa_s=4)
    assert res.motivo_parada == "max_paginas"
    assert res.paginas == 2 and len(res.ofertas) == 60
    assert f.urls == [URL_BASE, URL2]
    assert sleeps == [4]


def test_max_paginas_1_no_duerme(html_p1, sleeps):
    f = Fetch({URL_BASE: html_p1})
    res = recorrer(fetch=f, max_paginas=1, sleep=sleeps.append)
    assert res.paginas == 1 and sleeps == []
    assert res.motivo_parada == "max_paginas"


def test_sin_nuevas_pagina_repetida(html_p1, sleeps):
    f = Fetch({URL_BASE: html_p1, URL2: html_p1})
    res = recorrer(fetch=f, sleep=sleeps.append, pausa_s=1)
    assert res.motivo_parada == "sin_nuevas"
    assert len(res.ofertas) == 30
    assert len({o.clave for o in res.ofertas}) == 30
    assert sleeps == [1]


def test_bloqueado_a_mitad(html_p1, sleeps):
    f = Fetch({URL_BASE: html_p1, URL2: Bloqueado("http_429")})
    res = recorrer(fetch=f, sleep=sleeps.append, pausa_s=2)
    assert res.bloqueado and res.motivo_parada == "bloqueado"
    assert res.detalle == "http_429"
    assert len(res.ofertas) == 30 and res.paginas == 1
    assert sleeps == [2]


def test_bloqueado_en_primera_no_duerme(sleeps):
    f = Fetch({URL_BASE: Bloqueado("403")})
    res = recorrer(fetch=f, sleep=sleeps.append)
    assert res.bloqueado and res.ofertas == [] and sleeps == []


def test_parser_roto_se_propaga(sleeps):
    f = Fetch({URL_BASE: "<html>nada</html>"})
    with pytest.raises(ParserRoto):
        recorrer(fetch=f, sleep=sleeps.append)


def test_descartadas_se_acumulan(html_p1, sleeps):
    f = Fetch({URL_BASE: html_p1})
    res = recorrer(fetch=f, max_paginas=1, sleep=sleeps.append)
    assert res.n_descartadas == 0
