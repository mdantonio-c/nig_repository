import csv
from typing import List, Optional

from restapi.config import DATA_PATH
from restapi.connectors import neo4j
from restapi.utilities.logs import log


class Initializer:
    def __init__(self) -> None:
        # enter GeoData in neo4j
        attributes: Optional[List[str]] = None
        graph = neo4j.get_instance()
        with open(DATA_PATH.joinpath("geodata.tsv")) as fd:
            rd = csv.reader(fd, delimiter="\t", quotechar='"')
            for row in rd:
                if not attributes:
                    # use the first row to get the list of attributes
                    attributes = row
                else:
                    props = dict(zip(attributes, row))
                    geodata = graph.GeoData.nodes.get_or_none(**{attributes[0]: row[0]})
                    if not geodata:
                        # create a new one
                        geodata = graph.GeoData(**props).save()
                    else:
                        # check if an update is needed
                        for key, value in props.items():
                            if getattr(geodata, key) != value:
                                setattr(geodata, key, value)
                                geodata.save()

        log.info("GeoData nodes succesfully created")

    # This method is called after normal initialization if TESTING mode is enabled
    def initialize_testing_environment(self) -> None:
        pass
