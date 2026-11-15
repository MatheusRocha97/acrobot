"""
Bot com DOIS modos, ambos com redimensionamento automático dos prints:
  - ADB (emulador LDPlayer): vê a tela do emulador e toca via ADB. Funciona com a
    janela minimizada e NÃO mexe no seu mouse.
  - TELA (fora do emulador): vê todos os monitores do PC e clica com o mouse real,
    devolvendo o mouse para onde estava (como o bot.py antigo). O jogo precisa estar visível.
Escolha em MODO (abaixo) ou na linha de comando:  python bot.py --adb   /   python bot.py --tela
Em "auto", usa o ADB se ele responder; senão cai para o modo TELA.

USA OS MESMOS PRINTS DO bot.py (batalhar*.png, jogar_novamente*.png, derrota*.png,
vitoria*.png, victory*.png, level_up*.png) da pasta do bot. Não precisa recortar de
novo: o bot compara os prints em várias escalas e descobre sozinho o tamanho certo.
Se quiser prints extras só para o ADB, coloque-os na subpasta "imagens_adb".

Loop:
  1) Verifica se houve derrota (derrota*.png). Se sim, o bot para.
  2) Se aparecer a tela de vitória (vitoria*.png), avisa no CMD e conta.
  3) Se aparecer a tela "Victory" (victory*.png), toca nela para acelerar o loading.
  4) Se aparecer a tela de Level Up (level_up*.png), toca para fechar.
  5) Toca em "Batalhar" (batalhar*.png)
  6) Toca em "Jogar novamente" (jogar_novamente*.png)
  7) Se não reconhecer a tela por um tempo, salva uma captura em
     imagens_adb\\capturas_auto para você ver o que apareceu.
  8) Imagens novas colocadas nas pastas são carregadas sozinhas, sem reiniciar.

Como parar: Ctrl+C no terminal (no modo TELA, também: mouse no canto superior esquerdo).
Modo captura (salva um print a cada Enter):  python bot.py --capturar
"""

import ctypes
import io
import json
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# ---------------- Configurações ----------------
MODO = "auto"             # "auto" = ADB se responder, senão tela do PC | "adb" | "tela"
ADB = r"C:\LDPlayer\LDPlayer14\adb.exe"   # adb.exe do LDPlayer 14
DISPOSITIVO = "emulator-5554"    # veja o nome em "adb devices" (instância 0 = emulator-5554)
PASTA = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent    # pasta do bot (prints antigos ficam aqui)
PASTA_IMAGENS = PASTA / "imagens_adb"  # prints extras só para o ADB (opcional)
CONFIANCA = 0.8           # 0 a 1. Se não achar a imagem, diminua (ex.: 0.7)
CONFIANCA_DERROTA = 0.85  # com escala automática, a derrota casa um pouco menos que antes.
                          # Suba (0.9) se parar à toa; baixe (0.8) se não parar numa derrota.
ESCALA_PASSO = 0.05       # passo entre as escalas testadas nos prints
ESCALAS_POR_MODO = {"adb": (0.3, 2.0), "tela": (0.6, 1.5)}  # (mínima, máxima) de cada modo
INTERVALO = 1.0           # segundos entre cada verificação
PAUSA_APOS_CLIQUE = 2     # segundos de espera depois de um toque
VICTORY_CLICAR_REPETIDO = False  # False = 1 toque por aparição da tela Victory
                                 # True  = continua tocando enquanto ela estiver na tela
VICTORY_PAUSA = 0.5       # segundos de espera depois do toque na tela Victory
LIMITE_GROSSO = 0.5       # semelhança mínima na busca rápida (meia resolução) para refinar
FALLBACK_ESPERA = 30      # segundos entre buscas rápidas de um print já calibrado que sumiu
DIAGNOSTICO = True        # mostra no CMD o quanto cada print se parece com a tela (quando nada é achado)
SEM_BOTAO_AVISO = 15      # segundos sem achar nada até avisar (e salvar captura)
ESPERA_CAPTURA_AUTO = 30  # mínimo de segundos entre capturas automáticas
MAX_CAPTURAS_AUTO = 40    # para de salvar capturas automáticas depois disso
# ------------------------------------------------

Imagem = namedtuple("Imagem", "nome cinza chave mtime")
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ESCALAS = []              # definida em definir_escalas() conforme o modo
MODO_ATUAL = None         # "adb" ou "tela", definido ao iniciar

contagem = {}
_ultimo_erro = None       # evita repetir a mesma mensagem de erro
_escala_global = None     # última escala que funcionou (palpite inicial para os prints)
_escala_img = {}          # escala própria de cada print (cada um pode ter tamanho diferente)
_cache_dados = {}         # escalas salvas em disco (escalas_cache.json)
_ultimo_rapido = {}       # quando cada print foi varrido na busca rápida pela última vez
_tamanho_real = None      # tamanho real da última captura do emulador
_ultima_auto = 0.0
_qtd_auto = 0
PREFIXOS = ("batalhar", "jogar_novamente", "derrota", "vitoria", "victory", "level_up")


def hora():
    return time.strftime("%H:%M:%S")


def avisar_erro(msg):
    """Mostra o erro só se for diferente do último."""
    global _ultimo_erro
    if msg != _ultimo_erro:
        _ultimo_erro = msg
        print(f"[{hora()}] {msg}")


# ---------------- Imagens ----------------
def arquivos_do_prefixo(prefixo):
    achados = set(PASTA.glob(f"{prefixo}*.png")) | set(PASTA_IMAGENS.glob(f"{prefixo}*.png"))
    return sorted(achados)


def carregar(prefixo):
    """Carrega os prints que começam com o prefixo (pasta do bot + imagens_adb)."""
    lista = []
    for a in arquivos_do_prefixo(prefixo):
        try:
            rgb = np.array(Image.open(a).convert("RGB"))
            lista.append(Imagem(a.name, cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), str(a), a.stat().st_mtime))
        except Exception as e:
            avisar_erro(f"Não consegui abrir '{a.name}': {e!r}")
    return lista


def carregar_tudo():
    return {p: carregar(p) for p in PREFIXOS}


def assinatura():
    """Muda quando uma imagem é adicionada, removida ou alterada."""
    itens = []
    for p in PREFIXOS:
        for a in arquivos_do_prefixo(p):
            try:
                itens.append((str(a), a.stat().st_mtime))
            except OSError:
                pass
    return tuple(itens)


def resumo(imgs):
    rotulos = {
        "batalhar": "Batalhar", "jogar_novamente": "Jogar novamente", "derrota": "Derrota",
        "vitoria": "Vitória", "victory": "Victory", "level_up": "Level Up",
    }
    for p in PREFIXOS:
        if imgs[p]:
            print(f"Imagens de {rotulos[p]}:", [i.nome for i in imgs[p]])
        else:
            print(f"Sem imagem de {rotulos[p]} ({p}*.png): essa função fica desligada.")
    if not imgs["derrota"]:
        print("AVISO: sem derrota*.png: o bot NÃO vai parar sozinho numa derrota.")


# ---------------- ADB ----------------
def adb(*args, timeout=15):
    """Roda um comando do adb no dispositivo configurado."""
    return subprocess.run(
        [ADB, "-s", DISPOSITIVO, *args],
        capture_output=True,
        timeout=timeout,
        creationflags=SEM_JANELA,
    )


def conectar():
    """Conecta no emulador e confere se o dispositivo respondeu."""
    try:
        # Dispositivos "emulator-XXXX" já aparecem sozinhos no adb; só endereços
        # IP:porta (ex.: 127.0.0.1:5555) precisam de "adb connect".
        if not DISPOSITIVO.startswith("emulator-"):
            r = subprocess.run(
                [ADB, "connect", DISPOSITIVO],
                capture_output=True, text=True, timeout=20,
                creationflags=SEM_JANELA,
            )
            print("adb connect:", (r.stdout or r.stderr).strip())
        estado = adb("get-state")
    except FileNotFoundError:
        print(
            f"Não encontrei o adb em '{ADB}'. Ajuste a variável ADB no topo do "
            f"bot com o caminho completo do adb.exe."
        )
        return False
    if estado.stdout.decode(errors="replace").strip() != "device":
        print(
            "O dispositivo não respondeu. Confira se o emulador está aberto, se o "
            "ADB está ativado (Configurações > Outras > Depuração ADB) e se o nome "
            "em DISPOSITIVO é o mesmo que aparece em 'adb devices'."
        )
        return False
    return True


def capturar_adb():
    """Tira um print da tela do emulador via ADB. Retorna uma imagem PIL ou None."""
    global _tamanho_real
    try:
        r = adb("exec-out", "screencap", "-p")
        if r.returncode != 0 or not r.stdout:
            erro = r.stderr.decode(errors="replace").strip() or "captura vazia"
            raise RuntimeError(erro)
        img = Image.open(io.BytesIO(r.stdout)).convert("RGB")
    except Exception as e:
        avisar_erro(f"Erro ao capturar a tela pelo ADB: {e!r}")
        return None
    _tamanho_real = img.size
    return img


def tocar_adb(x, y):
    """Toca na posição (x, y) da tela do emulador."""
    adb("shell", "input", "tap", str(int(x)), str(int(y)))


# ---------------- Modo TELA (todos os monitores + mouse real) ----------------
class PONTO(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def origem_virtual():
    """Canto superior esquerdo de todos os monitores juntos (pode ser negativo)."""
    u = ctypes.windll.user32
    return u.GetSystemMetrics(76), u.GetSystemMetrics(77)


def posicao_mouse():
    ponto = PONTO()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(ponto))
    return ponto.x, ponto.y


def mover_mouse(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def mover_mouse_virtual(x, y):
    """Reforço: move o cursor usando a tela virtual (todos os monitores juntos)."""
    u = ctypes.windll.user32
    esq, topo = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
    larg, alt = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
    nx = int((int(x) - esq) * 65535 / max(larg - 1, 1)) + 1
    ny = int((int(y) - topo) * 65535 / max(alt - 1, 1)) + 1
    u.mouse_event(0x0001 | 0x8000 | 0x4000, nx, ny, 0, 0)


def devolver_mouse(x, y):
    """Devolve o mouse para (x, y) em qualquer monitor e confere se voltou certo."""
    for tentativa in range(5):
        if tentativa < 3:
            mover_mouse(x, y)
        else:
            mover_mouse_virtual(x, y)
        time.sleep(0.01)
        if posicao_mouse() == (int(x), int(y)):
            return True
    print(f"[{hora()}] Aviso: o mouse voltou para {posicao_mouse()} em vez de {(int(x), int(y))}")
    return False


def clique_esquerdo():
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # botão pressionado
    time.sleep(0.03)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # botão solto


def capturar_tela():
    """Print de TODOS os monitores. Retorna uma imagem PIL ou None."""
    global _tamanho_real
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True).convert("RGB")
    except Exception as e:
        avisar_erro(f"Erro ao capturar a tela do PC: {e!r}")
        return None
    _tamanho_real = img.size
    return img


def tocar_tela(x, y):
    """Clica em (x, y) do print e devolve o mouse para onde estava."""
    ox, oy = origem_virtual()
    antigo = posicao_mouse()
    mover_mouse(x + ox, y + oy)
    time.sleep(0.03)
    clique_esquerdo()
    time.sleep(0.05)
    devolver_mouse(*antigo)


def capturar():
    return capturar_adb() if MODO_ATUAL == "adb" else capturar_tela()


def tocar(x, y):
    if MODO_ATUAL == "adb":
        tocar_adb(x, y)
    else:
        tocar_tela(x, y)


def definir_escalas(modo):
    global ESCALAS
    mn, mx = ESCALAS_POR_MODO[modo]
    ESCALAS = [round(float(e), 2) for e in np.arange(mn, mx + 1e-9, ESCALA_PASSO)]


def escolher_modo():
    """Decide entre ADB e TELA (config MODO ou --adb / --tela). Retorna None se falhar."""
    if "--adb" in sys.argv:
        modo = "adb"
    elif "--tela" in sys.argv:
        modo = "tela"
    else:
        modo = MODO
    if modo == "adb":
        print(f"Modo ADB: conectando no emulador ({DISPOSITIVO})...")
        return "adb" if conectar() else None
    if modo == "tela":
        return "tela"
    print(f"Modo AUTO: tentando o ADB ({DISPOSITIVO})...")
    if conectar():
        return "adb"
    print("ADB indisponível: usando a TELA do PC (o jogo precisa estar visível e o mouse real será usado).")
    return "tela"


# ---------------- Busca de imagens (várias escalas) ----------------
def _cinza(tela):
    g = getattr(tela, "_cinza", None)
    if g is None:
        g = cv2.cvtColor(np.array(tela), cv2.COLOR_RGB2GRAY)
        tela._cinza = g
    return g


def _varrer(pal, imagem, escalas):
    """Testa o print nas escalas dadas. Retorna (pontuação, escala, x, y, larg, alt) ou None."""
    H, W = pal.shape
    melhor = None
    for e in escalas:
        t = imagem.cinza
        if e != 1.0:
            interp = cv2.INTER_AREA if e < 1 else cv2.INTER_LINEAR
            t = cv2.resize(t, None, fx=e, fy=e, interpolation=interp)
        th, tw = t.shape
        if th > H or tw > W or th < 8 or tw < 8:
            continue
        res = cv2.matchTemplate(pal, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if melhor is None or mx > melhor[0]:
            melhor = (mx, e, loc[0], loc[1], tw, th)
    return melhor


def _meia(tela):
    """Tela em metade da resolução (guardada junto da captura para ser reaproveitada)."""
    g = getattr(tela, "_meia", None)
    if g is None:
        g = cv2.resize(_cinza(tela), None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        tela._meia = g
    return g


def _varrer_rapido(tela, imagem):
    """Busca em 2 etapas: grossa (meia resolução, escalas de 2 em 2) e refinada
    (resolução cheia, só perto das melhores). Retorna (melhor ou None, semelhança_grossa)."""
    meia = _meia(tela)
    H, W = meia.shape
    grossas = []
    for e in ESCALAS[::2]:
        f = e * 0.5
        t = cv2.resize(imagem.cinza, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        th, tw = t.shape
        if th > H or tw > W or th < 6 or tw < 6:
            continue
        res = cv2.matchTemplate(meia, t, cv2.TM_CCOEFF_NORMED)
        grossas.append((float(cv2.minMaxLoc(res)[1]), e))
    if not grossas:
        return None, 0.0
    grossas.sort(reverse=True)
    topo = grossas[0][0]
    if topo < LIMITE_GROSSO:
        return None, topo
    candidatas = set()
    for _, e in grossas[:2]:
        for d in (-ESCALA_PASSO, 0, ESCALA_PASSO):
            candidatas.add(round(e + d, 2))
    return _varrer(_cinza(tela), imagem, sorted(candidatas)), topo


def _chave_cache(imagem):
    return f"{MODO_ATUAL}|{_tamanho_real}|{imagem.chave}|{imagem.mtime}"


def _definir_escala(imagem, escala):
    """Guarda a escala do print (memória e disco)."""
    if _escala_img.get(imagem.chave) == escala:
        return
    _escala_img[imagem.chave] = escala
    _cache_dados[_chave_cache(imagem)] = escala
    try:
        (PASTA_IMAGENS / "escalas_cache.json").write_text(
            json.dumps(_cache_dados, indent=1), encoding="utf-8"
        )
    except OSError:
        pass


def carregar_cache(imgs):
    """Usa as escalas salvas de execuções anteriores: sem recalibrar ao abrir o bot."""
    try:
        dados = json.loads((PASTA_IMAGENS / "escalas_cache.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    _cache_dados.update(dados)
    n = 0
    for p in PREFIXOS:
        for im in imgs[p]:
            e = _cache_dados.get(_chave_cache(im))
            if e:
                _escala_img[im.chave] = e
                n += 1
    if n:
        print(f"Escalas carregadas do cache: {n} print(s) já calibrado(s).")


def achar(tela, imagem, confianca=CONFIANCA):
    """Procura o print na tela testando escalas. Retorna o centro (x, y) ou None.
    Ordem: escala do próprio print -> escala global -> busca rápida em todas as escalas."""
    global _escala_global
    try:
        pal = _cinza(tela)
        base = _escala_img.get(imagem.chave, _escala_global)
        melhor = None
        if base is not None:
            melhor = _varrer(pal, imagem, [base, round(base - ESCALA_PASSO, 2), round(base + ESCALA_PASSO, 2)])
        if melhor is None or melhor[0] < confianca:
            # print novo: busca rápida a cada ciclo; já calibrado que sumiu: de vez em quando
            espera = FALLBACK_ESPERA if imagem.chave in _escala_img else 0
            agora = time.time()
            if agora - _ultimo_rapido.get(imagem.chave, 0) >= espera:
                _ultimo_rapido[imagem.chave] = agora
                melhor, _ = _varrer_rapido(tela, imagem)
        if melhor and melhor[0] >= confianca:
            _escala_global = melhor[1]
            _definir_escala(imagem, melhor[1])
            return (melhor[2] + melhor[4] // 2, melhor[3] + melhor[5] // 2)
        return None
    except Exception as ex:
        avisar_erro(f"Erro ao procurar '{imagem.nome}': {ex!r}")
        return None


def diagnosticar(tela, imgs):
    """Mostra o quanto cada print se parece com a tela atual (busca rápida em todas as escalas).
    Os que passarem do limite ficam calibrados e são achados no próximo ciclo."""
    print(f"[{hora()}] Diagnóstico (semelhança de cada print com a tela):")
    for p in PREFIXOS:
        limite = CONFIANCA_DERROTA if p == "derrota" else CONFIANCA
        for im in imgs[p]:
            m, grosso = _varrer_rapido(tela, im)
            if m is None:
                print(f"    {im.nome}: semelhança baixa (melhor {grosso:.2f}) -> não está na tela")
                continue
            ok = m[0] >= limite
            print(f"    {im.nome}: {m[0]:.2f} na escala {m[1]} (limite {limite}) -> {'RECONHECIDO' if ok else 'abaixo do limite'}")
            if ok:
                _definir_escala(im, m[1])


def algum(tela, imagens, confianca=CONFIANCA):
    """True se alguma das imagens estiver visível na tela."""
    return any(achar(tela, i, confianca) for i in imagens)


def clicar_se_achar(tela, imagens, nome):
    """Toca na primeira imagem encontrada na tela. Retorna True se tocou."""
    for imagem in imagens:
        pos = achar(tela, imagem)
        if pos:
            contagem[nome] = contagem.get(nome, 0) + 1
            print(f"[{hora()}] Tocando em {nome} ({contagem[nome]}) ({imagem.nome})")
            tocar(*pos)
            return True
    return False


# ---------------- Capturas de apoio ----------------
def salvar_debug(tela):
    """Salva a captura de teste. Nunca derruba o bot: tenta outro nome se falhar."""
    nomes = ["debug_tela.png", f"debug_tela_{time.strftime('%H%M%S')}.png"]
    for nome in nomes:
        caminho = PASTA_IMAGENS / nome
        try:
            tela.save(caminho)
            print(f"Captura de teste salva em: {caminho}")
            return
        except OSError as e:
            print(f"Não consegui salvar '{nome}' ({e}). Ele pode estar aberto em outro programa.")
    print("Seguindo sem salvar a captura de teste.")


def salvar_desconhecida(tela):
    """Salva a tela atual quando o bot não reconhece nada (com limite de quantidade)."""
    global _ultima_auto, _qtd_auto
    if _qtd_auto >= MAX_CAPTURAS_AUTO or time.time() - _ultima_auto < ESPERA_CAPTURA_AUTO:
        return False
    pasta = PASTA_IMAGENS / "capturas_auto"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"desconhecida_{time.strftime('%H%M%S')}.png"
        tela.save(caminho)
        _ultima_auto = time.time()
        _qtd_auto += 1
        print(f"[{hora()}] Tela não reconhecida salva em: {caminho}")
        return True
    except OSError as e:
        avisar_erro(f"Não consegui salvar a captura automática: {e}")
        return False


def modo_captura():
    """python bot.py --capturar: salva uma captura a cada Enter."""
    global MODO_ATUAL
    PASTA_IMAGENS.mkdir(exist_ok=True)
    MODO_ATUAL = escolher_modo()
    if MODO_ATUAL is None:
        return
    if MODO_ATUAL == "tela":
        ctypes.windll.user32.SetProcessDPIAware()
    print("MODO CAPTURA: deixe o jogo na tela que quer capturar e aperte Enter.")
    print("Ctrl+C para sair.")
    while True:
        input("Enter = capturar... ")
        tela = capturar()
        if tela is None:
            print("Não consegui capturar.")
            continue
        caminho = PASTA_IMAGENS / f"captura_{time.strftime('%H%M%S')}.png"
        try:
            tela.save(caminho)
            print(f"Salvo: {caminho}")
        except OSError as e:
            print(f"Não consegui salvar: {e}")


# ---------------- Programa principal ----------------
def main():
    global _escala_global, MODO_ATUAL
    if "--capturar" in sys.argv:
        modo_captura()
        return
    PASTA_IMAGENS.mkdir(exist_ok=True)

    MODO_ATUAL = escolher_modo()
    if MODO_ATUAL is None:
        return
    definir_escalas(MODO_ATUAL)
    if MODO_ATUAL == "tela":
        # Evita erro de posição quando os monitores têm escala (zoom) diferente
        ctypes.windll.user32.SetProcessDPIAware()
    print(f"Modo em uso: {MODO_ATUAL.upper()}")

    tela = capturar()
    if tela is None:
        print("Não consegui capturar a tela. Parando.")
        return
    salvar_debug(tela)
    print(f"Resolução da captura: {_tamanho_real}")

    imgs = carregar_tudo()
    if not imgs["batalhar"]:
        print(f"\nNenhuma imagem 'batalhar*.png' em {PASTA} nem em {PASTA_IMAGENS}.")
        return
    carregar_cache(imgs)
    resumo(imgs)
    sig = assinatura()

    print("Para parar: Ctrl+C.")
    print("Começando em 3 segundos...")
    time.sleep(3)

    vitorias = 0
    vitoria_visivel = False
    victory_clicado = False
    res_anterior = _tamanho_real
    ultimo_aviso = time.time()
    escala_avisada = None

    while True:
        # Recarrega as imagens se alguma foi adicionada/alterada nas pastas
        nova_sig = assinatura()
        if nova_sig != sig:
            sig = nova_sig
            imgs = carregar_tudo()
            _escala_global = None
            _escala_img.clear()
            carregar_cache(imgs)
            print(f"[{hora()}] Imagens recarregadas:")
            resumo(imgs)

        # Failsafe (modo TELA): mouse no canto superior esquerdo do monitor principal = para
        if MODO_ATUAL == "tela" and posicao_mouse() == (0, 0):
            print(f"[{hora()}] Mouse no canto da tela. Parando o bot.")
            break

        tela = capturar()
        if tela is None:
            time.sleep(INTERVALO)
            continue

        if _tamanho_real != res_anterior:
            print(
                f"[{hora()}] Resolução mudou de {res_anterior} para {_tamanho_real}. "
                f"Recalibrando a escala dos prints."
            )
            res_anterior = _tamanho_real
            _escala_global = None
            _escala_img.clear()

        derrota, vitoria = imgs["derrota"], imgs["vitoria"]
        victory, level_up = imgs["victory"], imgs["level_up"]

        # 1) Derrota é verificada PRIMEIRO, antes de qualquer toque
        if derrota and algum(tela, derrota, CONFIANCA_DERROTA):
            time.sleep(0.5)
            nova = capturar()
            if nova is not None and algum(nova, derrota, CONFIANCA_DERROTA):
                print(f"[{hora()}] Derrota detectada! Parando o bot.")
                break

        # 2) Vitória: avisa uma vez só por batalha
        if vitoria:
            if algum(tela, vitoria):
                if not vitoria_visivel:
                    vitorias += 1
                    print(
                        f"[{hora()}] Batalha concluída com sucesso! "
                        f"Vitórias: {vitorias}"
                    )
                    vitoria_visivel = True
            else:
                vitoria_visivel = False

        # 2.3) Tela Victory: toca nela para acelerar o loading
        if victory:
            if VICTORY_CLICAR_REPETIDO or not victory_clicado:
                if clicar_se_achar(tela, victory, "Victory"):
                    victory_clicado = True
                    time.sleep(VICTORY_PAUSA)
                    continue
                victory_clicado = False  # não achou: libera para o próximo aparecimento
            elif not algum(tela, victory):
                victory_clicado = False  # a tela sumiu: libera um novo toque

        # 2.5) Tela de Level Up: toca para fechar e segue o bot normalmente
        if level_up and clicar_se_achar(tela, level_up, "Level Up"):
            time.sleep(PAUSA_APOS_CLIQUE)
            continue

        # 3) Toques nos botões
        if clicar_se_achar(tela, imgs["batalhar"], "Batalhar") or clicar_se_achar(
            tela, imgs["jogar_novamente"], "Jogar novamente"
        ):
            if _escala_global != escala_avisada:
                escala_avisada = _escala_global
                print(f"[{hora()}] Escala dos prints calibrada: {_escala_global}")
            time.sleep(PAUSA_APOS_CLIQUE)
            ultimo_aviso = time.time()
        else:
            if time.time() - ultimo_aviso >= SEM_BOTAO_AVISO:
                print(f"[{hora()}] Rodando, mas não achei nenhum botão nos últimos {SEM_BOTAO_AVISO}s.")
                if salvar_desconhecida(tela) and DIAGNOSTICO:
                    diagnosticar(tela, imgs)
                ultimo_aviso = time.time()
            time.sleep(INTERVALO)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot parado.")