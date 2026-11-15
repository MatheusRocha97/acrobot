"""Gera o versao.json com o hash do bot.py e dos prints. Rode antes de subir uma atualização."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
PREFIXOS = ("batalhar", "jogar_novamente", "derrota", "vitoria", "victory", "level_up")


def hash_arquivo(p):
    d = p.read_bytes()
    if p.suffix.lower() == ".py":
        d = d.replace(b"\r\n", b"\n")
    return hashlib.sha256(d).hexdigest()


if not (BASE / "bot.py").exists():
    raise SystemExit("bot.py não encontrado nesta pasta.")

novos = {"bot.py": hash_arquivo(BASE / "bot.py")}
for pasta in (BASE, BASE / "imagens_adb"):
    if pasta.is_dir():
        for p in sorted(pasta.glob("*.png")):
            if p.name.lower().startswith(PREFIXOS):
                novos[p.relative_to(BASE).as_posix()] = hash_arquivo(p)

arq = BASE / "versao.json"
versao, antigos = 1, {}
if arq.exists():
    try:
        atual = json.loads(arq.read_text(encoding="utf-8-sig"))
        versao, antigos = int(atual["versao"]), atual.get("arquivos", {})
    except Exception:
        pass

mudaram = [n for n, h in novos.items() if antigos.get(n) != h]
if arq.exists() and not mudaram and set(antigos) == set(novos):
    print(f"Nada mudou desde a versão {versao}. Nenhum envio necessário.")
else:
    if arq.exists():
        versao += 1
    arq.write_text(json.dumps({"versao": versao, "arquivos": novos}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"versao.json gerado: versão {versao}\n")
    print("Envie para o GitHub (Add file > Upload files):")
    print("  - versao.json")
    for n in mudaram:
        print(f"  - {n}")
