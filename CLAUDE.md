# CLAUDE.md

Librairie Python qui parle au cloud Centrometal (`web-boiler.com`) pour l'intégration Home
Assistant `hass-centrometal-boiler` (dossier voisin). Fork de `9a4gl/py-centrometal-web-boiler`,
publié sur PyPI sous **`py-centrometal-web-boiler-androflo`** ; le module reste `centrometal_web_boiler`.
Le code, les docstrings et les commits sont en anglais.

## Architecture (`src/centrometal_web_boiler/`)

| Fichier | Rôle |
|---|---|
| `const.py` | URLs du site (HTTPS) et du broker STOMP (WebSocket), topics |
| `HttpClient.py` | Session aiohttp : login (formulaire HTML + jeton CSRF, parsé avec lxml), lectures JSON, commandes |
| `HttpHelper.py` | Raccourcis sur la liste des installations (`value` = id, `label` = n° de série) |
| `WebBoilerDeviceCollection.py` | Modèle : collection (par n° de série) → device (dict) → parameter (dict + callbacks) |
| `WebBoilerWsClient.py` | Client STOMP sur `websockets` (API asyncio), tâche de fond, callbacks |
| `WebBoilerClient.py` | Façade publique utilisée par l'intégration |
| `exceptions.py` | `WebBoilerError` |

Flux : `login` → `get_configuration` (instantané HTTPS) → `start_websocket` (temps réel) →
`refresh` (demande aux chaudières de tout renvoyer). Les commandes (`turn`, `turn_circuit`,
`set_pellet_mode`) renvoient `True`/`False` et ne lèvent jamais d'exception.

## Compatibilité avec l'intégration — à ne pas casser

L'intégration utilise : `WebBoilerClient` (`login`, `relogin`, `get_configuration`,
`start_websocket`, `close_websocket`, `refresh`, `turn`, `turn_circuit`, `set_pellet_mode`,
`is_websocket_connected`, `set_connectivity_callback`, `username`, `data`,
`http_client.close_session()`), l'import `from centrometal_web_boiler.WebBoilerDeviceCollection
import WebBoilerParameter`, `device.get_parameter/has_parameter`, `device.username`,
`device["serial"|"type"|"product"|"id"|"place"|"address"|"parameters"|"temperatures"|"circuits"]`,
`parameter["name"|"value"|"timestamp"|"used"]`, `parameter.set_update_callback(cb, tag)`.

C'est pour cela que les fichiers gardent leurs noms en CamelCase. `close_websocket()` puis
`start_websocket()` doivent pouvoir être rappelés sur le même client (reconnexion de l'intégration).

## Choix et pièges

- Un frame STOMP ou un message inattendu est journalisé et ignoré : il ne doit jamais arrêter la
  réception temps réel. Idem pour un groupe inconnu dans les réponses HTTPS (Centrometal peut en ajouter).
- Seuls les paramètres présents dans l'instantané de démarrage sont suivis en temps réel.
- Le corps des requêtes n'est jamais journalisé (le formulaire de login contient le mot de passe).
- Les certificats TLS sont vérifiés. Sur un Python macOS installé depuis python.org, lancer
  « Install Certificates.command » ou exporter `SSL_CERT_FILE=$(python -m certifi)` pour l'exemple.
- `WebBoilerClient(webroot=..., stomp_url=...)` permet de pointer vers un faux serveur (tests).

## Tester

```
pip install -e ".[test]"
pytest                    # faux site + faux broker locaux (tests/fake_server.py), aucun compte requis
ruff check . && ruff format --check .
```

Test manuel avec un vrai compte (lecture seule) :
`CENTROMETAL_USERNAME=... CENTROMETAL_PASSWORD=... python examples/test_client.py --duration 60`.

## Publier

1. Bumper `version` dans `pyproject.toml` (seule source de la version), commit + push sur `main`.
2. Pousser un tag égal à cette version (`git tag 0.1.0 && git push origin 0.1.0`) : le workflow
   `python-publish.yml` vérifie le tag, lance les tests, publie sur PyPI (Trusted Publishing,
   environnement GitHub `pypi`, pas de token) puis crée la release GitHub.
3. Dans l'intégration : bumper le pin `py-centrometal-web-boiler-androflo==<version>` et la
   `version` de `manifest.json`.
