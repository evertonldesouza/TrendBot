# Segurança

## Comunicação de vulnerabilidades

Evite publicar detalhes exploráveis, segredos ou dados de carteira em issues
públicas. Envie um relato privado para **evertonldesouza@proton.me**, com
versão/commit afetado, impacto, passos mínimos de reprodução e, se possível,
uma correção sugerida. Não inclua credenciais nem dados reais desnecessários.
Não há prazo garantido de resposta ou política formal de recompensa.

## Escopo e operação

O TrendBot apenas gera análises e sugestões: não executa ordens e não precisa
de credenciais de corretora. A API não implementa autenticação, autorização,
controle de taxa ou TLS. Não a exponha à internet sem proteção externa e
limitação de recursos. Informações de carteira no GET podem ficar em URLs e
logs; prefira POST sobre HTTPS e evite registrar corpos de requisição. A
recomendação publicada no GitHub Pages é pública.

As validações e a resposta genérica a erros reduzem a superfície de ataque,
mas não garantem disponibilidade nem confidencialidade. Restrinja o acesso a
logs, backups, variáveis de ambiente e dados locais; roteadores e proxies podem
registrar dados independentemente da aplicação. Proteja a branch principal
com revisão humana e checks obrigatórios nas configurações do repositório.

## Dependências e CI

O CI verifica dependências Python de produção e desenvolvimento com
`pip-audit`, e o lockfile de desenvolvimento JavaScript com `npm audit`. Em PR,
a auditoria falha o check se encontrar vulnerabilidades ou não puder concluir;
em execuções agendadas ou outros eventos, registra o problema sem bloquear a
publicação diária. A suíte Python continua sendo pré-requisito da publicação.

As versões Python usam intervalos, não lockfile: a auditoria resolve versões na
hora e pode divergir de um ambiente ou imagem existente. Uma auditoria sem
achados não é garantia de segurança. Ao corrigir uma dependência, execute os
testes, documente impactos e reconstrua a imagem; investigações ou exceções
precisam registrar justificativa e prazo de revisão.
