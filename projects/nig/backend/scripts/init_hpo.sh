 #!/bin/bash
set -e

pip3 install pronto

if [[ -f "${DATA_IMPORT_FOLDER}/hp.obo" ]];
then
    mv ${DATA_IMPORT_FOLDER}/hp.obo ${DATA_IMPORT_FOLDER}/hp.obo.bak
fi

echo "Downloading http://purl.obolibrary.org/obo/hp.obo ..."
wget --quiet http://purl.obolibrary.org/obo/hp.obo -O ${DATA_IMPORT_FOLDER}/hp.obo

echo "hp.obo successfully downloaded, starting parser"

cd /code/nig/scripts/

time python3 parsing_hpo.py