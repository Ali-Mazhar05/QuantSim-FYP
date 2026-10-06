# Jenkins secrets

Jenkins reads its credentials from files in this folder. Everything here except this
README is ignored by git; never commit these files. Each file holds a single value with
no trailing spaces.

| File | What it is | Where to get it |
|---|---|---|
| `admin_password` | Password of the Jenkins `admin` user | Choose a strong one |
| `github_app_id` | Numeric App ID of the `quantsim-jenkins` GitHub App | GitHub → Settings → Developer settings → GitHub Apps → the app → App ID |
| `github_app_key` | The app's private key in **PKCS#8** format | Generate a private key on the app page, then convert it (below) |
| `ghcr_user` | GitHub username that owns the images | `Ali-Mazhar05` |
| `ghcr_token` | Classic personal access token with `write:packages` and `read:packages` | GitHub → Settings → Developer settings → Personal access tokens (classic) |
| `cloudflare_api_token` | API token with **Account → Cloudflare Pages → Edit** | Cloudflare dashboard → My Profile → API Tokens → Create Token |
| `cloudflare_account_id` | Your Cloudflare account id | Cloudflare dashboard → Workers & Pages → Account ID |
| `sops_age_key` | Jenkins' age private key; its public half is in `.sops.yaml` | Already generated. **Back it up** somewhere safe outside this machine |

## GitHub App

Create it under the Ali-Mazhar05 account and install it **only** on QuantSim-FYP.

- Repository permissions: Contents **read and write** (release tags), Metadata read,
  Pull requests read, Commit statuses **read and write**, Checks **read and write**
- Subscribe to events: Push, Pull request
- Webhook: leave inactive unless Jenkins has a public URL; Jenkins also scans the
  repository every 2 minutes

Jenkins needs the private key in PKCS#8 format:

```bash
openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt \
  -in quantsim-jenkins.<date>.private-key.pem -out github_app_key
```

## After changing a secret

```bash
docker compose -f ci/jenkins/compose.yml up -d --force-recreate
```
