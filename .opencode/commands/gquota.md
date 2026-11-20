---
description: Остаток квоты Gemini Web (подписка AI Pro) и состояние моста
---

Покажи остаток квоты моста «Gemini Web» — выполни и перескажи коротко (без домыслов):

!`/mnt/DiskD/opencode-hub/infra/gemini-web/quota.sh`

Если скрипт вернул ошибку или «мост не запущен» — так и скажи, плюс укажи,
что делать: `systemctl --user status gweb-bridge` и проверка куки
`infra/gemini-web/cookies.json` в песочнице hub.
