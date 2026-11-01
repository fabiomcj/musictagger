#!/bin/zsh
TASK_APP_DIR="${0:A:h}"
cd "$TASK_APP_DIR" || exit 1
if [[ ! -x "$TASK_APP_DIR/.venv/bin/python3" ]]; then
  print "Manca l’ambiente di TagPuliti. Segui le istruzioni nel file LEGGIMI.md."
  read "?Premi Invio per chiudere."
  exit 1
fi
print "TagPuliti si aprirà nel browser. Lascia questa finestra aperta durante l’utilizzo."
print "Per chiudere il programma, premi Ctrl+C qui."
"$TASK_APP_DIR/.venv/bin/python3" "$TASK_APP_DIR/app.py"
