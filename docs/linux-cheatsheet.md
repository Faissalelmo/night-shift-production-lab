# Aide-mémoire Linux — commandes des runbooks

Les commandes utilisées dans `runbooks/`, expliquées brièvement. Dans le lab, la plupart
s'exécutent dans un conteneur via `docker compose exec <service> <commande>`.

## Conteneurs (Docker Compose)

| Commande | Rôle |
|---|---|
| `docker compose ps` | État de chaque service : `running`, `exited`, `healthy`… |
| `docker compose logs --since 30m jobs` | Logs d'un service sur une fenêtre de temps. `--tail 50` : les 50 dernières lignes ; `-f` : suivre en continu. |
| `docker compose exec jobs <cmd>` | Lancer une commande dans un conteneur en cours d'exécution. `-T` : sans terminal (scripts, redirections). |
| `docker compose stop/start/restart postgres` | Arrêter / démarrer / redémarrer un service sans le supprimer. |
| `docker compose cp jobs:/data/outbox ./outbox-copy` | Copier des fichiers d'un conteneur vers le poste. |
| `docker stats --no-stream` | Photo instantanée CPU / mémoire / I/O de chaque conteneur. |

## Fichiers et répertoires

| Commande | Rôle |
|---|---|
| `ls -la inbox/` | Contenu d'un répertoire, fichiers cachés inclus (`-a`), en format long (`-l`). |
| `ls -lt archive/*.csv \| head -n 3` | Trier par date de modification, plus récent d'abord (`-t`) ; ne garder que 3 lignes. |
| `find archive -name '*.csv' -mmin -30` | Fichiers modifiés il y a moins de 30 minutes. `-mmin +60` : il y a plus d'une heure. |
| `find /data/outbox -name '*.part'` | Rechercher des fichiers partiels laissés par une écriture interrompue. |
| `wc -l fichier` | Compter les lignes (ex. : lignes d'un CSV, résultats d'un `find`). |
| `sha256sum a b` | Empreinte d'un fichier : même empreinte = même contenu, quel que soit le nom. |
| `tail -n 20 fichier` / `tail -f fichier` | Fin d'un fichier ; `-f` suit les ajouts en direct (logs). |
| `grep '"error_type": "disk_full"' fichier` | Lignes contenant un motif. `-c` : compter ; `-i` : sans casse ; `-v` : inverser. |
| `cut -c1-200` | Tronquer chaque ligne (lisibilité des logs JSON longs). |
| `sort -rh` | Trier des tailles « humaines » (`4.9M`, `12K`) de la plus grande à la plus petite. |
| `rm -f fichier` | Supprimer un fichier sans confirmation. **À n'utiliser qu'après identification certaine.** |

## Disque

| Commande | Rôle |
|---|---|
| `df -h /data/outbox` | Espace total / utilisé / libre du système de fichiers qui contient ce chemin. |
| `du -ah /data/outbox \| sort -rh \| head` | Qui occupe la place : taille de chaque fichier et dossier, les plus gros d'abord. |
| `dd if=/dev/zero of=/data/outbox/.ballast bs=64k` | Écrire des zéros jusqu'à saturation (utilisé par `inject.sh disk_full` pour remplir le volume). |

> `df` mesure le système de fichiers, `du` additionne les fichiers. Un écart important entre les deux
> signale souvent un fichier supprimé mais encore ouvert par un processus.

## Processus

| Commande | Rôle |
|---|---|
| `ps -eo pid,etime,cmd` | Processus avec PID, durée d'exécution (`etime`) et ligne de commande. |
| `pgrep -a supercronic` | Le processus existe-t-il ? (`-a` : affiche la commande complète). |
| `kill <pid>` | Demander l'arrêt d'un processus (SIGTERM). `kill -9` en dernier recours seulement. |

## Planification (cron)

Format d'une ligne de crontab : `minute heure jour-du-mois mois jour-de-semaine commande`.

```
*/5 * * * *   run-job import_settlement_file     # toutes les 5 minutes
0 2 * * *     run-job daily_extract              # tous les jours à 02:00
```

Le lab utilise `supercronic`, un cron conçu pour les conteneurs (journalise sur la sortie
standard, transmet les signaux). La crontab est générée au démarrage : `docker compose exec jobs cat /tmp/crontab`.

## PostgreSQL

| Commande | Rôle |
|---|---|
| `pg_isready -U lab -d payments` | La base accepte-t-elle des connexions ? Code retour 0 si oui. |
| `psql -U lab -d payments -c "<SQL>"` | Exécuter une requête et sortir. |
| `SELECT … FROM pg_stat_activity` | Sessions et requêtes en cours : durée (`now() - query_start`), état, attente (`wait_event_type`). |
| `pg_blocking_pids(pid)` | PID des sessions qui bloquent une session donnée (verrous). |
| `SELECT pg_cancel_backend(pid)` | Annuler la requête en cours d'une session (la session reste ouverte). |
| `SELECT pg_terminate_backend(pid)` | Couper la session entière. Plus brutal : sur validation DBA. |
| `count(*) - count(DISTINCT rrn)` | Nombre de doublons sur une clé : doit valoir 0. |

## Réseau / HTTP

| Commande | Rôle |
|---|---|
| `curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' URL` | Code HTTP et temps de réponse d'une URL, sans afficher la page. |
| `curl -fs URL` | `-f` : code retour non nul si HTTP ≥ 400 (utile dans les scripts et les healthchecks). |
