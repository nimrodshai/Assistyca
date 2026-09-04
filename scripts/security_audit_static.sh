#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"

scan() {
  local title="$1"
  shift
  printf '\n## %s\n' "$title"
  rg --hidden --glob '!*.png' --glob '!*.jpg' --glob '!*.jpeg' --glob '!*.gif' \
    --glob '!*.pdf' --glob '!*.pyc' --glob '!*.sqlite' --glob '!*.db' \
    --glob '!*.lock' --glob '!node_modules/**' --glob '!.git/**' "$@" "$ROOT" || true
}

scan "Potential hard-coded secrets" \
  -n "(api[_-]?key|client[_-]?secret|secret[_-]?key|access[_-]?token|refresh[_-]?token|private[_-]?key|password|BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY)"

scan "Dangerous frontend sinks" \
  -n "(dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\\.write|document\\.writeln|eval\\(|new Function|setTimeout\\(\\s*['\"]|setInterval\\(\\s*['\"])"

scan "Browser storage and cross-window messaging" \
  -n "(localStorage|sessionStorage|IndexedDB|postMessage|addEventListener\\(\\s*['\"]message)"

scan "Cookie, CSRF, CORS, and security header markers" \
  -n "(Set-Cookie|HttpOnly|SameSite|Secure|csrf|CSRF|Origin|Referer|Access-Control-Allow|Content-Security-Policy|X-Frame-Options|X-Content-Type-Options|Referrer-Policy|Permissions-Policy)"

scan "Filesystem and artifact serving markers" \
  -n "(send_file|send_from_directory|send_head|translate_path|path\\.join|Path\\(|resolve\\(|relative_to|open\\(|read_bytes|write_bytes|unlink\\(|rmtree|copyfile)"

scan "Command execution and unsafe deserialization markers" \
  -n "(subprocess|os\\.system|Popen|shell=True|pickle|yaml\\.load|marshal\\.loads)"

scan "OAuth and webhook markers" \
  -n "(oauth|OAuth|webhook|Webhook|X-Hub-Signature|WHATSAPP_APP_SECRET|WHATSAPP_VERIFY_TOKEN|GOOGLE_OAUTH|refresh_token|scope)"
