from typing import Optional

from restapi.connectors import neo4j
from restapi.customizer import FlaskApp
from restapi.utilities.logs import log


class Initializer:
    def __init__(self, app: Optional[FlaskApp] = None):
        # enter GeoData in neo4j
        graph = neo4j.get_instance()
        query_for_nodes = """
        USING PERIODIC COMMIT 1000
        LOAD CSV WITH HEADERS
        FROM 'file:///repo/geodata.tsv' AS line
        FIELDTERMINATOR '\t'
        CREATE (:GeoData {
            country: line.country,
            macroarea: line.macroarea,
            region: line.region,
            province:line.province,
            code:line.code,
            population:line.population
            }
        );"""

        graph.cypher(query_for_nodes)
        log.info("GeoData nodes succesfully created")

    # This method is called after normal initialization if TESTING mode is enabled
    def initialize_testing_environment(self) -> None:
        pass
