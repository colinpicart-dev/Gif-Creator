import ctypes

# Avant toute ouverture d'écran par GTK, pour que le thread du raccourci
# puisse utiliser X11 en même temps que l'interface.
ctypes.CDLL("libX11.so.6").XInitThreads()

from gif_creator.window import main

main()
