#!/bin/sh
# Re-extracts the widget's strings into po/tuya-light.pot and merges them
# into every po/*.po. Run after changing any i18n() text in the QML.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
find plasma -name '*.qml' -print0 | sort -z | xargs -0 \
    xgettext --from-code=UTF-8 --language=JavaScript \
    -ki18n:1 -ki18nc:1c,2 -ki18np:1,2 -ki18ncp:1c,2,3 \
    --package-name=tuya-light \
    --msgid-bugs-address=https://github.com/YakupEmreYerli/tuya-light/issues \
    -o po/tuya-light.pot
for po in po/*.po; do
    [ -e "$po" ] || continue
    msgmerge --quiet --update --backup=none "$po" po/tuya-light.pot
done
