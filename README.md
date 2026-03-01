# Élections Idéales

Récupération des notes de communes depuis [www.ville-ideale.fr](https://www.ville-ideale.fr/) et groupement par affiliation politique à partir des résultats des élections municipales de 2020.

## :spoon: Scraping (`scrape_ville_ideale.py`)

Construit la liste des communes à partir des résultats des élections municipales 2020 (premier et second tour), récupère leurs notes sur ville-ideale.fr, et enrichit chaque commune avec sa [nuance politique et sa famille politique](https://www.legifrance.gouv.fr/download/pdf/circ?id=44929). Les communes qui n'ont pas d'étiquette politique (i.e. moins de 3500 habitants) sont ignorées.

Les fichiers d'élections sont téléchargés automatiquement depuis data.gouv.fr si absents. Les pages HTML sont mises en cache localement dans `html_pages/`; seules les pages manquantes sont récupérées à chaque exécution.

Le scraping utilise `tls_client` avec une empreinte TLS Chrome et envoie le callback JavaScript `sijs()` après chaque page pour éviter la détection anti-bot. Avec l'option `--wifi`, le script fonctionne par groupe de 100 pages et réinitialise le Wi-Fi entre chaque lot pour obtenir une nouvelle IP (hotspot mobile).

```
python3 scrape_ville_ideale.py              # Récupérer les pages manquantes + générer le JSON
python3 scrape_ville_ideale.py --wifi       # Réinitialiser le Wi-Fi entre les groupes
python3 scrape_ville_ideale.py --delay 5    # Délai personnalisé entre les requêtes (secondes)
```

Le résultat est écrit dans `villes_ratings.json`. Un fichier généré le 22 février est disponible dans la branche [villes_ratings_20260222](https://github.com/PyvesB/elections-ideales/tree/villes_ratings_20260222).

## :chart_with_upwards_trend: Analyse (`analyze_ratings.py`)

Calcule la moyenne ou la médiane des notes par affiliation politique (famille politique ou nuance politique), avec un filtre optionnel par département.

```
python3 analyze_ratings.py                            # Moyenne par famille politique
python3 analyze_ratings.py --by nuance_politique      # Moyenne par nuance politique
python3 analyze_ratings.py --median                   # Médiane au lieu de la moyenne
python3 analyze_ratings.py --dept 75                  # Filtrer sur Paris (dept 75)
python3 analyze_ratings.py --dept 13 --median         # Bouches-du-Rhône, médiane
```

## :e-mail: Support

Une idée ou besoin d'aide ? N'hésitez pas à ouvrir une "pull request" ou un [**ticket**](https://github.com/PyvesB/elections-ideales/issues) ! Vous trouvez le project utile, amusant ou intéressant ? Pensez à mettre une **étoile** :star: sur le dépôt en cliquant sur l'icône en haut à droite de cette page !

# :books: Dépendances

- Python 3.10+
- [`tls_client`](https://pypi.org/project/tls-client/) (scraping uniquement)

Les scripts ont été générés avec l'aide de Claude.

# :copyright: License

Les scripts Python sont soumis à la licence GNU Affero General Public License v3.0. Toute utilisation, modification ou distribution du code source disponible dans ce dépôt ne pourra se faire que sous réserve du respect des conditions de ladite licence.
