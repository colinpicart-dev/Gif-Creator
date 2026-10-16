Gif Créator
============

Logiciel de bureau pour Debian 13. Il capture une zone rectangulaire de l’écran, choisie à la souris, puis enregistre un GIF animé.

Lancement
---------

Depuis le dossier du projet :

    ./gif-creator

Ou :

    python3 -m gif_creator

La session doit être X11. Aucun droit administrateur n’est nécessaire.

Dépendances
-----------

Paquets Debian :

- python3
- python3-gi
- gir1.2-gtk-3.0
- python3-pil
- libx11-6
- libxfixes3
- xdg-user-dirs

Installation, si une dépendance manque :

    sudo apt install python3 python3-gi gir1.2-gtk-3.0 python3-pil libx11-6 libxfixes3 xdg-user-dirs

Aucun module pip n’est requis.

Fonctions
---------

1. Choisir la zone
   Le bouton « Choisir la zone » masque la fenêtre principale et ouvre un voile sur l’écran où se trouve le pointeur. Un clic maintenu trace un rectangle bleu. Si une zone existe déjà sur cet écran, elle est affichée tout de suite. Au relâchement, le voile reste ouvert. Le compteur REC est affiché sur le cadre, voyant éteint.

2. Ajuster le cadre
   Quatre carrés marquent les coins. Saisir un coin le déplace. Saisir un côté déplace le cadre sans changer sa taille. Le pointeur devient une flèche de déplacement sur les côtés. Le cadre affiche sa taille en pixels. Un clic à l’intérieur, hors des coins et des côtés, ne modifie rien. Un nouveau tracé commencé en dehors du cadre remplace le rectangle. La validation se fait avec le raccourci « Valider la zone ».

3. Annuler la sélection
   Le raccourci « Annuler la sélection » ferme le voile. La zone précédente, s’il y en a une, ne change pas.

4. Refuser une zone trop petite
   Un rectangle inférieur à 10 × 10 pixels n’est pas gardé. Le message est : « La zone doit mesurer au moins 10 × 10 pixels. » L’ancien cadre, s’il y en a un, reste en place.

5. Mémoriser la zone
   Une zone validée est enregistrée. Au lancement suivant, elle réapparaît et « Démarrer » est actif. Si elle ne coupe plus aucun écran, elle est oubliée.

6. Démarrer l’enregistrement
   Le bouton « Démarrer » reste inactif tant qu’aucune zone valide n’est choisie. La barre d’espace, raccourci « Démarrer ou arrêter », lance aussi l’enregistrement quand une zone est prête. Sans zone, elle affiche « Aucune zone sélectionnée. »
   Au démarrage, la fenêtre principale se masque, sauf si la case « Afficher Gif Créator pendant la prise » est cochée. La case « Afficher le cadre actif » dessine le rectangle autour de la zone, en dehors des pixels capturés, avec le compteur REC collé à l’extérieur de son coin haut droit. Le voyant REC s’allume au démarrage. La barre est vide au départ et pleine quand le compteur atteint la durée maximale. Les deux cases sont décochées au départ et restent utilisables pendant la prise.

7. Arrêter l’enregistrement
   L’enregistrement s’arrête tout seul à la durée maximale. Il peut aussi s’arrêter plus tôt avec la barre d’espace, ou avec le bouton « Arrêter » si la fenêtre est encore accessible. Espace n’est pris comme arrêt global que pendant l’enregistrement. Une barre d’espace maintenue juste après le départ qu’elle a provoqué ne coupe pas la capture : il faut la relâcher, puis la presser de nouveau.

8. Raccourcis
   La fenêtre affiche trois raccourcis, avec leur combinaison :
   - Démarrer ou arrêter : Espace
   - Valider la zone : Entrée
   - Annuler la sélection : Échap
   « Modifier » attend la prochaine combinaison. Le bouton devient « Annuler » et abandonne la saisie sans changer le raccourci. Une combinaison déjà utilisée par une autre action est refusée. Les raccourcis sont mémorisés.

9. Réglages
   - Cadence : de 1 à 30 images par seconde. Valeur initiale : 30.
   - Durée maximale : de 1 à 180 secondes. Valeur initiale : 4.
   - Case « Inclure le curseur ». Valeur initiale : décochée. Sans la case, le curseur n’est pas dans le GIF. Avec la case, il est dessiné sur les images.
   - Case « Afficher Gif Créator pendant la prise ». Valeur initiale : décochée. Cochée, la fenêtre reste visible. Décochée, elle se masque.
   - Case « Afficher le cadre actif ». Valeur initiale : décochée. Cochée, un trait bleu entoure la zone, sans recouvrir son intérieur, et le compteur REC est accroché à l’extérieur du coin haut droit. Le voyant s’allume au déclenchement de la prise.
   Ces réglages, la zone et les raccourcis sont enregistrés dans $XDG_CONFIG_HOME/gif-creator/config.json, ou dans ~/.config/gif-creator/config.json.

   Le poids estimé s’affiche sous la zone. C’est le maximum : une image différente à chaque pas de la cadence, sur toute la durée maximale. Le fichier réel est en général plus léger. Sans zone, le texte est « Poids estimé : en attente d’une zone. »

10. Encodage
    Les images sont gardées en mémoire, puis assemblées en GIF animé. Une palette commune de 256 couleurs est calculée à partir des images, puis appliquée à chacune. Le GIF boucle sans fin. Chaque image dure 1000/cadence millisecondes, arrondi à la milliseconde la plus proche. Les images successives identiques sont regroupées : leur durée s’additionne, et le temps affiché reste le même.

11. Enregistrer sous
    Après l’encodage, un dialogue « Enregistrer sous » s’ouvre. Son dossier initial est Téléchargements (xdg-user-dir DOWNLOAD, sinon ~/Téléchargements, sinon ~/Downloads, sinon le dossier personnel). Le nom proposé est capture-AAAAMMJJ-HHMMSS.gif, à l’heure locale. Le dossier et le nom peuvent être changés. Si le fichier existe déjà, une confirmation est demandée avant le remplacement.

12. Annulation de l’export
    Si le dialogue est annulé, aucun fichier n’est écrit à l’emplacement final. Le bouton « Enregistrer sous » permet de recommencer, jusqu’à la capture suivante.

13. Ouvrir le dossier
    Après un enregistrement réussi, le chemin complet s’affiche. Le bouton « Ouvrir le dossier » montre le fichier dans le gestionnaire de fichiers.

14. Session Wayland
    Si WAYLAND_DISPLAY est défini, le logiciel s’ouvre mais n’enregistre pas. Il affiche la raison en français. La capture Wayland n’est pas prise en charge.

15. Fermeture
    Fermer la fenêtre interrompt une capture en cours et supprime le GIF temporaire qui n’a pas été enregistré.

Limites
-------

- L’enregistrement fonctionne en session X11 seulement.
- La zone est limitée à l’écran qui se trouve sous le pointeur au moment du choix.
- La cadence réelle dépend du temps de lecture de l’écran. Le fichier GIF utilise ensuite un délai fixe par image.
- Le curseur inclus est celui du serveur X11, dessiné par-dessus l’image.

Fichiers
--------

- gif_creator/window.py : fenêtre principale et dialogue d’enregistrement
- gif_creator/selector.py : tracé de la zone et ajustement du cadre
- gif_creator/capture.py : lecture X11 de la zone
- gif_creator/cursor_overlay.py : curseur ajouté si la case est cochée
- gif_creator/encode.py : création du GIF
- gif_creator/hotkey.py : raccourci global d’arrêt
- gif_creator/shortcuts.py : lecture, affichage et comparaison des raccourcis
- gif_creator/config.py : mémorisation des réglages, de la zone et des raccourcis
- gif_creator/paths.py : dossier Téléchargements
- gif_creator/region.py : rectangle, taille minimale et coins
