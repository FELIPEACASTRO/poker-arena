# Perfil público fail-closed

Este diretório implementa TLS, autenticação individual OIDC, rate limiting e reverse
proxy com WebSocket. Ele não contém certificado nem credencial e não é ativado pelo
launcher local.

## Pré-requisitos externos

- domínio resolvendo para o host;
- certificado e chave TLS válidos para o domínio;
- cliente confidencial em um IdP OIDC, com callback
  `https://DOMINIO/oauth2/callback` e política explícita de usuários/grupos;
- quatro arquivos fora do checkout: fullchain, chave privada, segredo hexadecimal de
  64 caracteres e configuração completa do oauth2-proxy;
- Docker Engine + Compose v2 em host Linux endurecido.

Não foi encontrado material reutilizável desse tipo no inventário autorizado de
`C:\Users\davis\Workspace\POKER`. Não use CA bundle de dependência como certificado do
servidor nem reutilize chaves pessoais de Kaggle/Hugging Face/Modal.

## Preparação

1. Use `oauth2-proxy.cfg.example` apenas como estrutura. Crie a configuração real fora
   deste repositório, restrinja `email_domains` ou grupos e gere `client_secret` e
   `cookie_secret` no seu gerenciador de segredos.
2. Gere o segredo proxy-backend com CSPRNG (32 bytes, representados por 64 caracteres
   hexadecimais) e grave-o em arquivo externo com ACL mínima.
3. Exporte somente caminhos e o hostname, nunca os valores:

```text
POKER_PUBLIC_HOST=poker.example.org
POKER_PROXY_SHARED_SECRET_FILE=/secure/poker/proxy_shared_secret
POKER_TLS_FULLCHAIN_FILE=/secure/poker/fullchain.pem
POKER_TLS_PRIVATE_KEY_FILE=/secure/poker/privkey.pem
POKER_OAUTH2_PROXY_CONFIG_FILE=/secure/poker/oauth2-proxy.cfg
```

4. Antes de construir, execute o gate sem dependências:

```text
python deploy/production/validate_profile.py
docker compose -f deploy/production/docker-compose.production.yml config --quiet
```

5. Construa e publique por digest em registry privado. Em produção, substitua as tags
   versionadas por digests aprovados pelo scan/SBOM da organização. Só então execute:

```text
python deploy/production/validate_profile.py --homologation
docker compose -f deploy/production/docker-compose.production.yml up -d --build
```

O comando `--homologation` falha deliberadamente no checkout de referência enquanto
qualquer `FROM` ou `image:` ainda estiver somente por tag.

## Critérios de aceitação do ambiente

- somente NGINX possui portas publicadas; backend e oauth2-proxy não aparecem no host;
- HTTP sempre redireciona ao hostname fixo em HTTPS;
- usuário sem sessão vai ao IdP e usuário fora da política recebe negação;
- UI, REST e WSS funcionam após login; cabeçalhos falsificados pelo cliente não passam;
- rajada acima do limite retorna `429` e `Retry-After`;
- TLS scanner aprova protocolo, cadeia, SAN e renovação; logs não contêm cookie/token;
- reinício preserva logs, e backup/restauração foi ensaiado;
- imagens são referenciadas por digest e têm SBOM, scan e assinatura verificados.

## Limites atuais

Este checkout não dispõe de Docker CLI nem OpenSSL; portanto não houve build local,
`nginx -t`, `docker compose config`, handshake TLS ou login OIDC real nesta máquina. O
gate estrutural e os testes FastAPI exercitam os contratos, mas homologação depende dos
testes externos acima. O limite por IP é local a uma instância e deve migrar para WAF ou
estado compartilhado em implantação replicada. O sistema também não implementa ainda
ownership/ACL de mesas por usuário, requisito para multi-tenancy hostil.
Consequentemente, o perfil atual só pode ser usado por um grupo autenticado que confia
no mesmo workspace e aceita compartilhar mesas/logs. Não o exponha a tenants mutuamente
desconfiados.

Referências primárias: [NGINX auth_request](https://docs.nginx.com/nginx/admin-guide/security-controls/configuring-subrequest-authentication/),
[NGINX rate limiting](https://docs.nginx.com/nginx/admin-guide/security-controls/controlling-access-proxied-http/),
[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/) e
[Docker Compose secrets](https://docs.docker.com/reference/compose-file/secrets/).
