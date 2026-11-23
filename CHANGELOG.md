# Histórico de mudanças

Mudanças relevantes são registradas aqui. “Não lançado” reúne o trabalho ainda
não associado a uma versão; exemplos com dados sintéticos não representam o
mercado real.

## Não lançado

### Segurança e API

- Limites de 200 a 3000 dias, 32 ativos/posições e tamanhos de entrada para o
  relatório; valores financeiros devem ser finitos e não negativos. GET e POST
  rejeitam entradas inválidas com 422 antes do cálculo.
- Erros internos deixam de ser expostos na resposta HTTP e no estado de
  aquecimento público. Logs ainda podem conter detalhes e exigem proteção.
- Apenas o núcleo JavaScript é servido em `/comum/comum.js`; outros arquivos
  de `docs/` não são expostos pela API nesse caminho.
- Dependências de testes foram movidas para `requirements-dev.txt`; pytest foi
  atualizado para a faixa 9.0.3 ou superior, fora da faixa identificada pela
  auditoria. A imagem instala apenas `requirements.txt`.

### Testes e automação

- Testes HTTP cobrem limites, erros internos e acesso ao núcleo compartilhado.
- O Dockerfile copia `docs/comum.js`; o CI verifica seu acesso na imagem e a
  ausência do pytest, além do healthcheck.
- Auditorias Python e JavaScript falham o check em PR, mas não bloqueiam a
  publicação diária. O job de publicação é o único com permissão de escrita.

### Documentação

- README revisado para instalação, dois painéis, segurança, testes e CI/CD;
  adicionadas política de segurança e lista de revisão de PR. A API ainda não
  fornece autenticação, limitação de taxa ou TLS e requer proteção externa.
