"""
limpar_historico.py
-------------------
Remove duplicatas do historico.json, mantendo a entrada mais recente
para cada combinação (data + moeda).

Uso:
    python limpar_historico.py                  # lê e salva docs/historico.json
    python limpar_historico.py historico.json   # arquivo customizado
"""

import json
import sys
import os

caminho = sys.argv[1] if len(sys.argv) > 1 else "docs/historico.json"

if not os.path.exists(caminho):
    print(f"Arquivo não encontrado: {caminho}")
    sys.exit(1)

with open(caminho, 'r', encoding='utf-8') as f:
    historico = json.load(f)

total_antes = len(historico)

visto = {}
for entrada in historico:
    chave = (entrada['data'], entrada['moeda'])
    visto[chave] = entrada  # sobrescreve — mantém a mais recente

historico_limpo = list(visto.values())
total_depois = len(historico_limpo)
removidas = total_antes - total_depois

with open(caminho, 'w', encoding='utf-8') as f:
    json.dump(historico_limpo, f, ensure_ascii=False, indent=4)

print(f"✅ Concluído! {total_antes} entradas → {total_depois} entradas ({removidas} duplicatas removidas)")
