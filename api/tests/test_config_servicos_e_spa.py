"""
test_config_servicos_e_spa.py — Validação de nomes de serviço e caminhos da SPA

    - nome de serviço com caracteres de injeção é recusado no PUT da config (422);
    - o catch-all da SPA não serve arquivo fora de dashboard/dist (CWE-22).
"""

import pytest

from app.config_defaults import default_config, invalid_service_names
from app.main import _dist_file
from conftest import DASHBOARD_HEADERS


def _config_with_services(services):
    cfg = default_config("windows")
    cfg["operacional"]["critical_services"] = services
    return {"config": cfg}


@pytest.mark.parametrize("name", [
    "x'; Remove-Item C:\\ -Recurse; '",   # fecha a string do PowerShell
    "$(whoami)",
    "svc|calc",
    "--help",                             # vira opção do systemctl
    "",
    "ab\u2019c",                           # aspa tipográfica: o PowerShell trata como aspa
])
async def test_put_config_recusa_nome_de_servico_perigoso(client, server_id, name):
    resp = await client.put(f"/api/v1/servers/{server_id}/config",
                            json=_config_with_services(["W32Time", name]),
                            headers=DASHBOARD_HEADERS)
    assert resp.status_code == 422


async def test_put_config_aceita_nomes_reais(client, server_id):
    services = ["W32Time", "MSSQL$SQLEXPRESS", "getty@tty1", "ssh", "my-app.service"]
    resp = await client.put(f"/api/v1/servers/{server_id}/config",
                            json=_config_with_services(services),
                            headers=DASHBOARD_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["config"]["operacional"]["critical_services"] == services


def test_invalid_service_names_tolera_config_sem_a_chave():
    assert invalid_service_names({}) == []
    assert invalid_service_names(None) == []
    assert invalid_service_names({"operacional": {}}) == []
    assert invalid_service_names({"operacional": {"critical_services": "W32Time"}}) != []


def test_spa_nao_serve_arquivo_fora_do_dist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("INDEX")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("js")
    (tmp_path / "segredo.txt").write_text("SEGREDO")

    assert _dist_file(dist, "assets/app.js") == (dist / "assets" / "app.js").resolve()
    assert _dist_file(dist, "../segredo.txt") is None
    assert _dist_file(dist, "assets/../../segredo.txt") is None
    assert _dist_file(dist, str((tmp_path / "segredo.txt").resolve())) is None  # absoluto
    assert _dist_file(dist, "") is None
    assert _dist_file(dist, "assets") is None        # diretório → cai no index.html
    assert _dist_file(dist, "nao-existe.js") is None
