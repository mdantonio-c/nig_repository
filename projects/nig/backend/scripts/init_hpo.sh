 #!/bin/bash
set -e

pip3 install pronto

if [[ -f "/data/hp.obo" ]];
then
    mv /data/hp.obo /data/hp.obo.bak
fi

wget --quiet http://purl.obolibrary.org/obo/hp.obo -O /data/hp.obo

cd /code/nig/scripts/

time python3 parsing_hpo.py