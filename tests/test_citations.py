"""Offline tests for citation formatting, COD helpers, and BibTeX synthesis."""

from __future__ import annotations

from xrdlab import crossref
from xrdlab.amcsd.client import parse_cif_ids
from xrdlab.cifutil import cif_citation
from xrdlab.citations import extract_dois, record_url
from xrdlab.cod.client import CODClient, _clean_cod_formula, cod_url


def test_crossref_format_work():
    msg = {
        "author": [{"family": "Lany", "given": "Stephan"}, {"family": "Zunger", "given": "Alex"}],
        "title": ["Semiconducting rocksalt ScN"],
        "container-title": ["Physical Review B"],
        "issued": {"date-parts": [[2015]]}, "volume": "92", "page": "075143",
        "DOI": "10.1103/PhysRevB.92.075143",
    }
    out = crossref.format_work(msg)
    assert "Lany, S." in out
    assert "(2015)" in out
    assert "Physical Review B, 92, 075143" in out
    assert "doi:10.1103/PhysRevB.92.075143" in out


def test_crossref_format_empty():
    assert crossref.format_work({}) == ""


def test_extract_dois():
    refs = ["@article{x, doi = {10.1103/PhysRevB.92.075143}}", "no doi here"]
    assert extract_dois(refs) == ["10.1103/PhysRevB.92.075143"]


def test_clean_cod_formula():
    assert _clean_cod_formula("- N1 Sc1 -").split() == ["N1", "Sc1"]


def test_cod_url_and_record_url():
    assert cod_url("1011031").endswith("/1011031.html")
    url, label = record_url("COD-1011031")
    assert label == "COD" and "crystallography.net" in url
    url, label = record_url("mp-2857")
    assert label == "Materials Project" and "materialsproject.org" in url


def test_amcsd_parse_cif_ids():
    html = ('<a href="download.php?id=0011111.cif&down=cif">CIF</a> '
            '<a href="download.php?id=0022222.cif&down=cif">CIF</a> '
            '<a href="download.php?id=0011111.cif&down=amc">amc</a>')
    assert parse_cif_ids(html) == ["0011111", "0022222"]


def test_amcsd_record_url():
    url, label = record_url("AMCSD-0011111")
    assert label == "AMCSD" and "rruff" in url


def test_cif_citation_extraction():
    cif = (
        "_publ_author_name 'Doe, J.'\n_journal_name_full 'J. Test'\n"
        "_journal_year 2001\n_journal_paper_doi 10.1000/x\n"
    )
    cit = cif_citation(cif, "gan", source="CIF")
    assert cit["authors"] == ["Doe, J."]
    assert cit["journal"] == "J. Test"
    assert cit["year"] == "2001"
    assert cit["doi"] == "10.1000/x"
    assert cit["source"] == "CIF"


def test_cod_citation_fields():
    row = {"file": "1011031", "title": "ScN", "journal": "JSSC", "year": "1990",
           "doi": "10.1016/xyz", "authors": "Smith, J.; Doe, A."}
    cit = CODClient._citation(row, "1011031")
    assert cit["source"] == "COD"
    assert cit["material_id"] == "COD-1011031"
    assert cit["authors"] == ["Smith, J.", "Doe, A."]
    assert cit["database_IDs"]["COD"] == ["1011031"]
